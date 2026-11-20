"""A user-requested reply to one snapshot of a named conversation."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import secrets
import time

from .context_generation import GenerationHold, generate_reply
from .domain import SUFFIX, final_text
from .kakao.observation import ReadError
from .kakao.reply_snapshot import ReplySnapshot
from .storage import Journal, StorageError


@dataclass(repr=False)
class Draft:
    token: str
    name: str
    snapshot: ReplySnapshot
    text: str
    expires_at: float


class ContextReplies:
    """One volatile draft per local app. Only the explicit send endpoint can claim it."""

    def __init__(self, probe, journal: Journal, *, generate=generate_reply, clock=time.monotonic):
        self.probe = probe
        self.journal = journal
        self.generate = generate
        self.clock = clock
        self.epoch = 0
        self.draft: Draft | None = None
        self.expiry: asyncio.TimerHandle | None = None
        self.sending = False

    def clear(self):
        self.epoch += 1
        self.draft = None
        if self.expiry is not None:
            self.expiry.cancel()
            self.expiry = None

    async def prepare(self, name: str) -> dict:
        if self.sending:
            raise ReadError("REPLY_BUSY")
        self.clear()
        epoch = self.epoch
        name = name.strip()
        snapshot = await self.probe.reply_context(name)
        if not snapshot.turns:
            raise ReadError("EMPTY_CONTEXT")
        if snapshot.turns[-1].author != "partner":
            raise ReadError("LAST_NOT_PARTNER")
        if any(turn.text.strip() == "/봇중지" for turn in snapshot.turns):
            raise ReadError("STOPPED")
        if self.epoch != epoch:
            raise ReadError("CONTEXT_CHANGED")
        try:
            async with asyncio.timeout(30):
                body = await self.generate(snapshot.turns)
            if not isinstance(body, str) or SUFFIX in body:
                raise GenerationHold()
            text = final_text({"action": "reply", "reply_text": body, "reason_codes": ["ROUTINE_REPLY"],
                               "used_fact_ids": []}, 240)
        except GenerationHold as error:
            reason = str(error)
            if reason in {"MODEL_UNAVAILABLE", "MODEL_INVALID_RESPONSE"}:
                raise ReadError(reason) from None
            if reason == "UNSUPPORTED_CONTENT":
                raise ReadError("GENERATION_UNSUPPORTED") from None
            raise ReadError("GENERATION_HOLD") from None
        except (ValueError, TimeoutError):
            raise ReadError("GENERATION_HOLD") from None
        if self.epoch != epoch:
            raise ReadError("CONTEXT_CHANGED")
        token = secrets.token_urlsafe(24)
        ttl = 120
        self.draft = Draft(token, name, snapshot, text, self.clock() + ttl)
        self.expiry = asyncio.get_running_loop().call_later(ttl, self.clear)
        return {"draft_id": token, "text": text, "in_reply_to": snapshot.turns[-1].text,
                "context_count": len(snapshot.turns), "expires_in_seconds": ttl}

    async def send(self, token: str) -> dict:
        draft = self.draft
        if self.sending:
            raise ReadError("REPLY_BUSY")
        if draft is None or not secrets.compare_digest(token.encode(), draft.token.encode()):
            raise ReadError("DRAFT_EXPIRED")
        self.clear()  # Consume before any await. Even a rejected submission needs a fresh draft.
        epoch = self.epoch
        attempted = False

        def check_current():
            if self.epoch != epoch:
                raise ReadError("STOPPED")
            if self.clock() >= draft.expires_at:
                raise ReadError("DRAFT_EXPIRED")

        def before_attempt():
            nonlocal attempted
            check_current()
            if attempted:
                raise ReadError("ALREADY_ATTEMPTED")
            self.journal.claim_context_attempt(draft.snapshot.latest_key)
            attempted = True

        check_current()
        self.sending = True
        try:
            await self.probe.send_if_current(draft.name, draft.snapshot, draft.text, before_attempt)
            if not attempted:
                raise ReadError("LIVE_SEND_UNAVAILABLE")
            self.journal.confirm_context_attempt(draft.snapshot.latest_key)
            return {"status": "CONFIRMED_LOCAL"}
        except Exception as error:
            if attempted:
                raise ReadError("DELIVERY_UNKNOWN") from None
            if isinstance(error, ReadError):
                raise
            if isinstance(error, StorageError) and str(error) in {"DELIVERY_UNKNOWN", "ALREADY_ATTEMPTED"}:
                raise ReadError(str(error)) from None
            raise ReadError("LIVE_SEND_UNAVAILABLE") from None
        finally:
            self.sending = False
