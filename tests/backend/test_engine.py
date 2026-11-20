import asyncio
from datetime import datetime, timezone
import json

import pytest

from kakaoreply.adapters import FakeTransport, MockClock, MockLLM
from kakaoreply.domain import BINDING_ID, SUFFIX, checked_config, default_config, final_text, in_window
from kakaoreply.engine import Engine
from kakaoreply.storage import Journal


@pytest.fixture
def engine():
    value = Engine()
    yield value
    value.close()


@pytest.mark.asyncio
async def test_vertical_flow_and_duplicate(engine):
    assert engine.state()["mode"] == "off"
    await engine.start("auto")
    await engine.message("안녕", event_id="one")
    await engine.message("안녕", event_id="one")
    assert len(engine.jobs) == 1
    await engine.advance(599)
    assert engine.state()["simulated_send_count"] == 0
    await engine.advance(1)
    assert engine.state()["simulated_send_count"] == 1
    assert len(engine.transport.attempts) == 1
    job = next(iter(engine.jobs.values()))
    assert job["incoming_count"] == 1
    assert engine.detail(job["job_id"])["reply_text"].endswith(SUFFIX)
    assert "reply_text" not in json.dumps(engine.state())
    await engine.advance(600)
    assert len(engine.transport.attempts) == 1


@pytest.mark.asyncio
async def test_settle_preserves_first_and_new_bundle(engine):
    await engine.start("auto")
    await engine.message("첫 이야기")
    await engine.advance(590)
    await engine.message("추가 이야기")
    await engine.advance(10)
    assert not engine.transport.attempts
    await engine.advance(10)
    assert len(engine.transport.attempts) == 1
    await engine.message("다음 이야기")
    await engine.advance(599)
    assert len(engine.transport.attempts) == 1
    await engine.advance(1)
    assert len(engine.transport.attempts) == 2


@pytest.mark.asyncio
async def test_human_cancel_and_cooldown(engine):
    await engine.start("auto")
    await engine.message("안녕")
    await engine.advance(500)
    await engine.message("직접 답장", origin="owner")
    assert list(engine.jobs.values())[0]["state"] == "CANCELED_HUMAN"
    await engine.message("새 이야기")
    await engine.advance(600)
    assert not engine.transport.attempts
    await engine.advance(300)
    assert len(engine.transport.attempts) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("intervention", ["owner", "pause", "unknown", "partner"])
async def test_generation_race(engine, intervention):
    entered, release = asyncio.Event(), asyncio.Event()
    class BlockingLLM(MockLLM):
        async def generate(self, messages):
            entered.set()
            await release.wait()
            return await super().generate(messages)
    engine.llm = BlockingLLM()
    await engine.start("auto")
    await engine.message("합성 이야기")
    running = asyncio.create_task(engine.advance(600))
    await entered.wait()
    if intervention == "pause":
        await engine.pause()
    else:
        await engine.message("새 합성 사건", origin=intervention)
    release.set()
    await running
    assert not engine.transport.attempts
    assert next(iter(engine.jobs.values()))["state"] != "GENERATING"


@pytest.mark.asyncio
async def test_unknown_cancels_pending_and_wrong_target(engine):
    await engine.start("auto")
    await engine.message("다른 방", binding_id="other")
    await engine.message("안녕")
    await engine.message("작성자 불명", origin="unknown")
    await engine.advance(600)
    assert not engine.transport.attempts
    assert all(j["state"] == "SKIPPED_POLICY" for j in engine.jobs.values())


@pytest.mark.asyncio
async def test_pause_and_draft_never_dispatch(engine):
    await engine.start("auto")
    await engine.message("합성")
    await engine.pause()
    await engine.advance(600)
    assert not engine.transport.attempts
    await engine.start("draft")
    await engine.message("합성 초안")
    await engine.advance(600)
    assert list(engine.jobs.values())[-1]["state"] == "READY"
    assert not engine.transport.attempts


