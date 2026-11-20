"""Single actor with unlocked generation and a durable one-attempt send gate."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import timedelta
import uuid
from zoneinfo import ZoneInfo

from .adapters import FakeTransport, MockClock, MockLLM
from .domain import ACTIVE, BINDING_ID, checked_config, default_config, final_text, in_window, iso, timestamp, validate
from .storage import Journal


class Engine:
    def __init__(self, journal: Journal | None = None, clock: MockClock | None = None,
                 llm: MockLLM | None = None, transport: FakeTransport | None = None,
                 config: dict | None = None):
        self.journal = journal or Journal()
        self.clock = clock or MockClock()
        saved_now = self.journal.get("now")
        if saved_now:
            self.clock.now = max(self.clock.now, timestamp(saved_now))
        self.config = checked_config(config or default_config())
        self.config["mode"] = "off"
        self.llm = llm or MockLLM()
        self.transport = transport or FakeTransport()
        self.lock = asyncio.Lock()
        self.dispatcher = asyncio.Lock()
        self.jobs = self.journal.jobs()
        self.texts: dict[str, str] = {}
        self.pending: list[dict] = []
        self.active_job: str | None = None
        self.epoch = 0
        self.cooldown = timestamp(self.journal.get("cooldown", iso(self.clock.now)))
        self.session_id = self.journal.get("session_id", str(uuid.uuid4()))
        self.last_activity = self.journal.get("last_activity")
        self.paused_reason = None
        for job in self.jobs.values():
            if job["state"] == "DISPATCHING":
                self._transition(job, "DELIVERY_UNKNOWN", ["RECOVERY_UNCERTAIN"])
            elif job["state"] in ACTIVE:
                self._transition(job, "CANCELED_STALE", ["RESTART_BASELINE_REQUIRED"])
        if any(j["state"] == "DELIVERY_UNKNOWN" for j in self.jobs.values()):
            self.paused_reason = "DELIVERY_UNKNOWN"

    def close(self):
        self.journal.close()

    def _transition(self, job, state, reasons=None):
        job["state"] = state
        job["updated_at"] = iso(self.clock.now)
        if reasons is not None:
            job["reason_codes"] = reasons
        self.journal.save_job(job)

    def _cancel(self, state, reason):
        for job in self.jobs.values():
            if job["state"] in ACTIVE:
                self._transition(job, state, [reason])
        self.active_job = None

    def _new_job(self, state="PENDING", reason=None):
        now = iso(self.clock.now)
        job = {"job_id": str(uuid.uuid4()), "state": state, "reason_codes": [reason] if reason else [],
               "due_at": None, "created_at": now, "updated_at": now,
               "incoming_count": len(self.pending), "attempt_count": 0}
        self.jobs[job["job_id"]] = job
        self.journal.save_job(job)
        return job

    def _schedule(self):
        if not self.pending:
            return
        due = max(self.pending[0]["at"] + timedelta(seconds=self.config["reply_delay"]),
                  self.pending[-1]["at"] + timedelta(seconds=self.config["settle"]), self.cooldown)
        if self.active_job and self.jobs[self.active_job]["state"] == "PENDING":
            job = self.jobs[self.active_job]
        else:
            job = self._new_job()
            self.active_job = job["job_id"]
        job["due_at"] = iso(due)
        job["incoming_count"] = len(self.pending)
        job["updated_at"] = iso(self.clock.now)
        self.journal.save_job(job)

    def _activity(self):
        if self.last_activity and (self.clock.now - timestamp(self.last_activity)).total_seconds() >= self.config["session_gap"]:
            self.session_id = str(uuid.uuid4())
        self.last_activity = iso(self.clock.now)
        self.journal.put("session_id", self.session_id)
        self.journal.put("last_activity", self.last_activity)

    async def start(self, mode: str):
        if mode not in {"draft", "auto"}:
            raise ValueError("INVALID_MODE")
        async with self.lock:
            if any(j["state"] == "DELIVERY_UNKNOWN" for j in self.jobs.values()):
                raise ValueError("DELIVERY_UNKNOWN_REQUIRES_REVIEW")
            self.epoch += 1
            self._cancel("CANCELED_STALE", "MODE_CHANGED")
            self.pending.clear()
            self.config["mode"] = mode
            self.config["active_windows"] = [
                {"days": list(range(1, 8)), "start": "00:00", "end": "12:00"},
                {"days": list(range(1, 8)), "start": "12:00", "end": "00:00"},
            ]
            self.paused_reason = None
            return self.state()

    async def pause(self):
        async with self.lock:
            self.epoch += 1
            self.config["mode"] = "off"
            self._cancel("CANCELED_STALE", "STOPPED")
            self.pending.clear()
            if self.paused_reason != "DELIVERY_UNKNOWN":
                self.paused_reason = "STOPPED"
            return self.state()

    async def message(self, text: str, origin: str = "partner", event_id: str | None = None,
                      binding_id: str = BINDING_ID):
        event = {"event_id": event_id or str(uuid.uuid4()), "binding_id": binding_id,
                 "origin": origin, "source": "mock", "observed_at": iso(self.clock.now),
                 "source_time": None, "sequence": 0, "text": text,
                 "authorship": "human_verified" if origin in {"partner", "owner"} else "unknown",
                 "confidence": {"author": "verified" if origin in {"partner", "owner"} else "ambiguous",
                                "newness": "verified", "time": "observation_only"}}
        return await self.ingest(event)

    async def ingest(self, event: dict):
        validate("message-event", event)
        async with self.lock:
            if not self.journal.accept_event(event["event_id"]):
                return self.state()
            if event["binding_id"] != BINDING_ID:
                self._new_job("SKIPPED_POLICY", "WRONG_BINDING")
                return self.state()
            if event["source"] != "mock" or event["confidence"]["newness"] == "baseline":
                self._new_job("SKIPPED_POLICY", "BASELINE_OR_UNSUPPORTED_SOURCE")
                return self.state()
            if event["origin"] in {"system", "bot"}:
                return self.state()
            self.epoch += 1
            if (event["origin"] == "unknown" or event["confidence"]["author"] != "verified" or
                    event["confidence"]["newness"] != "verified" or event["confidence"]["time"] == "missing" or
                    event["authorship"] != "human_verified"):
                self._cancel("SKIPPED_POLICY", "AMBIGUOUS_AUTHOR_OR_CONTEXT")
                self.pending.clear()
                self._new_job("SKIPPED_POLICY", "AMBIGUOUS_AUTHOR_OR_CONTEXT")
                return self.state()
            self._activity()
            if event["origin"] == "partner" and event["text"] == "/봇중지":
                self.config["mode"] = "off"
                self._cancel("CANCELED_STALE", "PARTNER_STOPPED")
                self.pending.clear()
                if self.paused_reason != "DELIVERY_UNKNOWN":
                    self.paused_reason = "PARTNER_STOPPED"
                return self.state()
            if event["origin"] == "owner":
                self._cancel("CANCELED_HUMAN", "OWNER_REPLIED")
                self.pending.clear()
                self.cooldown = self.clock.now + timedelta(seconds=self.config["human_cooldown"])
                self.journal.put("cooldown", iso(self.cooldown))
                return self.state()
            if self.config["mode"] == "off" or self.paused_reason:
                self._new_job("SKIPPED_POLICY", "NOT_RUNNING")
                return self.state()
            observed = timestamp(event["source_time"] or event["observed_at"])
            if observed > self.clock.now or (self.clock.now - observed).total_seconds() > self.config["max_incoming_age"]:
                self._cancel("SKIPPED_POLICY", "STALE_INPUT")
                self.pending.clear()
                self._new_job("SKIPPED_POLICY", "STALE_INPUT")
                return self.state()
            # A candidate is immutable once generation begins; a new input gets a new job.
            if self.active_job and self.jobs[self.active_job]["state"] in {"GENERATING", "READY"}:
                self._transition(self.jobs[self.active_job], "CANCELED_STALE", ["CONTEXT_CHANGED"])
                self.active_job = None
            self.pending.append({"id": event["event_id"], "at": observed, "text": event["text"]})
            self._schedule()
            return self.state()

    def _policy(self, pending: list[dict]) -> str | None:
        if self.config["mode"] == "off" or self.paused_reason:
            return "NOT_RUNNING"
        if not self.transport.verify_binding(BINDING_ID):
            return "UNVERIFIED_BINDING"
        if not pending or (self.clock.now - pending[0]["at"]).total_seconds() > self.config["max_incoming_age"]:
            return "STALE_INPUT"
        if self.clock.now < self.cooldown:
            return "HUMAN_COOLDOWN"
        if not in_window(self.clock.now, self.config):
            return "OUTSIDE_ACTIVE_WINDOW"
        attempts = self.journal.attempts()
        local_date = self.clock.now.astimezone(ZoneInfo(self.config["timezone"])).date()
        hour_count = sum(0 <= (self.clock.now - timestamp(at)).total_seconds() < 3600 for _, at, _ in attempts)
        day_count = sum(timestamp(at).astimezone(ZoneInfo(self.config["timezone"])).date() == local_date for _, at, _ in attempts)
        session_count = sum(session == self.session_id for _, _, session in attempts)
        if (hour_count >= self.config["max_per_hour"] or day_count >= self.config["max_per_day"] or
                session_count >= self.config["max_autoreplies_session"]):
            return "REPLY_LIMIT"
        return None

    async def advance(self, seconds: float):
        async with self.lock:
            self.clock.advance(seconds)
            self.journal.put("now", iso(self.clock.now))
        await self.run_due()
        return self.state()

    async def run_due(self):
        async with self.lock:
            if not self.active_job:
                return
            job = self.jobs[self.active_job]
            if job["state"] != "PENDING":
                return
            snapshot = list(self.pending)
            # Expiry does not wait for settle/cooldown: continuous input must not
            # keep an old unresolved bundle alive indefinitely.
            if not snapshot or (self.clock.now - snapshot[0]["at"]).total_seconds() > self.config["max_incoming_age"]:
                self._transition(job, "SKIPPED_POLICY", ["STALE_INPUT"])
                self.pending.clear()
                self.active_job = None
                return
            if timestamp(job["due_at"]) > self.clock.now:
                return
            failure = self._policy(snapshot)
            if failure:
                self._transition(job, "SKIPPED_POLICY", [failure])
                self.pending.clear()
                self.active_job = None
                return
            epoch = self.epoch
            self._transition(job, "GENERATING")
        decision = None
        for _ in range(self.config["llm_retries"] + 1):
            try:
                decision = await asyncio.wait_for(self.llm.generate(tuple(p["text"] for p in snapshot)), self.config["llm_timeout"])
                validate("reply-decision", decision)
                if not set(decision["used_fact_ids"]).issubset(set()):
                    raise ValueError("INVALID_FACT")
                if decision["action"] == "reply":
                    text = final_text(decision, self.config["max_chars"])
                break
            except asyncio.CancelledError:
                async with self.lock:
                    if job["state"] == "GENERATING":
                        self._transition(job, "CANCELED_STALE", ["GENERATION_CANCELED"])
                raise
            except Exception:
                decision = None
        async with self.dispatcher:
            async with self.lock:
                if epoch != self.epoch or job["state"] != "GENERATING":
                    return
                if decision is None:
                    self._transition(job, "FAILED_BEFORE_DISPATCH", ["INVALID_OR_FAILED_GENERATION"])
                    self.active_job = None
                    self.pending.clear()
                    return
                if decision["action"] != "reply":
                    self._transition(job, "SKIPPED_POLICY", decision["reason_codes"])
                    self.texts[job["job_id"]] = decision["reply_text"]
                    self.active_job = None
                    self.pending.clear()
                    return
                self.texts[job["job_id"]] = text
                self._transition(job, "READY", decision["reason_codes"])
                if self.config["mode"] == "draft":
                    return
                failure = self._policy(snapshot)
                if failure:
                    self._transition(job, "SKIPPED_POLICY", [failure])
                    self.active_job = None
                    self.pending.clear()
                    return
                # Simulated SendGate never changes live_send_enabled or routes to live code.
                if self.transport.kind != "mock" or self.config["transport"] != "mock" or self.config["live_send_enabled"]:
                    self._transition(job, "SKIPPED_POLICY", ["M1_MOCK_ONLY"])
                    self.active_job = None
                    self.pending.clear()
                    return
                job["state"] = "DISPATCHING"
                job["updated_at"] = iso(self.clock.now)
                job["attempt_count"] = 1
                if not self.journal.claim(job, iso(self.clock.now), self.session_id):
                    self._transition(job, "DELIVERY_UNKNOWN", ["ATTEMPT_ALREADY_EXISTS"])
                    self.paused_reason = "DELIVERY_UNKNOWN"
                    return
                included = {p["id"] for p in snapshot}
                self.pending = [p for p in self.pending if p["id"] not in included]
                self.active_job = None
            try:
                echo = await self.transport.send(job_id=job["job_id"], binding_id=BINDING_ID, text=text)
                confirmed = (echo is not None and echo.get("job_id") == job["job_id"] and
                             echo.get("binding_id") == BINDING_ID and echo.get("text") == text and echo.get("new") is True)
            except BaseException as error:
                async with self.lock:
                    self._unknown(job)
                if isinstance(error, asyncio.CancelledError):
                    raise
                if not isinstance(error, Exception):
                    raise
                return
            async with self.lock:
                if confirmed:
                    self._transition(job, "CONFIRMED_LOCAL")
                    self._activity()
                else:
                    self._unknown(job)

    def _unknown(self, job):
        self._transition(job, "DELIVERY_UNKNOWN", ["DELIVERY_UNKNOWN"])
        self.paused_reason = "DELIVERY_UNKNOWN"
        self.config["mode"] = "off"
        self.epoch += 1
        self._cancel("SKIPPED_POLICY", "DELIVERY_UNKNOWN")
        self.pending.clear()

    def state(self):
        pending_due = self.jobs[self.active_job]["due_at"] if self.active_job and self.jobs[self.active_job]["state"] == "PENDING" else None
        return {"transport": "mock", "mode": self.config["mode"], "live_send_enabled": False,
                "now": iso(self.clock.now), "binding_id": BINDING_ID,
                "reply_delay": self.config["reply_delay"], "settle": self.config["settle"],
                "human_cooldown": self.config["human_cooldown"], "pending_due_at": pending_due,
                "paused_reason": self.paused_reason,
                "simulated_send_count": sum(j["state"] == "CONFIRMED_LOCAL" for j in self.jobs.values()),
                "jobs": deepcopy(list(reversed(self.jobs.values())))}

    def detail(self, job_id):
        if job_id not in self.jobs:
            raise KeyError("JOB_NOT_FOUND")
        return {**deepcopy(self.jobs[job_id]), "reply_text": self.texts.get(job_id)}
