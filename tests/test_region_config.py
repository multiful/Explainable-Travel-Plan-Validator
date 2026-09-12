"""RegionThresholds 유닛 테스트."""

from __future__ import annotations

from src.data.region_config import (
    TIER_HIGH_DENSITY,
    TIER_LOW_DENSITY,
    TIER_MEDIUM_DENSITY,
    get_thresholds,
)


class TestGetThresholds:
    def test_seoul_code_returns_high(self):
        assert get_thresholds("11110").tier == "high"

    def test_busan_code_returns_high(self):
        assert get_thresholds("26110").tier == "high"

    def test_daegu_code_returns_medium(self):
        assert get_thresholds("27110").tier == "medium"

    def test_rural_code_returns_low(self):
        assert get_thresholds("48000").tier == "low"

    def test_none_returns_medium(self):
        assert get_thresholds(None).tier == "medium"

    def test_unknown_code_returns_low(self):
        assert get_thresholds("99999").tier == "low"

    def test_high_dist_warn_smaller_than_low(self):
        assert TIER_HIGH_DENSITY.dist_warn_km < TIER_LOW_DENSITY.dist_warn_km

    def test_high_physical_strain_smaller_than_low(self):
        assert TIER_HIGH_DENSITY.physical_strain_km < TIER_LOW_DENSITY.physical_strain_km

    def test_tier_fields_ordered(self):
        assert (
            TIER_HIGH_DENSITY.dense_schedule_min
            < TIER_MEDIUM_DENSITY.dense_schedule_min
            < TIER_LOW_DENSITY.dense_schedule_min
        )
