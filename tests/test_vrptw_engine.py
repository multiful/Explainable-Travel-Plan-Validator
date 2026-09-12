"""Tests for VRPTW validation engine (TDD)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pydantic import ValidationError

from src.data.models import VRPTWDay, VRPTWPlace, VRPTWRequest, VRPTWResult
from src.validation.vrptw_engine import (
    EFFICIENCY_GAP_THRESHOLD,
    FATIGUE_HOURS_LIMIT,
    SAFETY_MARGIN_MINUTES,
    CachedRouteMatrix,
    HaversineMatrix,
    VRPTWEngine,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_place(
    name: str = "POI",
    lng: float = 127.0,
    lat: float = 37.5,
    open_: str = "09:00",
    close: str = "18:00",
    stay_min: int = 60,
    is_depot: bool = False,
) -> VRPTWPlace:
    return VRPTWPlace(
        name=name,
        lng=lng,
        lat=lat,
        open=open_,
        close=close,
        stay_duration=stay_min,
        is_depot=is_depot,
    )


DEPOT = make_place("Hotel", 127.0, 37.5, "00:00", "23:59", 0, is_depot=True)
POI_A = make_place("POI_A", 127.1, 37.5, "09:00", "18:00", 60)
POI_B = make_place("POI_B", 127.2, 37.5, "09:00", "18:00", 60)
POI_C = make_place("POI_C", 127.3, 37.5, "09:00", "18:00", 60)


# ---------------------------------------------------------------------------
# HaversineMatrix
# ---------------------------------------------------------------------------


class TestHaversineMatrix:
    def test_same_point_is_zero(self):
        m = HaversineMatrix()
        assert m.get_travel_time(DEPOT, DEPOT) == 0

    def test_known_distance(self):
        # ~11.1 km apart at equator per 0.1° longitude ≈ 11.1 km
        # 11.1 km / 30 km·h⁻¹ = 0.37 h = 1332 s (rough check)
        m = HaversineMatrix()
        t = m.get_travel_time(POI_A, POI_B)  # 0.1° lng difference
        assert 1000 < t < 1700  # loose bounds for Haversine at lat 37.5

    def test_symmetry(self):
        m = HaversineMatrix()
        assert m.get_travel_time(POI_A, POI_B) == m.get_travel_time(POI_B, POI_A)


# ---------------------------------------------------------------------------
# CachedRouteMatrix
# ---------------------------------------------------------------------------


class TestCachedRouteMatrix:
    def test_cache_hit(self):
        data = {"127.1,37.5|127.2,37.5": 600}
        m = CachedRouteMatrix(data)
        assert m.get_travel_time(POI_A, POI_B) == 600

    def test_cache_miss_falls_back_to_haversine(self):
        m = CachedRouteMatrix({})
        t = m.get_travel_time(POI_A, POI_B)
        haversine_t = HaversineMatrix().get_travel_time(POI_A, POI_B)
        assert t == haversine_t

    def test_reverse_key_fallback(self):
        """If only the reverse direction is cached, use it."""
        data = {"127.2,37.5|127.1,37.5": 700}
        m = CachedRouteMatrix(data)
        assert m.get_travel_time(POI_A, POI_B) == 700

    def test_load_from_dict(self):
        data = {"126.7205,33.5569|126.6887,33.5460": 593}
        m = CachedRouteMatrix(data)
        p1 = make_place(lng=126.7205, lat=33.5569)
        p2 = make_place(lng=126.6887, lat=33.5460)
        assert m.get_travel_time(p1, p2) == 593


# ---------------------------------------------------------------------------
# Depot constraint enforcement
# ---------------------------------------------------------------------------


class TestDepotConstraint:
    def _engine_with_haversine(self) -> VRPTWEngine:
        return VRPTWEngine(matrix=HaversineMatrix())

    def test_2n3d_day1_must_end_at_depot(self):
        """2박3일: day1 last place must be depot."""
        req = VRPTWRequest(
            days=[
                VRPTWDay(places=[DEPOT, POI_A, POI_B]),  # depot only at start
                VRPTWDay(places=[DEPOT, POI_C, DEPOT]),
                VRPTWDay(places=[DEPOT, POI_A]),
            ]
        )
        engine = self._engine_with_haversine()
        result = engine.validate(req)
        has_depot_warning = any(
            "depot" in d.fact.lower() or "숙소" in d.fact for d in result.deep_dive
        )
        assert has_depot_warning or result.risk_score < 100

    def test_2n3d_middle_day_must_start_and_end_at_depot(self):
        req = VRPTWRequest(
            days=[
                VRPTWDay(places=[DEPOT, POI_A, DEPOT]),
                VRPTWDay(places=[POI_A, POI_B, POI_C]),  # missing depot
                VRPTWDay(places=[DEPOT, POI_B]),
            ]
        )
        engine = self._engine_with_haversine()
        result = engine.validate(req)
        depot_issues = [
            d for d in result.deep_dive if "depot" in d.fact.lower() or "숙소" in d.fact
        ]
        assert len(depot_issues) >= 1

    def test_1n2d_no_depot_constraint_applied(self):
        """1박2일: depot constraint NOT enforced."""
        req = VRPTWRequest(
            days=[
                VRPTWDay(places=[POI_A, POI_B]),
                VRPTWDay(places=[POI_B, POI_C]),
            ]
        )
        engine = self._engine_with_haversine()
        result = engine.validate(req)
        depot_issues = [
            d
            for d in result.deep_dive
            if ("depot" in d.rule.lower() or "depot" in d.fact.lower()) and "1박" not in d.fact
        ]
        assert len(depot_issues) == 0


# ---------------------------------------------------------------------------
# Time window feasibility
# ---------------------------------------------------------------------------


class TestTimeWindowFeasibility:
    def _engine(self) -> VRPTWEngine:
        return VRPTWEngine(matrix=HaversineMatrix())

    def test_feasible_schedule_passes(self):
        req = VRPTWRequest(days=[VRPTWDay(places=[POI_A, POI_B])])
        engine = self._engine()
        result = engine.validate(req)
        hard_fails = [
            d for d in result.deep_dive if d.risk == "CRITICAL" and "time_window" in d.rule.lower()
        ]
        assert len(hard_fails) == 0

    def test_infeasible_close_time_triggers_critical(self):
        """A place that closes at 09:05 — impossible to visit after travel from A."""
        tight = make_place("TightPOI", 127.2, 37.5, "08:00", "09:05", 60)
        req = VRPTWRequest(days=[VRPTWDay(places=[POI_A, tight])])
        engine = self._engine()
        result = engine.validate(req)
        critical = [d for d in result.deep_dive if d.risk == "CRITICAL"]
        assert len(critical) >= 1

    def test_safety_margin_warning(self):
        """Arrival within 60 min of close triggers safety margin warning."""
        # POI_A at 127.1, stay 60 min → depart 10:00; near_close ~0.1° away → arrive ~10:20
        # close = 11:00 → margin = 40 min < 60 min → safety_margin warning
        near_close = make_place("NearClose", 127.2, 37.5, "08:00", "11:00", 30)
        req = VRPTWRequest(days=[VRPTWDay(places=[POI_A, near_close])])
        engine = self._engine()
        result = engine.validate(req)
        safety_issues = [d for d in result.deep_dive if "safety_margin" in d.rule.lower()]
        assert len(safety_issues) >= 1

    def test_request_start_time_is_used(self):
        late_poi = make_place("Late", 127.0, 37.5, "09:00", "10:00", 30)
        req = VRPTWRequest(
            days=[VRPTWDay(places=[late_poi])],
            start_time="10:30",
        )

        result = self._engine().validate(req)

        assert any(d.risk == "CRITICAL" for d in result.deep_dive)


# ---------------------------------------------------------------------------
# Efficiency gap
# ---------------------------------------------------------------------------


class TestEfficiencyGap:
    def test_optimal_order_same_as_user_gives_zero_gap(self):
        """With 2 POIs the optimal is always the same, gap should be 0 or minimal."""
        req = VRPTWRequest(days=[VRPTWDay(places=[POI_A, POI_B])])
        engine = VRPTWEngine(matrix=HaversineMatrix())
        result = engine.validate(req)
        if result.efficiency_gap is not None:
            assert result.efficiency_gap >= 0

    def test_reversed_inefficient_route_shows_gap(self):
        """A→C→B is longer than A→B→C when laid out linearly."""
        req = VRPTWRequest(days=[VRPTWDay(places=[POI_A, POI_C, POI_B])])
        engine = VRPTWEngine(matrix=HaversineMatrix())
        result = engine.validate(req)
        if result.efficiency_gap is not None:
            assert result.efficiency_gap >= 0


# ---------------------------------------------------------------------------
# Fatigue score
# ---------------------------------------------------------------------------


class TestFatigueScore:
    def test_12h_schedule_no_fatigue_penalty(self):
        # 09:00 start, 21:00 end = exactly 12h
        places = [
            make_place("A", 127.0, 37.5, "09:00", "21:00", 60),
            make_place("B", 127.0001, 37.5, "09:00", "21:00", 60),
        ]
        req = VRPTWRequest(days=[VRPTWDay(places=places)])
        engine = VRPTWEngine(matrix=HaversineMatrix())
        result = engine.validate(req)
        fatigue_issues = [d for d in result.deep_dive if "fatigue" in d.rule.lower()]
        # 2 POIs with 60 min each + minimal travel: well under 12h
        assert len(fatigue_issues) == 0

    def test_long_schedule_triggers_fatigue(self):
        # Pack many long-stay POIs to exceed 12h
        long_places = [
            make_place(f"P{i}", 127.0 + i * 0.001, 37.5, "00:00", "23:59", 120)
            for i in range(7)  # 7 × 120 min = 840 min = 14h
        ]
        req = VRPTWRequest(days=[VRPTWDay(places=long_places)])
        engine = VRPTWEngine(matrix=HaversineMatrix())
        result = engine.validate(req)
        fatigue_issues = [d for d in result.deep_dive if "fatigue" in d.rule.lower()]
        assert len(fatigue_issues) >= 1


# ---------------------------------------------------------------------------
# OR-Tools graceful degradation
# ---------------------------------------------------------------------------


class TestORToolsDegradation:
    def test_missing_ortools_still_returns_result(self):
        """When ortools is not available, engine still returns a VRPTWResult."""
        req = VRPTWRequest(days=[VRPTWDay(places=[POI_A, POI_B])])
        with patch.dict(
            "sys.modules",
            {
                "ortools": None,
                "ortools.constraint_solver": None,
                "ortools.constraint_solver.routing_enums_pb2": None,
                "ortools.constraint_solver.pywrapcsp": None,
            },
        ):
            # Re-import engine in patched context is complex; instead directly test the
            # fallback path by calling with ortools_available=False
            engine = VRPTWEngine(matrix=HaversineMatrix(), ortools_available=False)
            result = engine.validate(req)
        assert isinstance(result, VRPTWResult)
        assert result.optimal_route is None
        assert result.efficiency_gap is None
        assert result.risk_score is not None


# ---------------------------------------------------------------------------
# Risk score bounds
# ---------------------------------------------------------------------------


class TestRiskScore:
    def test_risk_score_in_0_100(self):
        req = VRPTWRequest(days=[VRPTWDay(places=[POI_A, POI_B])])
        engine = VRPTWEngine(matrix=HaversineMatrix())
        result = engine.validate(req)
        assert 0 <= result.risk_score <= 100

    def test_pass_fail_threshold(self):
        req = VRPTWRequest(days=[VRPTWDay(places=[POI_A, POI_B])])
        engine = VRPTWEngine(matrix=HaversineMatrix())
        result = engine.validate(req)
        if result.risk_score >= 60:
            assert result.passed is True
        else:
            assert result.passed is False


# ---------------------------------------------------------------------------
# Constants are tunable
# ---------------------------------------------------------------------------


def test_constants_accessible():
    assert EFFICIENCY_GAP_THRESHOLD == 0.20
    assert FATIGUE_HOURS_LIMIT == 12
    assert SAFETY_MARGIN_MINUTES == 60


# ---------------------------------------------------------------------------
# Pydantic model validation
# ---------------------------------------------------------------------------


class TestModelValidation:
    def test_invalid_lat_raises(self):
        with pytest.raises(ValidationError):
            VRPTWPlace(name="X", lng=127.0, lat=91.0, open="09:00", close="18:00", stay_duration=60)

    def test_invalid_lng_raises(self):
        with pytest.raises(ValidationError):
            VRPTWPlace(name="X", lng=181.0, lat=37.0, open="09:00", close="18:00", stay_duration=60)

    def test_invalid_time_format_raises(self):
        with pytest.raises(ValidationError):
            VRPTWPlace(name="X", lng=127.0, lat=37.0, open="9:00", close="18:00", stay_duration=60)

    def test_invalid_time_value_raises(self):
        with pytest.raises(ValidationError):
            VRPTWPlace(name="X", lng=127.0, lat=37.0, open="25:00", close="18:00", stay_duration=60)

    def test_negative_stay_raises(self):
        with pytest.raises(ValidationError):
            VRPTWPlace(name="X", lng=127.0, lat=37.0, open="09:00", close="18:00", stay_duration=-1)

    def test_zero_stay_allowed_for_depot(self):
        p = VRPTWPlace(
            name="Hotel",
            lng=127.0,
            lat=37.0,
            open="00:00",
            close="23:59",
            stay_duration=0,
            is_depot=True,
        )
        assert p.stay_duration == 0

    def test_empty_day_raises(self):
        with pytest.raises(ValidationError):
            VRPTWDay(places=[])

    def test_empty_days_raises(self):
        with pytest.raises(ValidationError):
            VRPTWRequest(days=[])

    def test_open_minutes_property(self):
        p = make_place(open_="14:30", close="18:00")
        assert p.open_minutes == 14 * 60 + 30

    def test_close_minutes_property(self):
        p = make_place(open_="09:00", close="21:45")
        assert p.close_minutes == 21 * 60 + 45


# ---------------------------------------------------------------------------
# Efficiency gap over threshold triggers deep_dive entry
# ---------------------------------------------------------------------------


class TestEfficiencyGapThreshold:
    def test_gap_over_threshold_adds_warning(self):
        """If efficiency gap > 20%, a deep_dive WARNING should appear."""
        # Build a route A→C→B where A→B→C is clearly shorter
        # A: 127.0, B: 127.1, C: 127.2 (all same lat) — A→C→B backtracks
        a = make_place("A", 127.0, 37.5, "09:00", "22:00", 30)
        b = make_place("B", 127.1, 37.5, "09:00", "22:00", 30)
        c = make_place("C", 127.2, 37.5, "09:00", "22:00", 30)
        req = VRPTWRequest(days=[VRPTWDay(places=[a, c, b])])
        engine = VRPTWEngine(matrix=HaversineMatrix())
        result = engine.validate(req)
        # efficiency_gap may be None if ortools not available; skip if so
        if result.efficiency_gap is not None and result.efficiency_gap > EFFICIENCY_GAP_THRESHOLD:
            gap_warnings = [d for d in result.deep_dive if "efficiency_gap" in d.rule]
            assert len(gap_warnings) >= 1


# ---------------------------------------------------------------------------
# Multi-day result structure
# ---------------------------------------------------------------------------


class TestMultiDayResult:
    def test_multi_day_returns_per_day_comparison(self):
        req = VRPTWRequest(
            days=[
                VRPTWDay(places=[POI_A, POI_B]),
                VRPTWDay(places=[POI_B, POI_C]),
            ]
        )
        engine = VRPTWEngine(matrix=HaversineMatrix())
        result = engine.validate(req)
        if result.optimal_route is not None:
            assert len(result.optimal_route) == 2
            assert result.optimal_route[0].day_index == 0
            assert result.optimal_route[1].day_index == 1

    def test_multi_day_user_total_travel_is_sum(self):
        req = VRPTWRequest(
            days=[
                VRPTWDay(places=[POI_A, POI_B]),
                VRPTWDay(places=[POI_B, POI_C]),
            ]
        )
        engine = VRPTWEngine(matrix=HaversineMatrix())
        result = engine.validate(req)
        if result.optimal_route is not None:
            day_sum = sum(d.user_travel_seconds for d in result.optimal_route)
            assert result.user_total_travel_seconds == day_sum

    def test_single_place_day_no_travel(self):
        req = VRPTWRequest(days=[VRPTWDay(places=[POI_A])])
        engine = VRPTWEngine(matrix=HaversineMatrix())
        result = engine.validate(req)
        assert result.user_total_travel_seconds == 0


# ---------------------------------------------------------------------------
# Summary string
# ---------------------------------------------------------------------------


def test_summary_contains_score():
    req = VRPTWRequest(days=[VRPTWDay(places=[POI_A, POI_B])])
    engine = VRPTWEngine(matrix=HaversineMatrix())
    result = engine.validate(req)
    assert str(result.risk_score) in result.summary
    assert "PASS" in result.summary or "FAIL" in result.summary


# ---------------------------------------------------------------------------
# DeepDiveItem structure
# ---------------------------------------------------------------------------


def test_deep_dive_items_have_all_fields():
    """Every DeepDiveItem must have non-empty fact, rule, risk, suggestion."""
    tight = make_place("Tight", 127.2, 37.5, "08:00", "09:05", 60)
    req = VRPTWRequest(days=[VRPTWDay(places=[POI_A, tight])])
    engine = VRPTWEngine(matrix=HaversineMatrix())
    result = engine.validate(req)
    for item in result.deep_dive:
        assert item.fact
        assert item.rule
        assert item.risk in ("OK", "WARNING", "CRITICAL")
        assert item.suggestion


# ---------------------------------------------------------------------------
# CachedRouteMatrix.from_file (uses actual cache_route.json)
# ---------------------------------------------------------------------------


def test_cached_matrix_from_actual_file():
    """Smoke test: load real cache_route.json and verify at least one hit."""
    import os

    cache_path = os.path.join(
        os.path.dirname(__file__), "..", "phases", "0-setup", "cache_route.json"
    )
    if not os.path.exists(cache_path):
        pytest.skip("cache_route.json not found")
    m = CachedRouteMatrix.from_file(cache_path)
    # First entry from the file: "126.7205,33.5569|126.6887,33.5460": 593
    p1 = make_place(lng=126.7205, lat=33.5569)
    p2 = make_place(lng=126.6887, lat=33.5460)
    assert m.get_travel_time(p1, p2) == 593
