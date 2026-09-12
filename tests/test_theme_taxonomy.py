"""Tests for src/data/theme_taxonomy.py — 2축 테마 + 매핑."""

from __future__ import annotations

import pytest

from src.data.theme_taxonomy import (
    PLACE_TYPES,
    TRAVEL_STYLES,
    UserPreferences,
    get_place_types_for,
    matches_place_type,
)


class TestPlaceTypeCount:
    def test_9_place_types(self):
        assert len(PLACE_TYPES) == 9
        assert "산" in PLACE_TYPES
        assert "축제" in PLACE_TYPES

    def test_9_travel_styles(self):
        assert len(TRAVEL_STYLES) == 9
        assert "여유롭게 힐링" in TRAVEL_STYLES
        assert "관광보다 먹방" in TRAVEL_STYLES


class TestUserPreferences:
    def test_valid_input(self):
        p = UserPreferences(place_types=["산"], travel_styles=["자연과 함께"])
        assert p.place_types == ["산"]
        assert p.all_themes() == ["산", "자연과 함께"]

    def test_invalid_place_type_raises(self):
        with pytest.raises(ValueError, match="정의되지 않은 PLACE_TYPE"):
            UserPreferences(place_types=["우주여행"], travel_styles=[])

    def test_invalid_style_raises(self):
        with pytest.raises(ValueError, match="정의되지 않은 TRAVEL_STYLE"):
            UserPreferences(place_types=[], travel_styles=["가즈아"])

    def test_empty_both_axes_raises(self):
        with pytest.raises(ValueError, match="최소 하나의"):
            UserPreferences()


class TestMatchesPlaceType:
    def test_mountain_matches_NA04(self):
        # NA04 = 산
        assert matches_place_type("산", lcls_systm3="NA0401") is True

    def test_beach_matches_NA12(self):
        assert matches_place_type("바다", lcls_systm3="NA1201") is True

    def test_festival_matches_content_type_15(self):
        assert matches_place_type("축제", content_type_id=15) is True

    def test_no_match(self):
        # NA04(산) 코드를 "카페"로 매칭하면 False
        assert matches_place_type("카페", lcls_systm3="NA0401") is False


class TestGetPlaceTypesFor:
    def test_mountain_code_returns_list(self):
        types = get_place_types_for(lcls_systm3="NA0401")
        assert "산" in types

    def test_no_code_returns_empty(self):
        types = get_place_types_for()
        assert types == []
