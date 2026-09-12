"""Tests for src/scoring/theme_alignment.py — LLM mocking 필수."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.data.theme_taxonomy import UserPreferences
from src.scoring.theme_alignment import (
    _CACHE,
    PENALTY_CRIT,
    POIWithCategory,
    ThemeAlignmentJudge,
    _classify_score,
    _parse_llm_response,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    """각 테스트 전 캐시 비우기."""
    _CACHE.clear()
    yield
    _CACHE.clear()


class TestNoApiKey:
    def test_skip_returns_informational_only(self):
        """API 키 없으면 LLM 호출 스킵 + 정보성 DeepDive."""
        judge = ThemeAlignmentJudge(api_key="")  # 명시적 빈 키
        prefs = UserPreferences(place_types=["산"], travel_styles=[])
        report = judge.evaluate(prefs, [POIWithCategory(name="한라산", visit_order=1)])
        assert report.judgment is None
        assert report.penalty == 0
        assert len(report.deep_dive) == 1
        assert report.deep_dive[0].risk == "OK"


class TestClassifyScore:
    def test_high_score_no_penalty(self):
        pen, risk = _classify_score(0.9)
        assert pen == 0
        assert risk == "OK"

    def test_low_score_critical(self):
        pen, risk = _classify_score(0.3)
        assert pen == PENALTY_CRIT
        assert risk == "CRITICAL"


class TestParseLlmResponse:
    def test_clean_json(self):
        raw = '{"score": 0.75, "reasoning": "테스트", "mismatched_places": ["A"]}'
        j = _parse_llm_response(raw)
        assert j.score == 0.75
        assert j.reasoning == "테스트"
        assert j.mismatched_places == ["A"]

    def test_score_clamped_to_1(self):
        raw = '{"score": 1.5, "reasoning": "x", "mismatched_places": []}'
        j = _parse_llm_response(raw)
        assert j.score == 1.0

    def test_code_block_stripped(self):
        raw = '```json\n{"score": 0.5, "reasoning": "x", "mismatched_places": []}\n```'
        j = _parse_llm_response(raw)
        assert j.score == 0.5


class TestEvaluateWithMockClient:
    def test_high_alignment_no_penalty(self):
        """LLM이 0.9 응답 → 패널티 0."""
        mock_client = MagicMock()
        mock_msg = MagicMock()
        mock_msg.content = [
            MagicMock(text='{"score": 0.9, "reasoning": "잘 맞음", "mismatched_places": []}')
        ]
        mock_client.messages.create.return_value = mock_msg

        judge = ThemeAlignmentJudge(api_key="dummy", client=mock_client)
        prefs = UserPreferences(place_types=["산"], travel_styles=["자연과 함께"])
        report = judge.evaluate(
            prefs,
            [
                POIWithCategory(name="한라산", category_name="자연관광지/산", visit_order=1),
            ],
        )

        assert report.judgment is not None
        assert report.judgment.score == 0.9
        assert report.penalty == 0

    def test_low_alignment_critical(self):
        """LLM이 0.3 응답 → CRITICAL 패널티."""
        mock_client = MagicMock()
        mock_msg = MagicMock()
        mock_msg.content = [
            MagicMock(text='{"score": 0.3, "reasoning": "안 맞음", "mismatched_places": ["카페A"]}')
        ]
        mock_client.messages.create.return_value = mock_msg

        judge = ThemeAlignmentJudge(api_key="dummy", client=mock_client)
        prefs = UserPreferences(place_types=["액티비티"], travel_styles=[])
        report = judge.evaluate(
            prefs,
            [
                POIWithCategory(name="카페A", category_name="음식점/카페", visit_order=1),
            ],
        )

        assert report.penalty == PENALTY_CRIT
        assert any(d.rule == "theme_alignment" for d in report.deep_dive)

    def test_cache_hit_skips_second_call(self):
        """동일 입력으로 두 번 호출 시 LLM은 1회만 호출."""
        mock_client = MagicMock()
        mock_msg = MagicMock()
        mock_msg.content = [
            MagicMock(text='{"score": 0.7, "reasoning": "x", "mismatched_places": []}')
        ]
        mock_client.messages.create.return_value = mock_msg

        judge = ThemeAlignmentJudge(api_key="dummy", client=mock_client)
        prefs = UserPreferences(place_types=["산"], travel_styles=[])
        places = [POIWithCategory(name="한라산", visit_order=1)]

        judge.evaluate(prefs, places)
        judge.evaluate(prefs, places)
        assert mock_client.messages.create.call_count == 1

    def test_llm_failure_returns_informational(self):
        """LLM 호출이 예외 던지면 정보성 DeepDive로 폴백."""
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = RuntimeError("network failure")

        judge = ThemeAlignmentJudge(api_key="dummy", client=mock_client)
        prefs = UserPreferences(place_types=["산"], travel_styles=[])
        report = judge.evaluate(prefs, [POIWithCategory(name="한라산", visit_order=1)])

        assert report.judgment is None
        assert report.penalty == 0
        assert any(d.rule == "theme_alignment_error" for d in report.deep_dive)
