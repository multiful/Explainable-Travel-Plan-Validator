"""PartyProfile 수량화 로직 테스트."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from src.data.party_config import PARTY_PROFILES, get_party_profile


class TestPartyProfiles:
    def test_all_types_defined(self):
        for pt in ("혼자", "친구", "연인", "가족", "아기동반", "어르신동반"):
            assert pt in PARTY_PROFILES

    def test_friends_speed_factor_one(self):
        assert get_party_profile("친구").speed_factor == 1.0

    def test_baby_speed_factor_below_one(self):
        assert get_party_profile("아기동반").speed_factor < 1.0

    def test_elderly_speed_factor_below_one(self):
        assert get_party_profile("어르신동반").speed_factor < 1.0

    def test_baby_fatigue_hours_lower_than_friends(self):
        baby = get_party_profile("아기동반")
        friends = get_party_profile("친구")
        assert baby.fatigue_hours < friends.fatigue_hours

    def test_elderly_fatigue_hours_lower_than_friends(self):
        elderly = get_party_profile("어르신동반")
        friends = get_party_profile("친구")
        assert elderly.fatigue_hours < friends.fatigue_hours

    def test_family_fatigue_between_friends_and_baby(self):
        family = get_party_profile("가족")
        friends = get_party_profile("친구")
        baby = get_party_profile("아기동반")
        assert baby.fatigue_hours <= family.fatigue_hours <= friends.fatigue_hours

    def test_unknown_type_returns_default(self):
        profile = get_party_profile("알수없음")
        default = get_party_profile("친구")
        assert profile == default

    def test_profile_is_frozen(self):
        profile = get_party_profile("친구")
        with pytest.raises(FrozenInstanceError):
            profile.speed_factor = 2.0  # type: ignore[misc]


class TestPartyProfileValues:
    def test_friends_fatigue_12h(self):
        assert get_party_profile("친구").fatigue_hours == 12

    def test_baby_fatigue_8h(self):
        assert get_party_profile("아기동반").fatigue_hours == 8

    def test_elderly_fatigue_8h(self):
        assert get_party_profile("어르신동반").fatigue_hours == 8

    def test_family_fatigue_10h(self):
        assert get_party_profile("가족").fatigue_hours == 10

    def test_baby_speed_factor_is_point_eight(self):
        assert get_party_profile("아기동반").speed_factor == pytest.approx(0.8)

    def test_family_speed_factor_is_point_nine(self):
        assert get_party_profile("가족").speed_factor == pytest.approx(0.9)


class TestStrainThresholdLogic:
    """speed_factor가 체력 부담 임계에 올바르게 반영되는지 확인."""

    BASE_KM = 30.0

    def test_baby_threshold_lower_than_friends(self):
        baby_threshold = self.BASE_KM * get_party_profile("아기동반").speed_factor
        friends_threshold = self.BASE_KM * get_party_profile("친구").speed_factor
        assert baby_threshold < friends_threshold

    def test_baby_threshold_is_24km(self):
        threshold = self.BASE_KM * get_party_profile("아기동반").speed_factor
        assert threshold == pytest.approx(24.0)

    def test_friends_threshold_unchanged(self):
        threshold = self.BASE_KM * get_party_profile("친구").speed_factor
        assert threshold == pytest.approx(30.0)
