"""Tests for ExplainEngine (TDD) — LLM은 mock으로 대체."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.data.models import (
    DayPlan,
    ExplanationItem,
    HardFail,
    ItineraryPlan,
    PlaceInput,
    Scores,
    Warning,
)
from src.explain.explain_engine import (
    ExplainEngine,
    _build_user_prompt,
    _cache_key,
    _fallback,
    _parse_llm_response,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_plan() -> ItineraryPlan:
    return ItineraryPlan(
        days=[DayPlan(places=[PlaceInput(name="경복궁"), PlaceInput(name="남산공원")])],
        party_size=2,
        party_type="친구",
        date="2026-05-10",
    )


def make_scores() -> Scores:
    return Scores(efficiency=0.8, feasibility=0.7, purpose_fit=0.9, flow=0.6, area_intensity=0.5)


def make_hard_fail() -> HardFail:
    return HardFail(
        fail_type="OPERATING_HOURS_CONFLICT",
        message="'경복궁' 도착 예정 18:30, 운영 종료 18:00 — 이미 문을 닫았습니다.",
        evidence="arrive=1110 close=1080",
        confidence="High",
        poi_name="경복궁",
    )


def make_warning() -> Warning:
    return Warning(
        warning_type="DENSE_SCHEDULE",
        message="총 일정 소요 시간 780분(13.0시간)이 '친구' 그룹 피로도 한계 12시간을 초과합니다.",
        confidence="High",
    )


# ---------------------------------------------------------------------------
# _cache_key
# ---------------------------------------------------------------------------

class TestCacheKey:
    def test_same_inputs_same_key(self):
        hf = [make_hard_fail()]
        w = [make_warning()]
        p = {"cluster_dispersion": 10}
        assert _cache_key(hf, w, p, 45) == _cache_key(hf, w, p, 45)

    def test_different_score_different_key(self):
        hf = [make_hard_fail()]
        assert _cache_key(hf, [], {}, 45) != _cache_key(hf, [], {}, 50)

    def test_empty_inputs(self):
        key = _cache_key([], [], {}, 80)
        assert isinstance(key, str) and len(key) == 32


# ---------------------------------------------------------------------------
# _build_user_prompt
# ---------------------------------------------------------------------------

class TestBuildUserPrompt:
    def test_contains_plan_info(self):
        prompt = _build_user_prompt([], [], {}, {}, None, make_plan(), 80)
        assert "친구" in prompt
        assert "2026-05-10" in prompt

    def test_hard_fail_in_prompt(self):
        prompt = _build_user_prompt([make_hard_fail()], [], {}, {}, None, make_plan(), 45)
        assert "OPERATING_HOURS_CONFLICT" in prompt
        assert "경복궁" in prompt

    def test_warning_in_prompt(self):
        prompt = _build_user_prompt([], [make_warning()], {}, {}, None, make_plan(), 70)
        assert "DENSE_SCHEDULE" in prompt

    def test_penalty_in_prompt(self):
        prompt = _build_user_prompt([], [], {"travel_ratio": 10}, {}, None, make_plan(), 70)
        assert "travel_ratio" in prompt

    def test_scores_included_when_provided(self):
        prompt = _build_user_prompt([], [], {}, {}, make_scores(), make_plan(), 80)
        assert "효율성" in prompt or "efficiency" in prompt.lower()

    def test_overall_item_present(self):
        prompt = _build_user_prompt([], [], {}, {}, None, make_plan(), 80)
        assert "overall" in prompt
        assert "summary" in prompt


# ---------------------------------------------------------------------------
# _parse_llm_response
# ---------------------------------------------------------------------------

class TestParseLlmResponse:
    def test_parses_valid_json_array(self):
        raw = json.dumps([{
            "item_type": "hard_fail",
            "item_key": "OPERATING_HOURS_CONFLICT",
            "fact": "경복궁 도착 18:30, 운영 종료 18:00",
            "rule": "운영시간 외 방문 불가",
            "risk": "CRITICAL",
            "suggestion": "방문 순서를 앞당기세요",
        }])
        items = _parse_llm_response(raw)
        assert len(items) == 1
        assert items[0].item_type == "hard_fail"
        assert items[0].risk == "CRITICAL"

    def test_strips_code_block_wrapper(self):
        raw = "```json\n[{\"item_type\":\"overall\",\"item_key\":\"summary\",\"fact\":\"점수 80\",\"rule\":\"규칙\",\"risk\":\"OK\",\"suggestion\":\"좋음\"}]\n```"
        items = _parse_llm_response(raw)
        assert len(items) == 1
        assert items[0].risk == "OK"

    def test_multiple_items(self):
        raw = json.dumps([
            {"item_type": "hard_fail", "item_key": "HF1", "fact": "f", "rule": "r", "risk": "CRITICAL", "suggestion": "s"},
            {"item_type": "warning", "item_key": "W1", "fact": "f", "rule": "r", "risk": "WARNING", "suggestion": "s"},
        ])
        items = _parse_llm_response(raw)
        assert len(items) == 2

    def test_returns_explanation_items(self):
        raw = json.dumps([{
            "item_type": "overall", "item_key": "summary",
            "fact": "fact", "rule": "rule", "risk": "OK", "suggestion": "sug",
        }])
        items = _parse_llm_response(raw)
        assert all(isinstance(i, ExplanationItem) for i in items)


# ---------------------------------------------------------------------------
# _fallback
# ---------------------------------------------------------------------------

class TestFallback:
    def test_hard_fail_becomes_critical(self):
        items = _fallback([make_hard_fail()], [], {}, 45)
        hf_items = [i for i in items if i.item_type == "hard_fail"]
        assert all(i.risk == "CRITICAL" for i in hf_items)

    def test_warning_becomes_warning(self):
        items = _fallback([], [make_warning()], {}, 70)
        w_items = [i for i in items if i.item_type == "warning"]
        assert all(i.risk == "WARNING" for i in w_items)

    def test_large_penalty_is_critical(self):
        items = _fallback([], [], {"cluster_dispersion": 10}, 70)
        p_items = [i for i in items if i.item_type == "penalty"]
        assert p_items[0].risk == "CRITICAL"

    def test_small_penalty_is_warning(self):
        items = _fallback([], [], {"cluster_dispersion": 5}, 70)
        p_items = [i for i in items if i.item_type == "penalty"]
        assert p_items[0].risk == "WARNING"

    def test_always_has_overall_item(self):
        for scenario in [
            ([make_hard_fail()], [], {}, 45),
            ([], [make_warning()], {}, 70),
            ([], [], {}, 85),
        ]:
            items = _fallback(*scenario)
            overall = [i for i in items if i.item_type == "overall"]
            assert len(overall) == 1

    def test_failed_overall_is_critical(self):
        items = _fallback([make_hard_fail()], [], {}, 45)
        overall = next(i for i in items if i.item_type == "overall")
        assert overall.risk == "CRITICAL"

    def test_passed_overall_is_ok(self):
        items = _fallback([], [], {}, 75)
        overall = next(i for i in items if i.item_type == "overall")
        assert overall.risk == "OK"


# ---------------------------------------------------------------------------
# ExplainEngine (no LLM)
# ---------------------------------------------------------------------------

class TestExplainEngineNoLLM:
    def setup_method(self):
        # API 키 없이 인스턴스 — fallback 경로 테스트
        self.engine = ExplainEngine(api_key="", client=None)

    def test_is_available_false_without_key(self):
        assert not self.engine.is_available()

    def test_generate_returns_list_of_explanation_items(self):
        result = self.engine.generate(
            hard_fails=[make_hard_fail()],
            warnings=[make_warning()],
            penalty_breakdown={"travel_ratio": 10},
            bonus_breakdown={},
            scores=make_scores(),
            plan=make_plan(),
            final_score=45,
        )
        assert isinstance(result, list)
        assert all(isinstance(i, ExplanationItem) for i in result)

    def test_no_issues_returns_ok_overall(self):
        result = self.engine.generate(
            hard_fails=[], warnings=[], penalty_breakdown={},
            bonus_breakdown={}, scores=make_scores(), plan=make_plan(), final_score=82,
        )
        assert len(result) == 1
        assert result[0].item_type == "overall"
        assert result[0].risk == "OK"

    def test_hard_fail_present_in_results(self):
        result = self.engine.generate(
            hard_fails=[make_hard_fail()], warnings=[], penalty_breakdown={},
            bonus_breakdown={}, scores=None, plan=make_plan(), final_score=45,
        )
        hf_items = [i for i in result if i.item_type == "hard_fail"]
        assert len(hf_items) >= 1

    def test_warning_present_in_results(self):
        result = self.engine.generate(
            hard_fails=[], warnings=[make_warning()], penalty_breakdown={},
            bonus_breakdown={}, scores=None, plan=make_plan(), final_score=70,
        )
        w_items = [i for i in result if i.item_type == "warning"]
        assert len(w_items) >= 1

    def test_penalty_present_in_results(self):
        result = self.engine.generate(
            hard_fails=[], warnings=[], penalty_breakdown={"cluster_dispersion": 10},
            bonus_breakdown={}, scores=None, plan=make_plan(), final_score=70,
        )
        p_items = [i for i in result if i.item_type == "penalty"]
        assert len(p_items) >= 1


# ---------------------------------------------------------------------------
# ExplainEngine — LLM mock 경로
# ---------------------------------------------------------------------------

class TestExplainEngineMockLLM:
    def _make_mock_client(self, response_json: list[dict]):
        raw = json.dumps(response_json)
        block = MagicMock()
        block.text = raw
        resp = MagicMock()
        resp.content = [block]
        client = MagicMock()
        client.messages.create.return_value = resp
        return client

    def test_llm_response_used_when_available(self):
        llm_output = [{
            "item_type": "hard_fail",
            "item_key": "OPERATING_HOURS_CONFLICT",
            "fact": "경복궁 도착 18:30, 운영종료 18:00 — 30분 초과",
            "rule": "운영시간 외 방문 불가 (Hard Fail)",
            "risk": "CRITICAL",
            "suggestion": "방문 순서를 오전으로 앞당기세요.",
        }, {
            "item_type": "overall",
            "item_key": "summary",
            "fact": "최종 점수 45/100",
            "rule": "60점 미만은 FAIL",
            "risk": "CRITICAL",
            "suggestion": "Hard Fail 해결 후 재검증하세요.",
        }]
        engine = ExplainEngine(api_key="test-key", client=self._make_mock_client(llm_output))
        result = engine.generate(
            hard_fails=[make_hard_fail()], warnings=[], penalty_breakdown={},
            bonus_breakdown={}, scores=None, plan=make_plan(), final_score=45,
        )
        assert len(result) == 2
        assert result[0].fact == "경복궁 도착 18:30, 운영종료 18:00 — 30분 초과"

    def test_llm_failure_falls_back_gracefully(self):
        client = MagicMock()
        client.messages.create.side_effect = Exception("API timeout")
        engine = ExplainEngine(api_key="test-key", client=client)
        result = engine.generate(
            hard_fails=[make_hard_fail()], warnings=[], penalty_breakdown={},
            bonus_breakdown={}, scores=None, plan=make_plan(), final_score=45,
        )
        assert len(result) >= 1
        assert all(isinstance(i, ExplanationItem) for i in result)

    def test_cache_prevents_second_llm_call(self):
        import src.explain.explain_engine as ee
        ee._CACHE.clear()  # 모듈 단위 캐시 초기화 — 타 테스트와 격리

        llm_output = [{
            "item_type": "overall", "item_key": "summary",
            "fact": "f", "rule": "r", "risk": "CRITICAL", "suggestion": "s",
        }]
        client = self._make_mock_client(llm_output)
        engine = ExplainEngine(api_key="test-key", client=client)
        # 동일 입력으로 두 번 호출
        hf = [make_hard_fail()]
        engine.generate(hf, [], {}, {}, None, make_plan(), 45)
        engine.generate(hf, [], {}, {}, None, make_plan(), 45)
        assert client.messages.create.call_count == 1

    def test_is_available_with_client(self):
        client = MagicMock()
        engine = ExplainEngine(api_key="test-key", client=client)
        assert engine.is_available()
