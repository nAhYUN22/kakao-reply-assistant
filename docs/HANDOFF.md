# 다음 Codex 세션 인수인계

기준일: 2026-11-20. **M0/M1 완료, M2 저장·읽기 어댑터·관측 코드/모의 검증 완료. M2 실연결 통합과 실기기 검증은 남아 있습니다.**

## 최신 인수인계 — Mac 읽기 진단

이 Mac에는 kmsg 1.260921.0과 Mac 카카오톡이 설치되어 있습니다. 설치본 MCP 초기화·도구 조회는 성공했고 손쉬운 사용 권한은 미허용으로 확인했습니다. 다음 검증은 RUNBOOK 3절의 로컬 진단 화면에서 사용자가 대상 1:1 대화를 지정한 뒤 진행합니다. 대화명이나 원문을 공유할 필요가 없습니다. 아래 이전 계획의 catalog·대상 확인 UI와 진단 전용 사용자별 잠금은 구현했습니다. 상시 관측·답장 엔진 연동·본인/봇 작성자 판별·실발송은 후속입니다.

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

`make serve`는 빌드 UI를 127.0.0.1:8765로 제공합니다. 기존 데모 서버는 `/private/tmp/kakaoreply-browser-m2.sqlite`, 모의/off 상태입니다. 포트 점유 시 실행 명령을 확인해 해당 서버만 정상 종료하고 재시작합니다. UI 토큰은 새로고침으로 갱신됩니다.

## 구조와 검증

- `backend/kakaoreply/{domain,adapters,engine,api}.py`: 합성 엔진, 정책, API.
- `{crypto,keys,storage,storage_setup}.py`: AES-GCM, Keychain 공급자, SQLite v2, 명시적 키 준비.
- `kakao/{mcp_client,relay,observation}.py`: 읽기 전용 실제 MCP SDK/가짜 서버 계약, 크기·종료 보호, 대상/관측 파서.
- `frontend/src/`: 기존 합성 UI + 저장 안내/로컬 생성문 삭제.
- `tests/backend`, `tests/security`, `tests/storage`, `tests/kakao`, `tests/test_contracts.py` 및 frontend 테스트.
- `.agents/skills/reply-{implement,review,eval}`는 호스트 목록에서 등록 확인. `.codex/agents` TOML은 구문 검증했으나 자동 선택은 미검증. 이번에는 실제 collaboration 위임을 사용했습니다.

최종 테스트 결과는 PROGRESS를 확인하세요. TypeScript/Vite, M1/M2 smoke, 브라우저 생성문 삭제/이력 보존까지 통과했습니다. 기존 Starlette TestClient httpx 경고 1개가 남습니다. 설치본 kmsg의 MCP 연결과 손쉬운 사용 권한 상태를 확인했습니다. 대상 대화 읽기·실제 Keychain·외부 모델 접근은 미실행입니다.

## 유지할 불변조건

- 기본 mock/off/실전송 false. UI/API는 가짜 시간을 명시적으로 전진합니다.
- MockLLM과 FakeTransport만 앱에 연결합니다. 실제 자동 발송은 제품 범위이나 이번 개발에서 실제 사람에게 보내지 않습니다.
- 600초/settle20초/cooldown900초, epoch 취소, 최종 SendGate·고정 AI 표시·한도·durable 단일 시도 유지.
- 불명확 결과는 DELIVERY_UNKNOWN, 자동 재시도 금지. 재시작은 off이며 미완료 후보 취소.
- v2 DB 기본 metadata-only는 본문 비영속. Keychain 선택 시 생성문은 암호화 저장 후 발송하며 실패하면 off. 암호화 DB를 키 없이 다시 열 수 없습니다.
- Keychain 실제 준비는 RUNBOOK의 명시 명령입니다. 이번 세션에서 실행하지 않았습니다. 실제 키·원문을 환경변수·로그·Git·Codex 프롬프트에 넣지 않습니다.
- 생성문 삭제/7일 만료 시 본문과 모의 복사본은 지우고 시도 기록은 남깁니다. 생성 중 삭제는 늦은 결과 폐기, 발송 중 삭제는 409. 발송 회수 기능이 아닙니다.

## 남은 작업 순서

1. 사용자가 손쉬운 사용 권한을 허용하고 로그인·1:1 창 준비를 마친 뒤 로컬 앱의 읽기 진단을 실행합니다. 기록에는 확인 결과와 건수만 남깁니다. 실제 전송은 0회로 유지합니다.
2. 실시간 관측·재시작·절전 복구를 진단의 프로세스 잠금 및 대상 확인 절차와 통합합니다. 작성자·직접 답장·봇 echo 근거가 있어야 엔진에서 실제 이벤트를 처리할 수 있습니다.
3. 실제 Keychain 검증과 실시간 보존 정리·감사 기록 만료, M3 개인화·모델, M4 자동 전송/복구, M5 운영을 진행합니다.

## GitHub

`main`은 사용자 지정 [GitHub](https://github.com/nAhYUN22/kakao-reply-assistant)에 연결되어 있으며 origin/main을 추적합니다. 기존 M0/M1 커밋은 8ac9104/8fb53ae입니다. M2 최신 커밋과 원격 반영은 `git log -3 --oneline`, `git status -sb`로 확인하세요. 강제 push하지 않습니다. 실제 대화·키·DB·빌드 산출물은 커밋하지 않습니다.
