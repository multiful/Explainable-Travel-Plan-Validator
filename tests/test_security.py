"""API 인증·레이트리밋 경계 테스트."""

from fastapi.testclient import TestClient

from src.api.main import app


def test_production_requires_bearer_token(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("API_AUTH_TOKEN", "test-secret")
    client = TestClient(app)

    assert client.post("/api/validate", json={}).status_code == 401
    assert (
        client.post(
            "/api/validate", json={}, headers={"Authorization": "Bearer test-secret"}
        ).status_code
        == 422
    )


def test_production_without_auth_token_fails_closed(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("API_AUTH_TOKEN", raising=False)

    client = TestClient(app)
    response = client.post("/api/validate", json={})

    assert response.status_code == 503
    assert "API_AUTH_TOKEN" in response.json()["detail"]
