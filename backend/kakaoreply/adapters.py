"""Deterministic synthetic adapters. No shell, network, or Kakao access."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import math

from .domain import BINDING_ID
from .context_generation import GenerationHold, MAX_TURNS, Turn, rule_reply


class MockClock:
    def __init__(self, now: datetime | None = None):
        self.now = now or datetime(2026, 11, 20, 3, tzinfo=timezone.utc)
        self.monotonic = 0.0

    def advance(self, seconds: float) -> None:
        if isinstance(seconds, bool) or not math.isfinite(seconds) or not 0 <= seconds <= 86400:
            raise ValueError("INVALID_SECONDS")
        self.now += timedelta(seconds=seconds)
        self.monotonic += seconds


class MockLLM:
    version = "mock-2"

    async def generate(self, messages: tuple[str, ...]) -> dict:
        await asyncio.sleep(0)
        text = " ".join(messages)
        # Deliberately conservative examples, not a production language classifier.
        if any(word in text for word in ("송금", "계좌", "돈 보내")):
            action, body, reason = "notify_owner", "", "MONEY_REQUEST"
        elif any(word in text for word in ("시스템 지침", "표시 제거", "명령 실행", "ignore previous")):
            action, body, reason = "hold", "", "UNTRUSTED_INSTRUCTION"
        elif any(word in text for word in ("어디야", "뭐해", "먹었", "약속", "예약")):
            action, body, reason = "hold", "", "MISSING_FACT"
        else:
            action, reason = "reply", "ACKNOWLEDGEMENT"
            try:
                body = rule_reply(tuple(Turn("partner", item) for item in messages[-MAX_TURNS:]))
            except GenerationHold:
                # The simulator keeps its synthetic acknowledgement for arbitrary test messages.
                body = "메시지 고마워. 남겨준 이야기 잘 확인했어."
        return {"action": action, "reply_text": body, "reason_codes": [reason], "used_fact_ids": []}


class FakeTransport:
    """Simulated delivery port, intentionally incapable of calling a live adapter."""
    kind = "mock"
    version = "fake-1"

    def __init__(self, outcome: str = "confirmed"):
        self.outcome = outcome
        self.attempts: list[dict] = []
        self.binding_verified = True
        self.echoes: list[dict] = []

    async def send(self, *, job_id: str, binding_id: str, text: str) -> dict | None:
        self.attempts.append({"job_id": job_id, "binding_id": binding_id, "text": text})
        await asyncio.sleep(0)
        if self.outcome == "error":
            raise TimeoutError("SIMULATED_TIMEOUT")
        if self.outcome != "confirmed":
            return None
        echo = {"job_id": job_id, "binding_id": binding_id, "text": text, "new": True}
        self.echoes.append(echo)
        return echo

    def verify_binding(self, binding_id: str) -> bool:
        return self.binding_verified and binding_id == BINDING_ID

    def forget_body(self, job_id: str) -> None:
        """Remove diagnostic plaintext copies while preserving attempt counts."""
        for record in self.attempts + self.echoes:
            if record["job_id"] == job_id:
                record.pop("text", None)
