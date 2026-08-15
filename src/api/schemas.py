"""API 요청/응답 Pydantic 스키마."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel


class PlaceInputWeb(BaseModel):
    name: str
    address: str = ""


class DayPlanWeb(BaseModel):
    places: list[PlaceInputWeb]


class POIInfo(BaseModel):
    name: str
    found: bool
    source: str        # "catalog" | "pois" | "fallback"
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
    days: list[DayPlanWeb]
    party_size: Literal[1, 2, 3, 4, 5] = 2
    party_type: Literal["혼자", "친구", "연인", "가족", "아기동반", "어르신동반"] = "친구"
    travel_type: Optional[Literal["cultural", "nature", "shopping", "food", "adventure"]] = None
    date: str = "2026-05-10"
    start_time: str = "09:00"


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
    scores: Optional[dict] = None
    explanations: list[dict] = []
    penalty_breakdown: dict[str, int]
    bonus_breakdown: dict[str, int]
    rewards: list[str]
    alternatives: dict[str, list[dict]] = {}
    poi_info: list[POIInfo]
    repair_suggestions: Optional[dict] = None
    optimal_route: Optional[list[dict]] = None
    vrptw_efficiency_gap: Optional[float] = None
    congestion_warnings: list[dict] = []
