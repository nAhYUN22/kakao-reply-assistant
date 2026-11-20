"""Exercise the public reply workflow without any native process or account."""
import asyncio

from fastapi.testclient import TestClient
import pytest

from kakaoreply.api import create_app
from kakaoreply.context_generation import Turn
from kakaoreply.context_reply import ContextReplies
from kakaoreply.domain import SUFFIX
from kakaoreply.kakao.observation import ReadError
from kakaoreply.kakao.reply_snapshot import ReplySnapshot
from kakaoreply.storage import Journal


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.delenv("KAKAOREPLY_OLLAMA_MODEL", raising=False)


class MemoryProbe:
    def __init__(self):
        self.snapshot = ReplySnapshot((Turn("partner", "영화 보고 왔어"),
                                       Turn("partner", "뭐가 궁금해?")), "snapshot-1", "message-1")
        self.attempts = []
        self.timeout = False

    async def reply_context(self, name):
        return self.snapshot

    async def send_if_current(self, name, expected, text, before_attempt):
        if self.snapshot != expected:
            raise ReadError("CONTEXT_CHANGED")
        before_attempt()
        self.attempts.append((name, text))
        if self.timeout:
            raise TimeoutError("synthetic private error")


def session(app):
    return TestClient(app, base_url="http://127.0.0.1:8765")


def login(client):
    client.headers["X-Session-Token"] = client.get("/api/session").json()["token"]


PREFIX = "/api/kakao/reply/"


def test_simulator_waits_and_answers_last_message_in_context():
    with session(create_app(":memory:", probe=MemoryProbe())) as client:
        login(client)
        client.post("/api/simulator/start", json={"mode": "auto"}).raise_for_status()
        for message in ("영화 보고 왔어", "뭐가 궁금해?"):
            client.post("/api/simulator/messages", json={"text": message, "origin": "partner"}).raise_for_status()
        assert client.post("/api/simulator/advance", json={"seconds": 599}).json()["simulated_send_count"] == 0
        result = client.post("/api/simulator/advance", json={"seconds": 1}).json()
        job, = result["jobs"]
        assert result["simulated_send_count"] == 1 and job["incoming_count"] == 2
        assert "장면" in client.get("/api/jobs/" + job["job_id"]).json()["reply_text"]
        assert not client.get(PREFIX + "history").json()["attempts"]


def prepare(client):
    result = client.post(PREFIX + "prepare", json={"name": "합성 대화", "one_to_one_confirmed": True})
    assert result.status_code == 200, result.text
    return result.json()


def send(client, draft, confirmed=True):
    return client.post(PREFIX + "send", json={"draft_id": draft["draft_id"], "confirmed": confirmed})


def test_context_reply_public_flow_privacy_and_restart(tmp_path):
    probe = MemoryProbe()
    path = str(tmp_path / "context.sqlite")
    with session(create_app(path, probe=probe)) as client:
        assert client.get(PREFIX + "history").status_code == 401
        login(client)
        assert client.post(PREFIX + "prepare", json={"name": "합성 대화", "one_to_one_confirmed": False}).status_code == 409
        draft = prepare(client)
        assert draft["context_count"] == 2 and "장면" in draft["text"]
        assert draft["in_reply_to"] == "뭐가 궁금해?"
        assert draft["text"].count(SUFFIX) == 1
        assert not probe.attempts
        assert send(client, draft, confirmed=False).status_code == 409
        assert not probe.attempts
        assert send(client, draft).json() == {"status": "CONFIRMED_LOCAL"}
        assert probe.attempts == [("합성 대화", draft["text"])]
        assert send(client, draft).json()["detail"] == "DRAFT_EXPIRED"
        assert client.get("/api/state").json()["simulated_send_count"] == 0
    with session(create_app(path, probe=probe)) as client:
        login(client)
        assert send(client, prepare(client)).json()["detail"] == "ALREADY_ATTEMPTED"
        history = client.get(PREFIX + "history").json()["attempts"]
        assert len(history) == 1 and history[0]["status"] == "CONFIRMED_LOCAL"
        assert not history[0]["requires_review"]
    data = (tmp_path / "context.sqlite").read_bytes()
    for private in ("합성 대화", "영화 보고 왔어", draft["text"], draft["draft_id"]):
        assert private.encode() not in data
    assert len(probe.attempts) == 1


def test_unknown_blocks_until_review_and_old_message_cannot_be_retried(tmp_path):
    probe = MemoryProbe()
    probe.timeout = True
    path = str(tmp_path / "uncertain.sqlite")
    with session(create_app(path, probe=probe)) as client:
        login(client)
        assert send(client, prepare(client)).json() == {"detail": "DELIVERY_UNKNOWN"}
    with session(create_app(path, probe=probe)) as client:
        login(client)
        assert send(client, prepare(client)).json()["detail"] == "DELIVERY_UNKNOWN"
        item, = client.get(PREFIX + "history").json()["attempts"]
        assert item["requires_review"] is True
        assert client.post(PREFIX + "review", json={"attempt_id": item["id"], "confirmed": True}).is_success
        assert send(client, prepare(client)).json()["detail"] == "ALREADY_ATTEMPTED"
        assert len(probe.attempts) == 1
        probe.timeout = False
        probe.snapshot = ReplySnapshot((Turn("partner", "안녕"),), "snapshot-2", "message-2")
        assert send(client, prepare(client)).is_success
        assert len(probe.attempts) == 2
        assert client.get(PREFIX + "history").json()["attempts"][1]["status"] == "DELIVERY_UNKNOWN"


@pytest.mark.parametrize("intervention", ["pause", "new_turn", "expire"])
async def test_intervention_before_claim(intervention):
    probe = MemoryProbe()
    entered, release = asyncio.Event(), asyncio.Event()
    send_if_current = probe.send_if_current

    async def gated(*args):
        entered.set()
        await release.wait()
        await send_if_current(*args)

    probe.send_if_current = gated
    now = 0
    journal = Journal()
    service = ContextReplies(probe, journal, clock=lambda: now)
    try:
        draft = await service.prepare("합성 대화")
        task = asyncio.create_task(service.send(draft["draft_id"]))
        await entered.wait()
        with pytest.raises(ReadError, match="REPLY_BUSY"):
            await service.send(draft["draft_id"])
        if intervention == "pause":
            service.clear()
        elif intervention == "expire":
            now = 121
        else:
            probe.snapshot = ReplySnapshot((Turn("owner", "내가 답했어"),), "updated", "new")
        release.set()
        with pytest.raises(ReadError):
            await task
        assert not probe.attempts and not journal.context_history()
    finally:
        service.clear()
        journal.close()


async def test_stop_during_generation_discards_late_draft():
    entered, release = asyncio.Event(), asyncio.Event()

    async def generate(turns):
        entered.set()
        await release.wait()
        return "합성 응답"

    journal = Journal()
    service = ContextReplies(MemoryProbe(), journal, generate=generate)
    task = asyncio.create_task(service.prepare("합성 대화"))
    await entered.wait()
    service.clear()
    release.set()
    with pytest.raises(ReadError, match="CONTEXT_CHANGED"):
        await task
    assert service.draft is None
    journal.close()
