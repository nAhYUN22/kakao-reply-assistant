"""Run a complete synthetic API flow with an isolated, temporary database."""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from fastapi.testclient import TestClient
from kakaoreply.api import create_app


def main():
    with TemporaryDirectory(prefix="kakaoreply-smoke-") as temp:
        with TestClient(create_app(db_path=str(Path(temp) / "mock.sqlite")), base_url="http://127.0.0.1:8765") as client:
            session = client.get("/api/session")
            session.raise_for_status()
            client.headers["X-Session-Token"] = session.json()["token"]

            def post(path, body):
                response = client.post(path, json=body)
                response.raise_for_status()
                return response.json()

            initial = client.get("/api/state").json()
            assert initial["mode"] == "off" and initial["live_send_enabled"] is False
            post("/api/simulator/start", {"mode": "auto"})
            pending = post("/api/simulator/messages", {"text": "오늘 산책했어", "origin": "partner", "event_id": "smoke-partner-1"})
            assert pending["pending_due_at"] is not None
            before = post("/api/simulator/advance", {"seconds": 599})
            assert before["simulated_send_count"] == 0
            sent = post("/api/simulator/advance", {"seconds": 1})
            assert sent["simulated_send_count"] == 1
            job = next(job for job in sent["jobs"] if job["state"] == "CONFIRMED_LOCAL")
            detail = client.get(f"/api/jobs/{job['job_id']}").json()
            assert detail["reply_text"].endswith("— 부재중 AI 답장")
            repeated = post("/api/simulator/messages", {"text": "오늘 산책했어", "origin": "partner", "event_id": "smoke-partner-1"})
            assert repeated["simulated_send_count"] == 1
            post("/api/simulator/messages", {"text": "합성 추가 메시지", "origin": "partner"})
            canceled = post("/api/simulator/messages", {"text": "직접 확인했어", "origin": "owner"})
            assert any(job["state"] == "CANCELED_HUMAN" for job in canceled["jobs"])
            stopped = post("/api/runtime/pause", {})
            assert stopped["mode"] == "off"
            print("PASS: 합성 입력 → 599초 대기 → 600초 생성/모의 발송 → 이력/AI 표시")
            print("PASS: 동일 이벤트 중복 방지 · 직접 답장 취소 · 즉시 중지")
            print("실제 카카오톡 읽기 0회 / 실제 발송 0회")


if __name__ == "__main__":
    main()
