from fastapi.testclient import TestClient

from src.api.main import app
from src.api.security import _LIMITER
from src.data.models import Settings
from src.matrix.route_matrix import RouteMatrixService


def test_vercel_cache_uses_writable_temp_directory(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    service = RouteMatrixService.from_settings(Settings(kakao_mobility_key="test", _env_file=None))
    assert str(service.provider._cache_path).startswith("/tmp/")


def test_vercel_defaults_to_production(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    assert Settings(_env_file=None).environment == "production"


def test_static_deployment_assets():
    with TestClient(app) as client:
        for path in ("/", "/static/landing.css", "/static/qtrip-map.png", "/static/api-client.js"):
            assert client.get(path).status_code == 200


def test_oversize_document_is_rejected_before_extraction(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    _LIMITER._hits.clear()
    with TestClient(app) as client:
        response = client.post(
            "/api/parse/document",
            files={"file": ("large.pdf", b"x" * (4 * 1024 * 1024 + 1), "application/pdf")},
        )
    assert response.status_code == 413
    assert "4MB" in response.json()["detail"]