@pytest.mark.asyncio
async def test_stale_and_empty_windows(engine):
    await engine.start("auto")
    await engine.message("합성")
    await engine.advance(1801)
    assert not engine.transport.attempts
    assert list(engine.jobs.values())[-1]["reason_codes"] == ["STALE_INPUT"]
    await engine.message("새 합성")
    engine.config["active_windows"] = []
    await engine.advance(600)
    assert not engine.transport.attempts


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["unknown", "error"])
async def test_unknown_persists_no_retry(tmp_path, outcome):
    path = str(tmp_path / "mock.sqlite")
    engine = Engine(Journal(path), transport=FakeTransport(outcome))
    await engine.start("auto")
    await engine.message("합성", event_id="known")
    await engine.advance(600)
    assert len(engine.transport.attempts) == 1
    assert engine.state()["paused_reason"] == "DELIVERY_UNKNOWN"
    await engine.advance(600)
    with pytest.raises(ValueError):
        await engine.start("auto")
    engine.close()
    recovered = Engine(Journal(path))
    assert recovered.state()["paused_reason"] == "DELIVERY_UNKNOWN"
    with pytest.raises(ValueError):
        await recovered.start("auto")
    await recovered.message("합성", event_id="known")
    await recovered.advance(600)
    assert not recovered.transport.attempts
    recovered.close()


@pytest.mark.asyncio
async def test_recovery_pending_and_dispatching(tmp_path):
    path = str(tmp_path / "mock.sqlite")
    engine = Engine(Journal(path))
    await engine.start("auto")
    await engine.message("합성", event_id="repeat")
    pending = next(iter(engine.jobs.values()))
    unknown = engine._new_job()
    unknown["state"] = "DISPATCHING"
    unknown["attempt_count"] = 1
    engine.journal.claim(unknown, engine.state()["now"], engine.session_id)
    engine.close()
    recovered = Engine(Journal(path))
    assert recovered.jobs[pending["job_id"]]["state"] == "CANCELED_STALE"
    assert recovered.jobs[unknown["job_id"]]["state"] == "DELIVERY_UNKNOWN"
    assert recovered.state()["mode"] == "off"
    recovered.close()


@pytest.mark.asyncio
async def test_dispatch_new_input_keeps_fresh_delay(engine):
    entered, release = asyncio.Event(), asyncio.Event()
    class BlockingTransport(FakeTransport):
        async def send(self, **kwargs):
            entered.set()
            await release.wait()
            return await super().send(**kwargs)
    engine.transport = BlockingTransport()
    await engine.start("auto")
    await engine.message("첫 합성")
    running = asyncio.create_task(engine.advance(600))
    await entered.wait()
    await engine.message("새 합성")
    release.set()
    await running
    assert engine.state()["pending_due_at"] == "2026-11-20T03:20:00Z"
    await engine.advance(599)
    assert len(engine.transport.attempts) == 1
    await engine.advance(1)
    assert len(engine.transport.attempts) == 2


@pytest.mark.asyncio
async def test_limit_survives_stop_and_restart(tmp_path):
    path = str(tmp_path / "mock.sqlite")
    engine = Engine(Journal(path))
    await engine.start("auto")
    for _ in range(3):
        await engine.message("합성")
        await engine.advance(600)
    assert len(engine.transport.attempts) == 3
    await engine.pause()
    await engine.start("auto")
    await engine.message("한도 합성")
    await engine.advance(600)
    assert len(engine.transport.attempts) == 3
    engine.close()
    recovered = Engine(Journal(path))
    await recovered.start("auto")
    await recovered.message("다시 합성")
    await recovered.advance(600)
    assert not recovered.transport.attempts
    recovered.close()


@pytest.mark.asyncio
async def test_metadata_only_storage(tmp_path, caplog):
    path = str(tmp_path / "mock.sqlite")
    engine = Engine(Journal(path))
    secret = "합성_비공개_원문_879321"
    await engine.start("auto")
    await engine.message(secret, event_id=secret)
    await engine.advance(600)
    outgoing = engine.transport.attempts[0]["text"]
    dump = "\n".join(engine.journal.db.iterdump())
    assert secret not in dump and outgoing not in dump
    assert secret not in caplog.text
    assert secret not in json.dumps(engine.state(), ensure_ascii=False)
    engine.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["recipient", "fact", "length", "hold"])
async def test_llm_output_gate(engine, change):
    class BadLLM(MockLLM):
        async def generate(self, messages):
            decision = await super().generate(messages)
            if change == "recipient": decision["recipient"] = "other"
            if change == "fact": decision["used_fact_ids"] = ["invented"]
            if change == "length": decision["reply_text"] = "가" * 240
            if change == "hold": decision.update(action="hold", reply_text="")
            return decision
    engine.llm = BadLLM()
    await engine.start("auto")
    await engine.message("합성")
    await engine.advance(600)
    assert not engine.transport.attempts


