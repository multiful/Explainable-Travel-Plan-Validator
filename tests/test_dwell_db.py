"""Tests for src/data/dwell_db.py — 5단계 폴백 검증."""

from __future__ import annotations

from src.data.dwell_db import (
    BY_LCLS1,
    BY_LCLS3,
    DEFAULT_DWELL,
    DwellRecommendation,
    get_recommended_dwell,
)


class TestManualOverride:
    def test_경복궁_returns_manual_source(self):
        rec = get_recommended_dwell("경복궁")
        assert rec.source == "manual"
        assert rec.min_minutes == 90
        assert rec.max_minutes == 150

    def test_normalization_handles_spaces(self):
        # "경복궁 " (trailing space) 도 매칭되어야 함
        rec = get_recommended_dwell("경복궁 ")
        assert rec.source == "manual"

    def test_n_seoul_tower_alias(self):
        rec1 = get_recommended_dwell("남산서울타워")
        rec2 = get_recommended_dwell("N서울타워")
        assert rec1.source == "manual"
        assert rec2.source == "manual"


class TestLclsSystm3:
    def test_museum_code(self):
        # 박물관 (VE0101)
        rec = get_recommended_dwell("미상의 박물관", lcls_systm3="VE0101")
        assert rec.source == "lcls3"
        assert rec.min_minutes == BY_LCLS3["VE0101"][0]


class TestLclsSystm1Fallback:
    def test_lcls3_unknown_falls_back_to_lcls1(self):
        # VE9999는 BY_LCLS3에 없음 → lcls1=VE로 폴백
        rec = get_recommended_dwell("미상의 인문관광지", lcls_systm3="VE9999")
        assert rec.source == "lcls1"
        assert rec.min_minutes == BY_LCLS1["VE"][0]


class TestContentTypeFallback:
    def test_content_type_used_when_no_lcls(self):
        rec = get_recommended_dwell("미상의 음식점", content_type_id=39)
        assert rec.source == "content_type"
        assert rec.min_minutes == 45


class TestDefaultFallback:
    def test_no_info_returns_default(self):
        rec = get_recommended_dwell("완전 미상의 장소")
        assert rec.source == "default"
        assert (rec.min_minutes, rec.max_minutes) == DEFAULT_DWELL


class TestIsTooShort:
    def test_below_50pct_is_too_short(self):
        rec = DwellRecommendation(min_minutes=90, max_minutes=150, source="manual")
        assert rec.is_too_short(30) is True  # 30 < 90*0.5=45
        assert rec.is_too_short(60) is False  # 60 >= 45
