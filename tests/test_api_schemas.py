"""API 입력 스키마의 경계값 검증."""

import pytest
from pydantic import ValidationError

from src.api.schemas import ValidateRequest


def _request(**overrides):
    data = {
        "days": [{"places": [{"name": "경복궁"}]}],
        "party_size": 2,
        "party_type": "친구",
        "travel_type": "cultural",
        "date": "2026-05-10",
        "start_time": "09:00",
    }
    data.update(overrides)
    return ValidateRequest(**data)


def test_date_and_start_time_are_validated():
    with pytest.raises(ValidationError):
        _request(date="not-a-date")
    with pytest.raises(ValidationError):
        _request(start_time="99:99")


def test_empty_day_is_rejected_at_request_boundary():
    with pytest.raises(ValidationError):
        _request(days=[{"places": []}])


def test_place_name_cannot_be_blank():
    with pytest.raises(ValidationError):
        _request(days=[{"places": [{"name": "   "}]}])
