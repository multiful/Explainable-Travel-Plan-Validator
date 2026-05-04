"""Pydantic models for travel plan validator (main app + VRPTW engine)."""
from __future__ import annotations

import hashlib
import re
from typing import Literal

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings


# ---------------------------------------------------------------------------
# Main application models
# ---------------------------------------------------------------------------


class HardFail(BaseModel):
    fail_type: Literal[
        "OPERATING_HOURS_CONFLICT",
        "TRAVEL_TIME_IMPOSSIBLE",
        "SCHEDULE_INFEASIBLE",
    ]
    message: str
    evidence: str
    confidence: Literal["High", "Medium", "Low"]
    poi_name: str | None = None


class Warning(BaseModel):
    warning_type: Literal[
        "DENSE_SCHEDULE",
        "INEFFICIENT_ROUTE",
        "PHYSICAL_STRAIN",
        "PURPOSE_MISMATCH",
        "AREA_REVISIT",
        "CUMULATIVE_FATIGUE",
    ]
    message: str
    confidence: str


class Scores(BaseModel):
    efficiency: float
    feasibility: float
    purpose_fit: float
    flow: float
    area_intensity: float

    @model_validator(mode="after")
    def validate_ranges(self) -> "Scores":
        for fname in ("efficiency", "feasibility", "purpose_fit", "flow", "area_intensity"):
            v = getattr(self, fname)
            if not 0.0 <= v <= 1.0:
                raise ValueError(f"{fname} must be in [0.0, 1.0], got {v}")
        return self


class AlternativePOI(BaseModel):
    name: str
    distance_km: float
    category: str
    lat: float
    lng: float


class POI(BaseModel):
    poi_id: str
    name: str
    lat: float
    lng: float
    open_start: str  # HH:MM
    open_end: str    # HH:MM
    duration_min: int
    category: str = ""

    @field_validator("poi_id")
    @classmethod
    def poi_id_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("poi_id must not be empty")
        return v

    @field_validator("lat")
    @classmethod
    def validate_lat(cls, v: float) -> float:
        if not -90 <= v <= 90:
            raise ValueError(f"Latitude must be in [-90, 90], got {v}")
        return v

    @field_validator("lng")
    @classmethod
    def validate_lng(cls, v: float) -> float:
        if not -180 <= v <= 180:
            raise ValueError(f"Longitude must be in [-180, 180], got {v}")
        return v

    @field_validator("open_start", "open_end")
    @classmethod
    def validate_hhmm(cls, v: str) -> str:
        if not re.fullmatch(r"\d{2}:\d{2}", v):
            raise ValueError(f"Time must be HH:MM format, got: {v!r}")
        h, m = int(v[:2]), int(v[3:])
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError(f"Invalid time value: {v!r}")
        return v

    @field_validator("duration_min")
    @classmethod
    def validate_duration(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("duration_min must be > 0")
        return v


class PlaceInput(BaseModel):
    name: str
    visit_order: int | None = None      # None → DayPlan에서 해당 일자 내 리스트 순서 자동 할당
    is_accommodation: bool = False      # True → 숙소(Depot). M3/M4 백트래킹 계산 시 기준점 역할

    @field_validator("visit_order")
    @classmethod
    def validate_order(cls, v: int | None) -> int | None:
        if v is None:
            return v
        if v < 1:
            raise ValueError("visit_order must be >= 1")
        return v


class DayPlan(BaseModel):
    """하루 일정 — 장소 이름과 방문 순서 입력."""
    places: list[PlaceInput]

    @field_validator("places")
    @classmethod
    def validate_place_count(cls, v: list[PlaceInput]) -> list[PlaceInput]:
        if len(v) < 1:
            raise ValueError("DayPlan must have at least 1 place")
        if len(v) > 8:
            raise ValueError("DayPlan must have at most 8 places")
        return v

    @model_validator(mode="after")
    def auto_fill_visit_order(self) -> "DayPlan":
        """visit_order 미입력 시 해당 일자 내 리스트 위치(1-based)로 자동 할당."""
        for i, place in enumerate(self.places):
            if place.visit_order is None:
                place.visit_order = i + 1
        return self


class ItineraryPlan(BaseModel):
    days: list[DayPlan]   # 일자별 장소 목록 (len = travel_days)
    party_size: Literal[1, 2, 3, 4, 5]   # 여행 인원 (5 = 5인 이상)
    party_type: Literal["혼자", "친구", "연인", "가족", "아기동반", "어르신동반"]
    travel_type: Literal["cultural", "nature", "shopping", "food", "adventure"] | None = None
    date: str  # 여행 시작일 (YYYY-MM-DD)

    @field_validator("days")
    @classmethod
    def validate_days(cls, v: list[DayPlan]) -> list[DayPlan]:
        if len(v) < 1:
            raise ValueError("ItineraryPlan must have at least 1 day")
        if len(v) > 30:
            raise ValueError("ItineraryPlan must have at most 30 days")
        return v

    @computed_field
    def travel_days(self) -> int:
        return len(self.days)

    @computed_field
    def plan_id(self) -> str:
        parts: list[str] = []
        for d_idx, day in enumerate(self.days):
            for p in sorted(day.places, key=lambda x: x.visit_order or 0):
                parts.append(f"d{d_idx}:{p.name}")
        key = "_".join(parts) + self.date
        return hashlib.sha256(key.encode()).hexdigest()[:12]


class ValidationResult(BaseModel):
    plan_id: str
    final_score: int
    hard_fails: list[HardFail]
    warnings: list[Warning]
    scores: Scores | None = None
    explanations: list[str] = []
    rewards: list[str] = []
    alternatives: dict[str, list[AlternativePOI]] = {}
    penalty_breakdown: dict[str, int] = Field(default_factory=dict)
    bonus_breakdown: dict[str, int] = Field(default_factory=dict)
    repair: dict = Field(default_factory=dict)

    @field_validator("final_score")
    @classmethod
    def validate_score_range(cls, v: int) -> int:
        if not 0 <= v <= 100:
            raise ValueError("final_score must be in [0, 100]")
        return v

    @model_validator(mode="after")
    def hard_fail_score_cap(self) -> "ValidationResult":
        if self.hard_fails and self.final_score >= 60:
            raise ValueError("final_score must be <= 59 when hard_fails are present")
        return self


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-6"
    tour_api_key: str = ""
    kakao_rest_api_key: str = ""
    kakao_mobility_key: str = ""
    seoul_data_api_key: str = ""
    wellness_api_key: str = ""
    barrier_free_api_key: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}

    @model_validator(mode="after")
    def fill_gov_api_keys(self) -> "Settings":
        """wellness_api_key / barrier_free_api_key 미설정 시 tour_api_key로 대체."""
        if not self.wellness_api_key:
            self.wellness_api_key = self.tour_api_key
        if not self.barrier_free_api_key:
            self.barrier_free_api_key = self.tour_api_key
        return self


