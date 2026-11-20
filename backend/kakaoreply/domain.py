"""Pure validation and time policy; no transport or API dependencies."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import unicodedata
from zoneinfo import ZoneInfo

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
SUFFIX = "— 부재중 AI 답장"
BINDING_ID = "synthetic-partner"
ACTIVE = {"PENDING", "GENERATING", "READY"}


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


VALIDATORS = {
    name: Draft202012Validator(
        json.loads((ROOT / "schemas" / f"{name}.schema.json").read_text()),
        format_checker=FormatChecker(),
    ) for name in ("app-config", "message-event", "reply-decision")
}


def validate(name: str, value: dict) -> None:
    # Never propagate jsonschema's exception: it includes the original data.
    if not VALIDATORS[name].is_valid(value):
        raise ValueError("INVALID_" + name.upper().replace("-", "_"))


def default_config() -> dict:
    result = json.loads((ROOT / "examples/app-config.example.json").read_text())
    result.pop("$schema", None)
    return result


def checked_config(value: dict) -> dict:
    validate("app-config", value)
    if value["timezone"] not in {"Asia/Seoul", "UTC"}:
        raise ValueError("UNSUPPORTED_TIMEZONE")
    if value["reply_delay"] >= value["max_incoming_age"]:
        raise ValueError("INVALID_DELAY")
    if any(w["start"] == w["end"] for w in value["active_windows"]):
        raise ValueError("EMPTY_WINDOW")
    if value["transport"] != "mock" or value["provider"]["kind"] != "mock" or value["live_send_enabled"]:
        raise ValueError("M1_MOCK_ONLY")
    return deepcopy(value)


def in_window(now: datetime, config: dict) -> bool:
    local = now.astimezone(ZoneInfo(config["timezone"]))
    minute = local.hour * 60 + local.minute
    day = local.isoweekday()
    previous = (local - timedelta(days=1)).isoweekday()
    for window in config["active_windows"]:
        start, end = (int(x[:2]) * 60 + int(x[3:]) for x in (window["start"], window["end"]))
        if start < end and day in window["days"] and start <= minute < end:
            return True
        if start > end and ((day in window["days"] and minute >= start) or
                            (previous in window["days"] and minute < end)):
            return True
    return False


def final_text(decision: dict, max_chars: int, valid_fact_ids: set[str] | None = None) -> str:
    validate("reply-decision", decision)
    if not set(decision["used_fact_ids"]).issubset(valid_fact_ids or set()):
        raise ValueError("INVALID_FACT")
    if decision["action"] != "reply":
        raise ValueError("NOT_REPLY")
    body = unicodedata.normalize("NFC", decision["reply_text"]).strip()
    if not body:
        raise ValueError("EMPTY_REPLY")
    text = body + "\n" + SUFFIX
    if len(text) > max_chars:
        raise ValueError("MAX_CHARS")
    return text
