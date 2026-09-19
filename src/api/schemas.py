"""API 요청/응답 Pydantic 스키마."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from src.data.models import _validate_hhmm, _validate_iso_date


class PlaceInputWeb(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    address: str = ""

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("place name must not be blank")
        return value


class DayPlanWeb(BaseModel):
    places: list[PlaceInputWeb] = Field(min_length=1, max_length=8)


class POIInfo(BaseModel):
    name: str
    found: bool
    source: Literal[
        "catalog",
        "pois",
        "fallback",
        "kakao",
        "geocode",
        "tour_api",
        "jeju_csv",
        "seoul_realtime",
    ]
    confidence: Literal["High", "Medium", "Low"] = "Medium"
    lat: float
    lng: float
    open_start: str
    open_end: str
    duration_min: int
    hours_estimated: bool = True
    graph_region: str = ""
    graph_nearby: list[str] = []
    category: str = ""
    day_index: int = 0
    wellness: bool = False
    pet_friendly: bool = False


class PlaceItem(BaseModel):
    name: str
    region: str
    category_name: str
    category_code: str
    has_coords: bool = False
    annual_max: float = 0.0
    firstimage: str = ""
    addr: str = ""
    tags: list[str] = []


class PlacesResponse(BaseModel):
    places: list[PlaceItem]
    total: int


class ValidateRequest(BaseModel):
    days: list[DayPlanWeb] = Field(min_length=1, max_length=30)
    party_size: Literal[1, 2, 3, 4, 5] = 2
    party_type: Literal["혼자", "친구", "연인", "가족", "아기동반", "어르신동반"] = "친구"
    travel_type: Literal["cultural", "nature", "shopping", "food", "adventure"] | None = None
    date: str = "2026-05-10"
    start_time: str = "09:00"
    pet_friendly: bool = False

    @field_validator("date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        return _validate_iso_date(v)

    @field_validator("start_time")
    @classmethod
    def validate_start_time(cls, v: str) -> str:
        return _validate_hhmm(v, "start_time")


class ParseTextRequest(BaseModel):
    text: str


class ParsedPlace(BaseModel):
    name: str
    address: str = ""
    category: str = "12"


class ParsedDay(BaseModel):
    places: list[ParsedPlace]


class ParsedPlanResponse(BaseModel):
    days: list[ParsedDay]


class ValidateResponse(BaseModel):
    plan_id: str
    final_score: int
    base_score: int = 0
    passed: bool
    data_reliability_score: int = 0
    hard_fails: list[dict]
    warnings: list[dict]
    scores: dict | None = None
    explanations: list[dict] = []
    penalty_breakdown: dict[str, int]
    bonus_breakdown: dict[str, int]
    rewards: list[str]
    alternatives: dict[str, list[dict]] = {}
    poi_info: list[POIInfo]
    repair_suggestions: dict | None = None
    optimal_route: list[dict] | None = None
    vrptw_efficiency_gap: float | None = None
    congestion_warnings: list[dict] = []
