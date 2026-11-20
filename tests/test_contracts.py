"""Published fixtures remain the contract, independently of implementation models."""
import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads((ROOT / path).read_text())


@pytest.mark.parametrize("schema,fixture", [
    ("app-config", "app-config.example"),
    ("message-event", "message-events.synthetic"),
    ("reply-decision", "reply-decisions.synthetic"),
])
def test_published_contracts(schema, fixture):
    definition = read(f"schemas/{schema}.schema.json")
    Draft202012Validator.check_schema(definition)
    validator = Draft202012Validator(definition, format_checker=FormatChecker())
    data = read(f"examples/{fixture}.json")
    for item in data if isinstance(data, list) else [data]:
        validator.validate(item)


def test_mock_cannot_enable_live_send():
    config = read("examples/app-config.example.json")
    config.update(mode="auto", live_send_enabled=True)
    with pytest.raises(ValidationError):
        Draft202012Validator(read("schemas/app-config.schema.json")).validate(config)


@pytest.mark.parametrize("mutation", [
    {"recipient": "another-chat"}, {"action": "send"},
    {"action": "hold", "reply_text": "must not send"},
])
def test_model_cannot_expand_send_contract(mutation):
    decision = {"action": "reply", "reply_text": "합성 답장", "reason_codes": ["ROUTINE_REPLY"], "used_fact_ids": []}
    decision = copy.deepcopy(decision) | mutation
    with pytest.raises(ValidationError):
        Draft202012Validator(read("schemas/reply-decision.schema.json")).validate(decision)
