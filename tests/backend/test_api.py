import json

from fastapi.testclient import TestClient
import pytest

from kakaoreply.api import create_app


@pytest.fixture
def client():
    with TestClient(create_app(db_path=":memory:"), base_url="http://127.0.0.1:8765") as value:
        yield value


def authorize(client):
    token = client.get("/api/session").json()["token"]
    client.headers["X-Session-Token"] = token


def test_api_vertical_flow(client):
    assert client.get("/api/health").json()["transport"] == "mock"
    assert client.get("/api/state").status_code == 401
    authorize(client)
    assert client.get("/api/state").json()["mode"] == "off"
    assert client.post("/api/simulator/start", json={"mode": "auto"}).status_code == 200
    assert client.post("/api/simulator/messages", json={"origin": "partner", "text": "안녕"}).json()["pending_due_at"]
    response = client.post("/api/simulator/advance", json={"seconds": 600})
    state = response.json()
    assert state["simulated_send_count"] == 1
    detail = client.get("/api/jobs/" + state["jobs"][0]["job_id"]).json()
    assert detail["reply_text"].endswith("— 부재중 AI 답장")
    assert client.post("/api/runtime/pause", json={}).json()["mode"] == "off"


@pytest.mark.parametrize("headers", [{"Host": "attacker.example"}, {"Origin": "https://attacker.example"}, {"Sec-Fetch-Site": "cross-site"}, {"Origin": "null"}])
def test_browser_boundary(client, headers):
    assert client.get("/api/session", headers=headers).status_code == 403


def test_errors_do_not_echo_input(client):
    authorize(client)
    secret = "合成_SECRET_PRIVATE"
    result = client.post("/api/simulator/messages", json={"text": secret, "origin": secret})
    assert result.status_code == 422
    assert secret not in result.text
    assert client.post("/api/simulator/start", json={"mode": "auto", "live_send_enabled": True}).status_code == 422
    assert client.post("/api/simulator/advance", content='{"seconds":NaN}', headers={"Content-Type": "application/json"}).status_code == 422
    assert client.post("/api/runtime/pause", content="{}").status_code == 415
    assert client.get("/api/jobs/missing").status_code == 404


def test_same_origin_requests_and_token_not_cached(client):
    response = client.get("/api/session", headers={"Origin": "http://127.0.0.1:5173"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "access-control-allow-origin" not in response.headers
