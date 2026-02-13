from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_login_success_and_protected_endpoint():
    # login with default credentials
    resp = client.post("/api/v1/login", data={"username": "admin", "password": "admin"})
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


def test_login_fail():
    resp = client.post("/api/v1/login", data={"username": "admin", "password": "wrong"})
    assert resp.status_code == 401
