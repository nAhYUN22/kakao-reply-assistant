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

    async def verify(self, ticket, *, allow_open_window=False):
        self.operations.append(("verify", allow_open_window))
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
    assert probe.operations == ["catalog", ("verify", False)]


def test_foreground_read_requires_explicit_boolean_and_confirmed_target(local):
    client, probe = local
    client.headers["X-Session-Token"] = client.get("/api/session").json()["token"]
    body = {"id": "ticket", "one_to_one_confirmed": True, "allow_open_window": True}
    for invalid in (1, "true", None):
        assert client.post("/api/kakao/verify", json={**body, "allow_open_window": invalid}).status_code == 422
    assert client.post("/api/kakao/verify", json={**body, "one_to_one_confirmed": False}).status_code == 409
    assert probe.operations == []
    assert client.post("/api/kakao/verify", json=body).status_code == 200
    assert probe.operations == [("verify", True)]


def test_probe_error_response_drops_upstream_text(local):
    client, _ = local
    client.headers["X-Session-Token"] = client.get("/api/session").json()["token"]
    response = client.post("/api/kakao/verify", json={"id": "stale", "one_to_one_confirmed": True})
    assert response.status_code == 409
    assert response.json() == {"detail": "READ_CHECK_FAILED"}


@pytest.mark.parametrize(("reason", "public"), [
    ("CATALOG_TIMEOUT", "CATALOG_TIMEOUT"),
    ("CATALOG_TOO_LARGE", "CATALOG_TOO_LARGE"),
    ("INVALID_PAYLOAD", "INVALID_CATALOG"),
    ("SYNTHETIC_PRIVATE_DIAGNOSTIC", "READ_CHECK_FAILED"),
])
def test_catalog_errors_distinguish_failure_from_empty_result(local, monkeypatch, reason, public):
    client, probe = local
    async def failed_catalog():
        raise ReadError(reason)
    monkeypatch.setattr(probe, "catalog", failed_catalog)
    client.headers["X-Session-Token"] = client.get("/api/session").json()["token"]
    response = client.post("/api/kakao/catalog", json={})
    assert response.status_code == 409
    assert response.json() == {"detail": public}
