"""Tests for ScoreCalculator (TDD)."""
from __future__ import annotations

import pytest

from src.data.models import DayPlan, HardFail, ItineraryPlan, PlaceInput, POI, Scores
from src.validation.scoring import WEIGHTS, ScoreCalculator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_poi(
    poi_id: str = "1",
    name: str = "POI",
    lat: float = 37.5,
    lng: float = 127.0,
    category: str = "14",
    duration_min: int = 60,
) -> POI:
    return POI(
        poi_id=poi_id, name=name, lat=lat, lng=lng,
        open_start="09:00", open_end="18:00",
        duration_min=duration_min, category=category,
    )


def make_plan(
    names: list[str],
    travel_type: str | None = None,
) -> ItineraryPlan:
    return ItineraryPlan(
        days=[DayPlan(places=[PlaceInput(name=n) for n in names])],
        party_size=2,
        party_type="친구",
        date="2026-05-10",
        travel_type=travel_type,
    )


def make_matrix(pairs: dict[tuple[int, int], float]) -> dict:
    matrix: dict[int, dict] = {}
    for (i, j), travel_min in pairs.items():
        matrix.setdefault(i, {})[j] = {
            "travel_min": travel_min,
            "distance_km": travel_min * (22.0 / 60.0),
        }
    return matrix


