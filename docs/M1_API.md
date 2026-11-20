# M1 모의 실행 API 계약

2026-11-20 주 에이전트가 소유하는 통합 계약입니다. 실제 카카오 연결과 외부 LLM은 사용하지 않습니다.

- FastAPI `127.0.0.1:8765`, Vite `127.0.0.1:5173`에서 `/api` proxy. 빌드 UI는 FastAPI에서도 제공합니다.
- JSON API, 오류 `{detail: string}`. 클라이언트 입력 본문을 validation 오류에 재출력하지 않습니다.
- `GET /api/session` → `{token: string}`; 허용 Host/Origin 검사 후 발급, 모든 다른 API에 `X-Session-Token` 필요(health 제외). 토큰은 브라우저 메모리만 사용합니다.
- `GET /api/health` → `{status: "ok", transport: "mock", version: "0.1.0"}`.
- `GET /api/state` → 아래 State. 기본값 mock/off/실전송 false, 가짜 시계 `2026-11-20T03:00:00Z`.
- `POST /api/simulator/start` body `{mode: "auto" | "draft"}` → State. 합성 전용 세션, 명시적인 데모 활성 시간 00:00–12:00 및 12:00–00:00 모든 요일. 기본 600초 지연을 유지합니다.
- `POST /api/simulator/messages` body `{text: string, origin: "partner" | "owner" | "unknown", event_id?: string, binding_id?: string}` → State. 기본 대상 `synthetic-partner`.
- `POST /api/simulator/advance` body `{seconds: number}` (0–86400 유한값) → State. 가짜 시간 전진 후 due 작업 처리.
- `POST /api/runtime/pause` body `{}` → State. 모드 off 및 아직 발송하지 않은 작업 취소.
- `GET /api/jobs/{job_id}` → Job + `{reply_text: string | null}`. 본문은 이 명시적 상세 API에서만 조회.

```typescript
type Job = {
  job_id: string; state: string; reason_codes: string[];
  due_at: string | null; created_at: string; updated_at: string;
  incoming_count: number; attempt_count: number;
};
type State = {
  transport: 'mock'; mode: 'off' | 'draft' | 'auto';
  live_send_enabled: false; now: string; binding_id: 'synthetic-partner';
  reply_delay: number; settle: number; human_cooldown: number;
  pending_due_at: string | null; paused_reason: string | null;
  simulated_send_count: number; jobs: Job[];
};
```

Job 상태는 ARCHITECTURE의 상태 목록을 사용합니다. 초안은 READY이며 전송하지 않습니다. 모의 확인은 CONFIRMED_LOCAL이며 실제 수신/읽음을 뜻하지 않습니다. 중복 이벤트는 같은 ID로 멱등 처리합니다. 원문은 상태 요약·일반 로그에 넣지 않습니다. M1 데이터는 합성 전용이며 SQLite 영속 outbox/복구 범위는 구현 증거로 별도 기록합니다.
