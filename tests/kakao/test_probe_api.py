import pytest
from fastapi.testclient import TestClient

from kakaoreply.api import create_app
from kakaoreply.kakao import ReadError


class FakeProbe:
    def __init__(self):
        self.operations = []

    def installed(self):
        return True

    async def catalog(self):
        self.operations.append("catalog")
        return {"choices": [{"id": "ticket", "title": "합성 대화"}]}

    async def verify(self, ticket):
        self.operations.append("verify")
        if ticket != "ticket":
            raise ReadError("SYNTHETIC_PRIVATE_DIAGNOSTIC")
        return {"baseline_count": 2, "new_count": 1, "status": "APPENDED"}


@pytest.fixture
def local():
    probe = FakeProbe()
    app = create_app(db_path=":memory:", probe=probe)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        yield client, probe


def test_probe_requires_local_session_and_explicit_confirmation(local):
    client, probe = local
    request = {"id": "ticket", "one_to_one_confirmed": True}
    assert client.post("/api/kakao/catalog", json={}).status_code == 401
    client.headers["X-Session-Token"] = client.get("/api/session").json()["token"]
    assert client.get("/api/kakao/status").json() == {"installed": True}
    assert client.post("/api/kakao/verify", json=request, headers={"Origin": "https://elsewhere.invalid"}).status_code == 403
    for flag in [False, 1, "true", None]:
        rejected = client.post("/api/kakao/verify", json={**request, "one_to_one_confirmed": flag})
        assert rejected.status_code in {409, 422}
    assert probe.operations == []
    assert client.post("/api/kakao/catalog", json={}).json()["choices"][0]["id"] == "ticket"
    result = client.post("/api/kakao/verify", json=request)
    assert result.json() == {"baseline_count": 2, "new_count": 1, "status": "APPENDED"}
    assert result.headers["cache-control"] == "no-store"
    state = client.get("/api/state").json()
    assert not state["jobs"] and state["mode"] == "off" and not state["live_send_enabled"]
    assert probe.operations == ["catalog", "verify"]


def test_probe_error_response_drops_upstream_text(local):
    client, _ = local
    client.headers["X-Session-Token"] = client.get("/api/session").json()["token"]
    response = client.post("/api/kakao/verify", json={"id": "stale", "one_to_one_confirmed": True})
    assert response.status_code == 409
    assert response.json() == {"detail": "READ_CHECK_FAILED"}