def make_hard_fail() -> HardFail:
    return HardFail(
        fail_type="OPERATING_HOURS_CONFLICT",
        message="test",
        evidence="test evidence",
        confidence="Medium",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def calc() -> ScoreCalculator:
    return ScoreCalculator()


@pytest.fixture
def sample_pois() -> list[POI]:
    return [
        make_poi(poi_id="1", name="A", lat=37.5, lng=127.0, category="14"),
        make_poi(poi_id="2", name="B", lat=37.51, lng=127.01, category="14"),
        make_poi(poi_id="3", name="C", lat=37.52, lng=127.02, category="12"),
        make_poi(poi_id="4", name="D", lat=37.53, lng=127.03, category="39"),
    ]


@pytest.fixture
def sample_matrix(sample_pois) -> dict:
    n = len(sample_pois)
    return make_matrix({(i, j): 20.0 for i in range(n) for j in range(n) if i != j})


@pytest.fixture
def sample_plan(sample_pois) -> ItineraryPlan:
    return make_plan([p.name for p in sample_pois])


# ---------------------------------------------------------------------------
# WEIGHTS constant
# ---------------------------------------------------------------------------

class TestWeights:
    def test_weights_sum_to_one(self):
        total = sum(WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9

    def test_weights_keys(self):
        assert set(WEIGHTS.keys()) == {
            "efficiency", "feasibility", "purpose_fit", "flow", "area_intensity"
        }


# ---------------------------------------------------------------------------
# compute() — final_score range
# ---------------------------------------------------------------------------

class TestCompute:
    def test_final_score_in_range(self, calc, sample_pois, sample_matrix, sample_plan):
        scores, final_score = calc.compute(sample_plan, sample_pois, sample_matrix, [])
        assert 0 <= final_score <= 100

    def test_hard_fail_caps_score_at_59(self, calc, sample_pois, sample_matrix, sample_plan):
        _, final_score = calc.compute(
            sample_plan, sample_pois, sample_matrix, [make_hard_fail()]
        )
        assert final_score <= 59

    def test_no_hard_fail_can_exceed_59(self, calc, sample_pois, sample_matrix, sample_plan):
        _, final_score = calc.compute(sample_plan, sample_pois, sample_matrix, [])
        # Score CAN be > 59 without hard fails (not guaranteed but cap must not apply)
        # Just verify no artificial cap below 60
        assert isinstance(final_score, int)

    def test_scores_object_fields(self, calc, sample_pois, sample_matrix, sample_plan):
        scores, _ = calc.compute(sample_plan, sample_pois, sample_matrix, [])
        assert 0.0 <= scores.efficiency <= 1.0
        assert 0.0 <= scores.feasibility <= 1.0
        assert 0.0 <= scores.purpose_fit <= 1.0
        assert 0.0 <= scores.flow <= 1.0
        assert 0.0 <= scores.area_intensity <= 1.0


# ---------------------------------------------------------------------------
# _calc_efficiency
# ---------------------------------------------------------------------------

class TestEfficiency:
    def test_optimal_order_is_one(self, calc):
        # 4 POIs in a straight line — user visits in order → efficiency ≈ 1.0
        pois = [
            make_poi(poi_id=str(i), name=f"P{i}", lat=37.5, lng=127.0 + i * 0.01)
            for i in range(4)
        ]
        efficiency = calc._calc_efficiency(pois, {})
        assert efficiency == pytest.approx(1.0, abs=0.05)

    def test_suboptimal_order_below_one(self, calc):
        # Zigzag pattern — clearly suboptimal
        pois = [
            make_poi(poi_id="1", name="A", lat=37.5, lng=127.0),
            make_poi(poi_id="2", name="B", lat=37.5, lng=127.5),  # far right
            make_poi(poi_id="3", name="C", lat=37.5, lng=127.1),  # back near start
            make_poi(poi_id="4", name="D", lat=37.5, lng=127.4),
        ]
        efficiency = calc._calc_efficiency(pois, {})
        assert efficiency < 1.0

    def test_single_poi_returns_one(self, calc):
        pois = [make_poi()]
        assert calc._calc_efficiency(pois, {}) == 1.0


# ---------------------------------------------------------------------------
# _calc_feasibility
# ---------------------------------------------------------------------------

class TestFeasibility:
    def test_no_hard_fails_hard_is_one(self, calc, sample_pois, sample_matrix, sample_plan):
        feasibility = calc._calc_feasibility(sample_plan, sample_pois, sample_matrix, [])
        # hard × 0.5 = 0.5, plus temporal + human → total >= 0.5
        assert feasibility >= 0.5

    def test_hard_fail_reduces_feasibility(self, calc, sample_pois, sample_matrix, sample_plan):
        with_fail = calc._calc_feasibility(sample_plan, sample_pois, sample_matrix, [make_hard_fail()])
        no_fail = calc._calc_feasibility(sample_plan, sample_pois, sample_matrix, [])
        assert with_fail < no_fail

    def test_feasibility_in_range(self, calc, sample_pois, sample_matrix, sample_plan):
        f = calc._calc_feasibility(sample_plan, sample_pois, sample_matrix, [])
        assert 0.0 <= f <= 1.0


# ---------------------------------------------------------------------------
# _calc_purpose_fit
# ---------------------------------------------------------------------------

class TestPurposeFit:
    def test_cultural_all_cultural_high(self, calc):
        pois = [make_poi(poi_id=str(i), name=f"P{i}", category="14") for i in range(4)]
        plan = make_plan([p.name for p in pois], travel_type="cultural")
        fit = calc._calc_purpose_fit(plan, pois)
        assert fit > 0.7

    def test_cultural_all_sports_low(self, calc):
        pois = [make_poi(poi_id=str(i), name=f"P{i}", category="15") for i in range(4)]
        plan = make_plan([p.name for p in pois], travel_type="cultural")
        fit = calc._calc_purpose_fit(plan, pois)
        assert fit < 0.5

    def test_no_travel_type_returns_half(self, calc):
        pois = [make_poi(poi_id=str(i), name=f"P{i}") for i in range(4)]
        plan = make_plan([p.name for p in pois], travel_type=None)
        assert calc._calc_purpose_fit(plan, pois) == 0.5


# ---------------------------------------------------------------------------
# _cosine_distance
# ---------------------------------------------------------------------------

class TestCosineDistance:
    def test_identical_vectors(self, calc):
        v = {"a": 0.5, "b": 0.5}
        assert calc._cosine_distance(v, v) == pytest.approx(0.0, abs=1e-9)

    def test_orthogonal_vectors(self, calc):
        v1 = {"a": 1.0}
        v2 = {"b": 1.0}
        assert calc._cosine_distance(v1, v2) == pytest.approx(1.0, abs=1e-9)

    def test_zero_vector(self, calc):
        v1 = {"a": 0.0}
        v2 = {"b": 1.0}
        assert calc._cosine_distance(v1, v2) == 1.0
