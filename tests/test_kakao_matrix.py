"""KakaoMobilityMatrix 테스트 (실제 API 호출 X — 모두 mock)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.data.models import VRPTWPlace
from src.validation.kakao_matrix import KakaoMobilityMatrix


def _place(name: str, lng: float, lat: float) -> VRPTWPlace:
    return VRPTWPlace(
        name=name,
        lng=lng,
        lat=lat,
        open="09:00",
        close="22:00",
        stay_duration=60,
        is_depot=False,
    )


def _ok_response() -> MagicMock:
    """카카오 정상 응답 mock — duration 600초."""
    m = MagicMock()
    m.status_code = 200
    m.json.return_value = {
        "routes": [
            {
                "summary": {"duration": 600, "distance": 5000},
                "sections": [{"duration": 600}],
            }
        ],
    }
    return m


def _httpx_sync_client(response: MagicMock) -> MagicMock:
    """httpx.Client() context manager mock."""
    client = MagicMock()
    client.get.return_value = response
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=client)
    cm.__exit__ = MagicMock(return_value=False)
    return cm


# ---------------------------------------------------------------------------
# Same point → zero
# ---------------------------------------------------------------------------


class TestSamePoint:
    def test_same_coords_returns_zero(self):
        m = KakaoMobilityMatrix(api_key="dummy")
        p = _place("A", 127.0, 37.5)
        assert m.get_travel_time(p, p) == 0


# ---------------------------------------------------------------------------
# Cache + sync API (_call_kakao_sync)
# ---------------------------------------------------------------------------


class TestApiCall:
    def test_sync_call_populates_cache(self):
        m = KakaoMobilityMatrix(api_key="dummy")
        a = _place("A", 127.0, 37.5)
        b = _place("B", 127.1, 37.6)

        with patch(
            "src.validation.kakao_matrix.httpx.Client",
            return_value=_httpx_sync_client(_ok_response()),
        ):
            result = m._call_kakao_sync(a, b)

        assert result == 600
        assert m.stats["api_success"] == 1

    def test_get_travel_time_uses_cache_after_sync_call(self):
        m = KakaoMobilityMatrix(api_key="dummy")
        a = _place("A", 127.0, 37.5)
        b = _place("B", 127.1, 37.6)

        with patch(
            "src.validation.kakao_matrix.httpx.Client",
            return_value=_httpx_sync_client(_ok_response()),
        ):
            m._call_kakao_sync(a, b)

        result = m.get_travel_time(a, b)
        assert result == 600
        assert m.stats["cache_hit"] == 1
        assert m.cache_size == 1

    def test_get_travel_time_second_call_cache_hit(self):
        m = KakaoMobilityMatrix(api_key="dummy")
        a = _place("A", 127.0, 37.5)
        b = _place("B", 127.1, 37.6)

        with patch(
            "src.validation.kakao_matrix.httpx.Client",
            return_value=_httpx_sync_client(_ok_response()),
        ):
            m._call_kakao_sync(a, b)

        m.get_travel_time(a, b)  # 1st hit
        m.get_travel_time(a, b)  # 2nd hit
        assert m.stats["cache_hit"] == 2

    def test_reverse_direction_also_cached(self):
        m = KakaoMobilityMatrix(api_key="dummy")
        a = _place("A", 127.0, 37.5)
        b = _place("B", 127.1, 37.6)

        with patch(
            "src.validation.kakao_matrix.httpx.Client",
            return_value=_httpx_sync_client(_ok_response()),
        ):
            m._call_kakao_sync(a, b)

        result = m.get_travel_time(b, a)  # reverse 방향
        assert result == 600
        assert m.stats["cache_hit"] == 1


# ---------------------------------------------------------------------------
# Quota exhaustion — 429
# ---------------------------------------------------------------------------


class TestQuotaExhaustion:
    def test_429_sets_quota_exhausted(self):
        m = KakaoMobilityMatrix(api_key="dummy")
        a = _place("A", 127.0, 37.5)
        b = _place("B", 127.1, 37.6)

        resp_429 = MagicMock()
        resp_429.status_code = 429

        with patch(
            "src.validation.kakao_matrix.httpx.Client", return_value=_httpx_sync_client(resp_429)
        ):
            result = m._call_kakao_sync(a, b)

        assert result is None
        assert m.is_quota_exhausted is True

    def test_get_travel_time_haversine_fallback_when_no_cache(self):
        m = KakaoMobilityMatrix(api_key="dummy")
        a = _place("A", 127.0, 37.5)
        b = _place("B", 127.1, 37.6)

        result = m.get_travel_time(a, b)  # cache miss → haversine
        assert result > 0
        assert m.stats["fallback"] == 1

    def test_after_quota_exhausted_get_travel_time_falls_back(self):
        m = KakaoMobilityMatrix(api_key="dummy")
        m._quota_exhausted = True
        a = _place("A", 127.0, 37.5)
        b = _place("B", 127.1, 37.6)
        result = m.get_travel_time(a, b)
        assert result > 0
        assert m.stats["fallback"] == 1


# ---------------------------------------------------------------------------
# Auth error
# ---------------------------------------------------------------------------


class TestAuthError:
    def test_401_raises(self):
        resp_401 = MagicMock()
        resp_401.status_code = 401

        m = KakaoMobilityMatrix(api_key="invalid")
        a = _place("A", 127.0, 37.5)
        b = _place("B", 127.1, 37.6)

        with patch(
            "src.validation.kakao_matrix.httpx.Client", return_value=_httpx_sync_client(resp_401)
        ):
            with pytest.raises(RuntimeError, match="인증 오류"):
                m._call_kakao_sync(a, b)


# ---------------------------------------------------------------------------
# Cache persistence
# ---------------------------------------------------------------------------


class TestCachePersistence:
    def test_save_and_load_cache(self, tmp_path):
        cache_file = tmp_path / "route_cache.json"

        m1 = KakaoMobilityMatrix(api_key="dummy", cache_path=cache_file, save_every=1)
        a = _place("A", 127.0, 37.5)
        b = _place("B", 127.1, 37.6)

        with patch(
            "src.validation.kakao_matrix.httpx.Client",
            return_value=_httpx_sync_client(_ok_response()),
        ):
            m1._call_kakao_sync(a, b)
        m1.save_cache()

        assert cache_file.exists()
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        assert len(data) == 1

        m2 = KakaoMobilityMatrix(api_key="dummy", cache_path=cache_file)
        result = m2.get_travel_time(a, b)
        assert result == 600
        assert m2.stats["cache_hit"] == 1


# ---------------------------------------------------------------------------
# from_env
# ---------------------------------------------------------------------------


class TestFromEnv:
    def test_no_key_raises(self, monkeypatch):
        monkeypatch.delenv("KAKAO_MOBILITY_KEY", raising=False)
        monkeypatch.delenv("KAKAO_REST_API_KEY", raising=False)
        with pytest.raises(ValueError, match="API key 누락"):
            KakaoMobilityMatrix.from_env(env_path="/nonexistent/.env")

    def test_uses_mobility_key_first(self, monkeypatch):
        monkeypatch.setenv("KAKAO_MOBILITY_KEY", "MOBILITY_KEY")
        monkeypatch.setenv("KAKAO_REST_API_KEY", "REST_KEY")
        m = KakaoMobilityMatrix.from_env(env_path="/nonexistent/.env")
        assert m._api_key == "MOBILITY_KEY"

    def test_falls_back_to_rest_key(self, monkeypatch):
        monkeypatch.delenv("KAKAO_MOBILITY_KEY", raising=False)
        monkeypatch.setenv("KAKAO_REST_API_KEY", "REST_KEY")
        m = KakaoMobilityMatrix.from_env(env_path="/nonexistent/.env")
        assert m._api_key == "REST_KEY"


# ---------------------------------------------------------------------------
# aprefetch_matrix (async)
# ---------------------------------------------------------------------------


class TestAsyncPrefetch:
    def test_aprefetch_populates_cache_and_hit_on_get(self):
        """aprefetch_matrix 후 get_travel_time이 캐시를 사용한다."""

        m = KakaoMobilityMatrix(api_key="dummy")
        a = _place("A", 127.0, 37.5)
        b = _place("B", 127.1, 37.6)

        # 캐시를 직접 채워서 aprefetch 결과 시뮬레이션
        m._cache[m._make_key(a, b)] = 600

        result = m.get_travel_time(a, b)
        assert result == 600
        assert m.stats["cache_hit"] == 1

    def test_aprefetch_deduplicates_bidirectional(self):
        """A→B 캐시 존재 시 B→A prefetch는 스킵된다."""
        import asyncio

        async def fake_acall(origin, dest):
            return 700

        m = KakaoMobilityMatrix(api_key="dummy")
        a = _place("A", 127.0, 37.5)
        b = _place("B", 127.1, 37.6)

        # A→B 미리 캐시
        m._cache[m._make_key(a, b)] = 600

        # aprefetch 호출 — B→A는 reverse key가 캐시에 있어 스킵
        with patch.object(m, "_acall_kakao", new=AsyncMock(side_effect=fake_acall)):
            asyncio.run(m.aprefetch_matrix([a, b]))

        # B→A는 스킵됐으므로 cache 크기 변화 없음 (A→B만 있음)
        assert m.cache_size == 1
