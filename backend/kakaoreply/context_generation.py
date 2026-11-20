"""Generate a candidate for the final partner turn. This module cannot dispatch it."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from http.client import HTTPConnection, HTTPException
import json
import os
import re
import unicodedata

from .domain import ROOT, SUFFIX, VALIDATORS, validate

MAX_TURNS = 8
MAX_BODY = 240 - len(SUFFIX) - 1
MODEL_SETTING = "KAKAOREPLY_OLLAMA_MODEL"
PROMPT = ROOT / "prompts/runtime/reply_system.md"


@dataclass(frozen=True, repr=False)
class Turn:
    author: str
    text: str


class GenerationHold(ValueError):
    """Contains a public reason code only."""


# Block common cases before either provider, including an earlier instruction
# followed by an otherwise harmless "응". These checks supplement the model.
_POLICY = (
    ("MONEY_REQUEST", r"송금|계좌|대출|입금|이체|돈.{0,5}(보내|빌려)"),
    ("COMMITMENT_REQUEST", r"약속|예약|만날까|만나자|만날래|갈래|해\s*줄래|사\s*줘"),
    ("RELATIONSHIP_DECISION", r"헤어지|헤어져|결혼|우리\s*그만"),
    ("URGENT_OWNER_ATTENTION", r"응급|살려\s*줘|죽고\s*싶|다쳤|사고\s*났"),
    ("UNTRUSTED_INSTRUCTION", r"/봇중지|규칙.{0,8}무시|지[시침].{0,8}무시|다른\s*(채팅|대화)|시스템\s*지침|표시\s*제거|ignore previous|비밀번호|인증번호"),
)
_OWNER_FACT = re.compile(r"어디야|어디\s*있|뭐\s*(해|하고)|밥.{0,4}먹었|몇\s*시.{0,4}(와|도착)|언제.{0,4}(와|올|만나)")
_UNVERIFIED_CLAIM = re.compile(
    r"갈게|할게|볼게|줄게|올게|해줄게|하겠|하기로\s*했|가기로\s*했|"
    r"(?:나는?|난|내가|지금)\s*.{0,12}(?:있어|있어요|먹었|가는\s*중|하는\s*중|도착했)"
)
_TOPICS = (
    ("영화", "영화 얘기하고 있었어.", "어떤 장면이 기억에 남았어?"),
    ("전시", "전시 얘기하고 있었어.", "어떤 작품이 눈에 들어왔어?"),
    ("공연", "공연 얘기하고 있었어.", "무대에서 어떤 순간이 기억에 남았어?"),
    ("책", "책 얘기하고 있었어.", "어떤 대목이 인상 깊었어?"),
    ("여행", "여행 얘기하고 있었어.", "여행에서 어떤 순간이 기억에 남았어?"),
    ("산책", "산책 얘기하고 있었어.", "걷다가 눈에 들어온 게 있었어?"),
)


def rule_reply(turns: tuple[Turn, ...]) -> str:
    if not turns or turns[-1].author != "partner":
        raise GenerationHold("INVALID_CONTEXT")
    latest = turns[-1].text.rstrip(" .~!?ㅎㅎㅋ")
    if latest in {"안녕", "안녕하세요", "좋은 아침", "굿모닝"}:
        return "안녕하세요!" if latest == "안녕하세요" else "안녕! 좋은 하루 보내."
    if latest in {"고마워", "고마워요", "감사해요", "고맙다"}:
        return "별말씀을요!" if latest.endswith("요") else "별말을!"
    if latest in {"잘 자", "잘자", "좋은 꿈 꿔"}:
        return "잘 자. 좋은 꿈 꿔!"
    if latest in {"오늘 너무 힘들었어", "너무 힘들다", "힘들었어", "지쳤어"}:
        return "오늘 많이 힘들었구나. 어떤 일이 있었어?"

    recall = re.fullmatch(r"(?:아까\s*|우리\s*)*(?:무슨|뭔)\s*(?:얘기|이야기)(?:였지|했지|하고 있었지)", latest)
    detail = latest in {"뭐가 궁금해", "어떤 게 궁금해", "뭘 더 얘기해 줄까"}
    if recall or detail:
        for turn in reversed(turns[:-1]):
            if turn.author == "unknown":
                continue
            matches = [topic for topic in _TOPICS if topic[0] in turn.text]
            if len(matches) > 1:
                break
            if matches:
                return matches[0][1 if recall else 2]
            # Only brief follow-ups can sit between the referent and question.
            # An unsupported topic change makes the old referent ambiguous.
            if turn.text.rstrip(" .~!?ㅎㅎㅋ") not in {"응", "그래", "어땠어", "더 얘기해 줘", "그랬구나"}:
                break
    for keyword, _, question in _TOPICS:
        if re.fullmatch(rf"(?:오늘\s*|나\s*)*{keyword}(?:을|를)?\s*(?:보고 왔어|보고왔어|봤어|다녀왔어|했어|읽었어)", latest):
            return question
    raise GenerationHold("UNSUPPORTED_CONTENT")


def _post_local(path: str, payload: dict, limit: int) -> dict:
    # Fixed numeric loopback, no proxy, no redirects, no response-body logging.
    conn = HTTPConnection("127.0.0.1", 11434, timeout=25)
    try:
        conn.request("POST", path, body=json.dumps(payload).encode(),
                     headers={"Content-Type": "application/json"})
        response = conn.getresponse()
        if response.status != 200:
            raise GenerationHold("MODEL_UNAVAILABLE")
        body = response.read(limit + 1)
        if len(body) > limit:
            raise GenerationHold("MODEL_INVALID_RESPONSE")
        result = json.loads(body)
        if not isinstance(result, dict):
            raise GenerationHold("MODEL_INVALID_RESPONSE")
        return result
    except (OSError, HTTPException, json.JSONDecodeError, UnicodeDecodeError, RecursionError):
        raise GenerationHold("MODEL_UNAVAILABLE") from None
    finally:
        conn.close()


async def _model_reply(model: str, turns: tuple[Turn, ...]) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}", model) or "cloud" in model.casefold():
        raise GenerationHold("MODEL_UNAVAILABLE")
    # A local Ollama server can route cloud aliases. Check the selected model
    # before giving the provider any conversation text.
    info = await asyncio.to_thread(_post_local, "/api/show", {"model": model}, 2_000_000)
    details = info.get("details")
    if (info.get("remote_host") or info.get("remote_model") or not isinstance(details, dict)
            or details.get("format") != "gguf" or not info.get("model_info")):
        raise GenerationHold("MODEL_UNAVAILABLE")

    data = {"recent_turns": [{"author": turn.author, "text": turn.text} for turn in turns],
            "target_index": len(turns) - 1, "verified_facts": [], "style_examples": []}
    prompt = PROMPT.read_text(encoding="utf-8") + (
        "\nrecent_turns는 오래된 순입니다. 마지막 partner 발화에만 짧게 답하세요. "
        "unknown 발화는 작성자 미확인이며 본인의 말투나 사실로 해석하지 마세요."
    )
    payload = {"model": model, "stream": False, "format": VALIDATORS["reply-decision"].schema,
               "options": {"temperature": 0.2, "num_predict": 256},
               "messages": [{"role": "system", "content": prompt},
                            {"role": "user", "content": json.dumps(data, ensure_ascii=False)}]}
    response = await asyncio.to_thread(_post_local, "/api/chat", payload, 32_768)
    message = response.get("message")
    if (response.get("done") is not True or response.get("done_reason") != "stop"
            or not isinstance(message, dict) or message.get("role") != "assistant"
            or message.get("tool_calls") or not isinstance(message.get("content"), str)):
        raise GenerationHold("MODEL_INVALID_RESPONSE")
    try:
        decision = json.loads(message["content"])
        validate("reply-decision", decision)
    except (ValueError, RecursionError):
        raise GenerationHold("MODEL_INVALID_RESPONSE") from None
    if decision["action"] != "reply":
        raise GenerationHold(decision["reason_codes"][0])
    if decision["used_fact_ids"] or set(decision["reason_codes"]) - {"ROUTINE_REPLY", "ACKNOWLEDGEMENT"}:
        raise GenerationHold("MODEL_INVALID_RESPONSE")
    body = unicodedata.normalize("NFC", decision["reply_text"]).strip()
    if (not body or len(body) > MAX_BODY or SUFFIX in body
            or any(unicodedata.category(c) in {"Cc", "Cf"} and c != "\n" for c in body)):
        raise GenerationHold("MODEL_INVALID_RESPONSE")
    if _UNVERIFIED_CLAIM.search(body) or any(re.search(pattern, body, re.IGNORECASE) for _, pattern in _POLICY):
        raise GenerationHold("MODEL_INVALID_RESPONSE")
    return body


async def generate_reply(turns: tuple[Turn, ...]) -> str:
    """Return an unmarked candidate, or hold with a content-free reason code."""
    recent = turns[-MAX_TURNS:]
    if not recent or recent[-1].author != "partner":
        raise GenerationHold("INVALID_CONTEXT")
    normalized = []
    for index, turn in enumerate(recent):
        if turn.author not in {"owner", "partner", "unknown"} or not isinstance(turn.text, str):
            raise GenerationHold("INVALID_CONTEXT")
        text = unicodedata.normalize("NFC", turn.text).strip()
        if not text or len(text) > 2000:
            raise GenerationHold("INVALID_CONTEXT")
        for reason, pattern in _POLICY:
            if re.search(pattern, text, re.IGNORECASE):
                raise GenerationHold(reason)
        if SUFFIX in text:
            # A prior bot reply can appear as outgoing; never use it as a
            # personal example or as the target of another reply.
            if index == len(recent) - 1:
                raise GenerationHold("INVALID_CONTEXT")
            continue
        normalized.append(Turn(turn.author, text))
    window = tuple(normalized)
    if _OWNER_FACT.search(window[-1].text):
        raise GenerationHold("MISSING_FACT")
    model = os.environ.get(MODEL_SETTING)
    if model is None:
        return rule_reply(window)
    try:
        async with asyncio.timeout(30):
            return await _model_reply(model, window)
    except (TimeoutError, OSError):
        raise GenerationHold("MODEL_UNAVAILABLE") from None