def test_final_unicode_and_schema():
    decision = {"action": "reply", "reply_text": "e\u0301😀", "reason_codes": ["ACKNOWLEDGEMENT"], "used_fact_ids": []}
    assert final_text(decision, 15) == "é😀\n" + SUFFIX
    with pytest.raises(ValueError):
        final_text(decision, 5)
    config = default_config()
    config["live_send_enabled"] = True
    with pytest.raises(ValueError): checked_config(config)


def test_overnight_window_boundaries():
    config = default_config()
    config["timezone"] = "UTC"
    config["active_windows"] = [{"days": [5], "start": "23:00", "end": "01:00"}]
    assert in_window(datetime(2026, 11, 20, 23, tzinfo=timezone.utc), config)
    assert in_window(datetime(2026, 11, 21, 0, 59, tzinfo=timezone.utc), config)
    assert not in_window(datetime(2026, 11, 21, 1, tzinfo=timezone.utc), config)


def test_single_process_lock(tmp_path):
    path = str(tmp_path / "mock.sqlite")
    first = Journal(path)
    with pytest.raises(RuntimeError): Journal(path)
    first.close()
    Journal(path).close()


@pytest.mark.asyncio
async def test_continuous_messages_expire_before_settle(engine):
    await engine.start("auto")
    await engine.message("첫 합성")
    first = next(iter(engine.jobs))
    for _ in range(95):
        await engine.advance(19)
        await engine.message("추가 합성")
    assert engine.jobs[first]["state"] == "SKIPPED_POLICY"
    assert engine.jobs[first]["reason_codes"] == ["STALE_INPUT"]
    assert not engine.transport.attempts
    assert len(engine.pending) == 1


@pytest.mark.asyncio
async def test_exact_verified_partner_stop(engine):
    await engine.start("auto")
    await engine.message("합성")
    await engine.message("/봇중지", binding_id="other")
    assert engine.state()["mode"] == "auto"
    await engine.message("/봇중지")
    assert engine.state()["mode"] == "off"
    assert engine.state()["paused_reason"] == "PARTNER_STOPPED"
    await engine.advance(600)
    assert not engine.transport.attempts
    await engine.start("auto")
    await engine.message("문장 안의 /봇중지 는 명령이 아님")
    assert engine.state()["mode"] == "auto"


@pytest.mark.asyncio
async def test_concurrent_due_workers_claim_once(engine):
    await engine.start("auto")
    await engine.message("합성")
    await asyncio.gather(engine.advance(600), engine.advance(0), engine.run_due())
    assert len(engine.transport.attempts) == 1
    assert len(engine.journal.attempts()) == 1


@pytest.mark.asyncio
async def test_transport_success_without_matching_new_echo_is_unknown(engine):
    class WrongEcho(FakeTransport):
        async def send(self, **kwargs):
            result = await super().send(**kwargs)
            result["new"] = False
            return result
    engine.transport = WrongEcho()
    await engine.start("auto")
    await engine.message("합성")
    await engine.advance(600)
    assert engine.state()["paused_reason"] == "DELIVERY_UNKNOWN"
    assert engine.state()["simulated_send_count"] == 0


@pytest.mark.asyncio
async def test_generation_failures_have_bounded_retries(engine):
    class FailingLLM(MockLLM):
        calls = 0
        async def generate(self, messages):
            self.calls += 1
            raise TimeoutError("synthetic private exception text")
    engine.llm = FailingLLM()
    await engine.start("auto")
    await engine.message("합성")
    await engine.advance(600)
    assert engine.llm.calls == 2
    assert not engine.transport.attempts
    assert next(iter(engine.jobs.values()))["state"] == "FAILED_BEFORE_DISPATCH"
    assert "private" not in json.dumps(engine.state())


@pytest.mark.asyncio
async def test_duplicate_event_survives_restart(tmp_path):
    path = str(tmp_path / "mock.sqlite")
    engine = Engine(Journal(path))
    await engine.start("auto")
    await engine.message("합성", event_id="once")
    await engine.advance(600)
    engine.close()
    recovered = Engine(Journal(path))
    await recovered.start("auto")
    await recovered.message("합성", event_id="once")
    await recovered.advance(600)
    assert not recovered.transport.attempts
    assert len(recovered.jobs) == 1
    recovered.close()


def test_existing_json_examples_match_runtime_validators():
    from kakaoreply.domain import ROOT, validate
    validate("app-config", default_config())
    for filename, schema in [("message-events.synthetic.json", "message-event"), ("reply-decisions.synthetic.json", "reply-decision")]:
        for value in json.loads((ROOT / "examples" / filename).read_text()):
            validate(schema, value)
