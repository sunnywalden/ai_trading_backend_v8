from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

client = TestClient(app)


def test_login_success_and_protected_endpoint(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_USERNAME", "admin")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", "test-admin-password")
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "test-jwt-secret")

    resp = client.post(
        "/api/v1/login",
        data={"username": "admin", "password": "test-admin-password"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data

    token = data["access_token"]

    # access protected endpoint without token -> should be 401
    r = client.get("/api/v1/admin/scheduler/jobs")
    assert r.status_code == 401

    # access protected endpoint with token -> should NOT be 401
    headers = {"Authorization": f"Bearer {token}"}
    r2 = client.get("/api/v1/admin/scheduler/jobs", headers=headers)
    assert r2.status_code != 401


def test_login_fail(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_USERNAME", "admin")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", "test-admin-password")

    resp = client.post(
        "/api/v1/login",
        data={"username": "admin", "password": "wrong"},
    )
    assert resp.status_code == 401


def test_login_fail_when_admin_password_missing(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_USERNAME", "admin")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", None)

    resp = client.post(
        "/api/v1/login",
        data={"username": "admin", "password": "anything"},
    )
    assert resp.status_code == 401
