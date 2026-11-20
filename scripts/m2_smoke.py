"""Synthetic encrypted recovery plus a real MCP stdio handshake with a fake server."""
import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from mcp import StdioServerParameters
from kakaoreply.crypto import DataCipher
from kakaoreply.engine import Engine
from kakaoreply.keys import EphemeralKeyProvider
from kakaoreply.kakao import BindingVerifier, McpReadClient, SnapshotScanner
from kakaoreply.storage import Journal


async def main():
    with TemporaryDirectory(prefix="kakaoreply-m2-") as temp:
        provider = EphemeralKeyProvider()
        cipher = DataCipher(provider.provision("synthetic-m2"), "synthetic-m2")
        path = str(Path(temp) / "encrypted.sqlite")
        engine = Engine(Journal(path, cipher=cipher))
        await engine.start("auto")
        await engine.message("합성 산책 이야기")
        await engine.advance(600)
        job_id = next(iter(engine.jobs))
        reply = engine.detail(job_id)["reply_text"]
        assert reply and reply not in "\n".join(engine.journal.db.iterdump())
        engine.close()
        recovered = Engine(Journal(path, cipher=cipher))
        assert recovered.state()["mode"] == "off"
        assert recovered.detail(job_id)["reply_text"] == reply
        await recovered.delete_reply(job_id)
        assert recovered.detail(job_id)["reply_text"] is None
        assert len(recovered.journal.attempts()) == 1
        recovered.close()
        print("PASS: 합성 키로 암호화 저장 → 동일 키 재오픈 → 생성문 복구 → 본문 삭제·시도 이력 보존")

        verifier = BindingVerifier()
        binding = verifier.bind({"count": 1, "chats": [{"chat_id": "chat_synthetic", "title": "Synthetic partner"}]},
                                "chat_synthetic", one_to_one_confirmed=True)
        client = McpReadClient(StdioServerParameters(command=sys.executable,
                              args=[str(ROOT / "tests/kakao/fake_mcp_server.py")]))
        async with client.connect():
            snapshot = await client.read_snapshot(binding)
            observation = SnapshotScanner(binding).scan(snapshot, observed_at=datetime(2026, 11, 20, tzinfo=timezone.utc))
            assert observation.status == "BASELINE" and not observation.events
        print("PASS: 실제 MCP SDK stdio initialize → tools/list → 가짜 kmsg_read → 기준선 관측 → 종료")
        print("실제 Keychain 접근 0회 / 실제 카카오톡 읽기 0회 / 실제 메시지 전송 0회")


if __name__ == "__main__":
    asyncio.run(main())
