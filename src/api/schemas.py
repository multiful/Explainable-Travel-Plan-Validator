"""API 요청/응답 Pydantic 스키마."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class PlaceInputWeb(BaseModel):
    name: str


class DayPlanWeb(BaseModel):
    places: list[PlaceInputWeb]


class ValidateRequest(BaseModel):
    days: list[DayPlanWeb]
    party_size: Literal[1, 2, 3, 4, 5] = 2
    party_type: Literal["혼자", "친구", "연인", "가족", "아기동반", "어르신동반"] = "친구"
    travel_type: Literal["cultural", "nature", "shopping", "food", "adventure"] | None = None
    date: str = "2026-05-10"


class POIInfo(BaseModel):
    name: str
    found: bool        # hardcoded 목록에서 발견 여부
    source: str        # "hardcoded" | "fallback"
    lat: float
    lng: float
    open_start: str
    open_end: str
    duration_min: int


class PlaceItem(BaseModel):
    name: str
    region: str
    category_name: str
    category_code: str
    has_coords: bool = False
    annual_max: float = 0.0


class PlacesResponse(BaseModel):
    places: list[PlaceItem]
    total: int


class ValidateResponse(BaseModel):
    plan_id: str
    final_score: int
    passed: bool
    hard_fails: list[dict]
    warnings: list[dict]
    scores: dict | None
    penalty_breakdown: dict[str, int]
    bonus_breakdown: dict[str, int]
    rewards: list[str]
    poi_info: list[POIInfo]
    repair_suggestions: dict | None = None
