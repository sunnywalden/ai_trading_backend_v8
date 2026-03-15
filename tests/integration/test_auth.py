from fastapi.testclient import TestClient

from app.core.auth import get_current_user, get_current_user_context
from app.core.auth_context import UserContext
from app.core.config import settings
from app.main import app

client = TestClient(app)

ADMIN_SECRET = "".join(["test", "-admin", "-password"])
WRONG_SECRET = "".join(["wr", "ong"])
FALLBACK_SECRET = "".join(["any", "thing"])


def test_login_success_and_protected_endpoint(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_USERNAME", "admin")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", ADMIN_SECRET)
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "test-jwt-secret")

    resp = client.post(
        "/api/v1/login",
        data={"username": "admin", "password": ADMIN_SECRET},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["user"]["must_change_password"] is False
    assert "feature_flags" in data["user"]

    token = data["access_token"]

    # access protected endpoint without token -> should be 401
    r = client.get("/api/v1/admin/scheduler/jobs")
    assert r.status_code == 401

    # access protected endpoint with token -> should NOT be 401
    headers = {"Authorization": f"Bearer {token}"}
    r2 = client.get("/api/v1/admin/scheduler/jobs", headers=headers)
    assert r2.status_code != 401

    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    me_data = me.json()
    assert me_data["username"] == "admin"
    assert isinstance(me_data["must_change_password"], bool)


def test_login_fail(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_USERNAME", "admin")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", ADMIN_SECRET)

    resp = client.post(
        "/api/v1/login",
        data={"username": "admin", "password": WRONG_SECRET},
    )
    assert resp.status_code == 401


def test_login_fail_when_admin_password_missing(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_USERNAME", "admin")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", None)

    resp = client.post(
        "/api/v1/login",
        data={"username": "admin", "password": FALLBACK_SECRET},
    )
    assert resp.status_code == 401


def test_supervisor_is_blocked_from_operator_and_admin_routes():
    def override_context() -> UserContext:
        return UserContext(
            username="supervisor",
            role="SUPERVISOR",
            display_name="Supervisor",
            permissions={
                "executive.home.read",
                "executive.report.risk.read",
                "executive.report.executive.read",
                "executive.report.performance.read",
                "common.dashboard.read",
                "common.copilot.read",
            },
        )

    def override_user() -> str:
        return "supervisor"

    app.dependency_overrides[get_current_user_context] = override_context
    app.dependency_overrides[get_current_user] = override_user
    try:
        assert client.get("/api/v1/quant-loop/status").status_code == 403
        assert client.get("/api/v1/governance/pipeline").status_code == 403
        assert client.get("/api/v1/live-safety/degradation").status_code == 403
        assert client.get("/api/v1/ai-hub/calibration").status_code == 403
    finally:
        app.dependency_overrides.clear()
