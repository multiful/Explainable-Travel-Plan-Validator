"""API 인증·레이트리밋 경계 테스트."""

from fastapi.testclient import TestClient

from src.api.main import app


def test_production_requires_bearer_token(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("API_AUTH_TOKEN", "test-secret")
    client = TestClient(app)

    assert client.get("/api/places").status_code == 401
    assert (
        client.get("/api/places", headers={"Authorization": "Bearer test-secret"}).status_code
        == 200
    )
