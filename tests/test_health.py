"""배포 프로브가 실제 애플리케이션 준비 상태를 반영하는지 검증한다."""

from fastapi.testclient import TestClient

from src.api import router
from src.api.main import app


def test_health_returns_ok_when_required_data_is_loaded() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["ready"] is True


def test_health_returns_503_when_required_data_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(router, "_PLACE_LIST", [])
    monkeypatch.setattr(router, "_MONTHLY_CONG", {})

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["ready"] is False
