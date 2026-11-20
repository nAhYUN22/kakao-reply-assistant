# 다음 Codex 세션 인수인계

기준일: 2026-11-20. **M0/M1 완료, M2 저장·읽기 어댑터·관측 코드/모의 검증 완료. M2 실연결 통합과 실기기 검증은 남아 있습니다.**

## 먼저 읽기

AGENTS → PROGRESS → PLAN → PRODUCT_SPEC/ARCHITECTURE/CONTRACTS → M1_API/M2_CONTRACT → KAKAO_ADAPTER/RELIABILITY/TEST_PLAN. 세부 명세는 현재 구현보다 넓습니다. 기존 M0/M1 완료를 다시 시작하지 마세요.

## 실행

```bash
make install
make test
make build
make smoke
make smoke-m2
make serve
```

Python 3.12 이상, uv, Node 22.12 이상/npm. 현재 `.venv`는 `/private/tmp/kakaoreply-python`의 Python 3.12.13 기반입니다. 임시 런타임이 없어지면 `uv sync --locked`로 재생성하세요. 캐시 `/private/tmp/kakaoreply-uv-cache`와 `UV_SYSTEM_CERTS=true`로 설치·offline 잠금 재현을 확인했습니다. 보안 설정을 낮추지 않습니다.

`make serve`는 빌드 UI를 127.0.0.1:8765로 제공합니다. 기존 데모 서버는 `/private/tmp/kakaoreply-browser-m2.sqlite`, 시작 PID 91575, 모의/off 상태입니다. 포트 점유 시 실행 명령을 확인해 해당 서버만 정상 종료하고 재시작합니다. UI 토큰은 새로고침으로 갱신됩니다.

## 구조와 검증

- `backend/kakaoreply/{domain,adapters,engine,api}.py`: 합성 엔진, 정책, API.
- `{crypto,keys,storage,storage_setup}.py`: AES-GCM, Keychain 공급자, SQLite v2, 명시적 키 준비.
- `kakao/{mcp_client,relay,observation}.py`: 읽기 전용 실제 MCP SDK/가짜 서버 계약, 크기·종료 보호, 대상/관측 파서.
- `frontend/src/`: 기존 합성 UI + 저장 안내/로컬 생성문 삭제.
- `tests/backend`, `tests/security`, `tests/storage`, `tests/kakao`, `tests/test_contracts.py` 및 frontend 테스트.
- `.agents/skills/reply-{implement,review,eval}`는 호스트 목록에서 등록 확인. `.codex/agents` TOML은 구문 검증했으나 자동 선택은 미검증. 이번에는 실제 collaboration 위임을 사용했습니다.

최종 테스트 결과는 PROGRESS를 확인하세요. TypeScript/Vite, M1/M2 smoke, 브라우저 생성문 삭제/이력 보존까지 통과했습니다. 기존 Starlette TestClient httpx 경고 1개가 남습니다. 실제 Keychain·kmsg·카카오톡·외부 모델 접근은 모두 실행하지 않았습니다.

## 유지할 불변조건

- 기본 mock/off/실전송 false. UI/API는 가짜 시간을 명시적으로 전진합니다.
- MockLLM과 FakeTransport만 앱에 연결합니다. 실제 자동 발송은 제품 범위이나 이번 개발에서 실제 사람에게 보내지 않습니다.
- 600초/settle20초/cooldown900초, epoch 취소, 최종 SendGate·고정 AI 표시·한도·durable 단일 시도 유지.
- 불명확 결과는 DELIVERY_UNKNOWN, 자동 재시도 금지. 재시작은 off이며 미완료 후보 취소.
- v2 DB 기본 metadata-only는 본문 비영속. Keychain 선택 시 생성문은 암호화 저장 후 발송하며 실패하면 off. 암호화 DB를 키 없이 다시 열 수 없습니다.
- Keychain 실제 준비는 RUNBOOK의 명시 명령입니다. 이번 세션에서 실행하지 않았습니다. 실제 키·원문을 환경변수·로그·Git·Codex 프롬프트에 넣지 않습니다.
- 생성문 삭제/7일 만료 시 본문과 모의 복사본은 지우고 시도 기록은 남깁니다. 생성 중 삭제는 늦은 결과 폐기, 발송 중 삭제는 409. 발송 회수 기능이 아닙니다.

## 다음 작업 순서

1. M2 읽기 orchestration을 합성 자료로 먼저 통합합니다. `McpReadClient`는 읽기만 제공하며 모의 엔진은 live 이벤트를 거부합니다. 권한·대상 증거를 갖춘 별도 경로를 명시적으로 설계하세요.
2. kmsg MCP에는 catalog 도구가 없으므로 확인된 목록 확보 경로와 대상 재확인 UI를 구현합니다. 숨은 CLI fallback이나 없는 API를 추가하지 마세요. for_kmsg는 절대 실행 파일 경로가 필요하며 설치본 스키마를 다시 확인해야 합니다.
3. `SnapshotScanner`는 최초/reconnect baseline, 공백·stale·모호한 overlap·축소/rollback 뒤 REVALIDATION_REQUIRED입니다. 사용자 재확인 후 reset하며 다음 관측도 baseline입니다. `(me)`는 본인 근거가 아니며 authorship=unknown을 학습에 쓰지 않습니다. 실제 직접 답장/bot echo 증거가 남습니다.
4. 같은 DB flock 및 공유 MCP dispatcher는 구현했지만, 서로 다른 DB/클라이언트 프로세스 사이의 전역 UI 잠금은 통합되지 않았습니다. 실연결 전에 처리하세요.
5. 실시간 시계/절전 복구·본문 보존 정리와 감사30일/tombstone 설계를 추가합니다. 가짜 시계 통과를 실시간 검증으로 보고하지 마세요.
6. 실제 Keychain·Mac 읽기는 별도 검증하며 계정/권한/대상 범위를 확인합니다. kmsg는 현재 PATH에 없습니다. 실제 Mac 준비가 안 되어도 합성 구현은 계속합니다.
7. M3 개인화·사실/말투 분리·실제 모델, M4 자동 전송/복구, M5 운영은 후속입니다. 실전송 테스트는 대상·내용·횟수가 승인된 경우만 가능합니다.

## GitHub

`main`은 사용자 지정 [GitHub](https://github.com/nAhYUN22/kakao-reply-assistant)에 연결되어 있으며 origin/main을 추적합니다. 기존 M0/M1 커밋은 8ac9104/8fb53ae입니다. M2 최신 커밋과 원격 반영은 `git log -3 --oneline`, `git status -sb`로 확인하세요. 강제 push하지 않습니다. 실제 대화·키·DB·빌드 산출물은 커밋하지 않습니다.
