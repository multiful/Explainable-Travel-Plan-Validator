"""Unit tests for CongestionEngine."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.scoring.congestion_engine import (
    CongestionEngine,
    CongestionLevel,
    CongestionResult,
    _score_to_level,
)

# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

SAMPLE_CSV_DATA = pd.DataFrame(
    {
        "poi_name": ["경복궁"] * 12 + ["남산타워"] * 12 + ["해운대"] * 12,
        "month": list(range(1, 13)) * 3,
        "avg_visitors": (
            [10000, 11000, 15000, 30000, 45000, 35000, 30000, 32000, 40000, 50000, 20000, 12000]
            + [5000, 5500, 7000, 12000, 18000, 14000, 12000, 13000, 16000, 20000, 8000, 5000]
            + [8000, 8500, 9000, 15000, 20000, 25000, 90000, 95000, 30000, 18000, 9000, 8000]
        ),
        "congestion_score": (
            [0.2, 0.22, 0.30, 0.60, 1.00, 0.70, 0.60, 0.64, 0.80, 1.00, 0.40, 0.24]
            + [0.25, 0.275, 0.35, 0.60, 0.90, 0.70, 0.60, 0.65, 0.80, 1.00, 0.40, 0.25]
            + [0.084, 0.090, 0.095, 0.158, 0.211, 0.263, 1.000, 1.000, 0.316, 0.190, 0.095, 0.084]
        ),
        "annual_max": [50000 * 12] * 12 + [20000 * 12] * 12 + [95000 * 12] * 12,
        "annual_min": [10000 * 12] * 12 + [5000 * 12] * 12 + [8000 * 12] * 12,
    }
)


@pytest.fixture
def engine(tmp_path):
    csv = tmp_path / "congestion_stats.csv"
    SAMPLE_CSV_DATA.to_csv(csv, index=False, encoding="utf-8-sig")
    return CongestionEngine(csv_path=csv)


# ──────────────────────────────────────────────
# _score_to_level
# ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "score,expected",
    [
        (0.0, CongestionLevel.LOW),
        (0.39, CongestionLevel.LOW),
        (0.4, CongestionLevel.MEDIUM),
        (0.64, CongestionLevel.MEDIUM),
        (0.65, CongestionLevel.HIGH),
        (0.84, CongestionLevel.HIGH),
        (0.85, CongestionLevel.VERY_HIGH),
        (1.0, CongestionLevel.VERY_HIGH),
    ],
)
def test_score_to_level(score, expected):
    assert _score_to_level(score) == expected


# ──────────────────────────────────────────────
# Exact match
# ──────────────────────────────────────────────


def test_exact_match(engine):
    result = engine.score("경복궁", 10)
    assert result.fallback_used == "exact"
    assert result.matched_poi == "경복궁"
    assert result.congestion_score == pytest.approx(1.0)
    assert result.level == CongestionLevel.VERY_HIGH


def test_exact_match_low_season(engine):
    result = engine.score("경복궁", 1)
    assert result.fallback_used == "exact"
    assert result.congestion_score < 0.4
    assert result.level == CongestionLevel.LOW


# ──────────────────────────────────────────────
# Partial match
# ──────────────────────────────────────────────


def test_partial_match_substring(engine):
    result = engine.score("경복", 5)
    assert result.fallback_used == "partial"
    assert result.matched_poi == "경복궁"


def test_partial_match_superstring(engine):
    result = engine.score("해운대해수욕장", 7)
    assert result.fallback_used == "partial"
    assert result.matched_poi == "해운대"


# ──────────────────────────────────────────────
# Category / global fallback
# ──────────────────────────────────────────────


def test_global_fallback(engine):
    result = engine.score("존재하지않는관광지XYZ", 6)
    assert result.fallback_used in ("category", "global")
    assert 0.0 <= result.congestion_score <= 1.0


def test_category_fallback(engine):
    # '경' prefix matches 경복궁
    result = engine.score("경주역사유적지구", 5)
    assert result.fallback_used in ("category", "global")


# ──────────────────────────────────────────────
# Validation
# ──────────────────────────────────────────────


def test_invalid_month_raises(engine):
    with pytest.raises(ValueError, match="month must be 1-12"):
        engine.score("경복궁", 0)
    with pytest.raises(ValueError, match="month must be 1-12"):
        engine.score("경복궁", 13)


def test_result_is_dataclass(engine):
    result = engine.score("경복궁", 5)
    assert isinstance(result, CongestionResult)
    assert isinstance(result.level, CongestionLevel)


# ──────────────────────────────────────────────
# is_crowded / batch
# ──────────────────────────────────────────────


def test_is_crowded_true(engine):
    assert engine.is_crowded("경복궁", 10, threshold=0.7) is True


def test_is_crowded_false(engine):
    assert engine.is_crowded("경복궁", 1, threshold=0.7) is False


def test_score_itinerary(engine):
    results = engine.score_itinerary(["경복궁", "남산타워", "해운대"], month=8)
    assert len(results) == 3
    assert all(isinstance(r, CongestionResult) for r in results)


# ──────────────────────────────────────────────
# Missing CSV
# ──────────────────────────────────────────────


def test_missing_csv_raises():
    engine = CongestionEngine(csv_path=Path("/nonexistent/path.csv"))
    with pytest.raises(FileNotFoundError, match="혼잡도 데이터 없음"):
        _ = engine._df