# ---------------------------------------------------------------------------
# VRPTW engine models
# ---------------------------------------------------------------------------


class VRPTWPlace(BaseModel):
    name: str
    lng: float
    lat: float
    open: str   # HH:MM
    close: str  # HH:MM
    stay_duration: int  # minutes; 0 allowed for depot
    is_depot: bool = False

    @field_validator("open", "close")
    @classmethod
    def validate_hhmm(cls, v: str) -> str:
        if not re.fullmatch(r"\d{2}:\d{2}", v):
            raise ValueError(f"Time must be HH:MM format, got: {v!r}")
        h, m = int(v[:2]), int(v[3:])
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError(f"Invalid time value: {v!r}")
        return v

    @field_validator("lat")
    @classmethod
    def validate_lat(cls, v: float) -> float:
        if not -90 <= v <= 90:
            raise ValueError(f"Latitude must be [-90, 90], got {v}")
        return v

    @field_validator("lng")
    @classmethod
    def validate_lng(cls, v: float) -> float:
        if not -180 <= v <= 180:
            raise ValueError(f"Longitude must be [-180, 180], got {v}")
        return v

    @field_validator("stay_duration")
    @classmethod
    def validate_stay(cls, v: int) -> int:
        if v < 0:
            raise ValueError("stay_duration must be >= 0")
        return v

    @property
    def open_minutes(self) -> int:
        h, m = int(self.open[:2]), int(self.open[3:])
        return h * 60 + m

    @property
    def close_minutes(self) -> int:
        h, m = int(self.close[:2]), int(self.close[3:])
        return h * 60 + m


class VRPTWDay(BaseModel):
    places: list[VRPTWPlace]

    @field_validator("places")
    @classmethod
    def at_least_one(cls, v: list[VRPTWPlace]) -> list[VRPTWPlace]:
        if len(v) < 1:
            raise ValueError("Each day must have at least one place")
        return v


class VRPTWRequest(BaseModel):
    days: list[VRPTWDay]

    @field_validator("days")
    @classmethod
    def at_least_one_day(cls, v: list[VRPTWDay]) -> list[VRPTWDay]:
        if len(v) < 1:
            raise ValueError("Request must have at least one day")
        return v


class DeepDiveItem(BaseModel):
    fact: str
    rule: str
    risk: Literal["OK", "WARNING", "CRITICAL"]
    suggestion: str


class DayRouteComparison(BaseModel):
    day_index: int
    user_order: list[str]        # place names in user order
    optimal_order: list[str] | None  # None when ortools unavailable
    user_travel_seconds: int
    optimal_travel_seconds: int | None


class VRPTWResult(BaseModel):
    risk_score: int                          # 0–100
    passed: bool                             # risk_score >= 60
    user_total_travel_seconds: int
    optimal_total_travel_seconds: int | None
    efficiency_gap: float | None             # (user - optimal) / optimal
    optimal_route: list[DayRouteComparison] | None
    deep_dive: list[DeepDiveItem]
    summary: str
