# 진행 상태

기준일: 2026-11-20 (Asia/Seoul)

| 구분 | 실제 상태 |
|---|---|
| 명세·개발 지침 | 기존 패키지 보존, 구현 결과에 맞춰 실행·진행 문서 갱신 |
| 코드 구현 | M0/M1 완료. FastAPI + React 합성 시뮬레이터 실행 가능 |
| 모의 검증 | Python 44개, UI/API 10개 통과; API smoke 및 실제 브라우저 수직 흐름 통과 |
| 실제 Mac 카카오톡 읽기 | 미실행. kmsg 미설치(PATH에서 없음), 계정·권한·대상 미확인 |
| 실제 메시지 전송 | 미실행, 0회. 이번 요청에서는 금지 |
| 자동 모드 실기기 검증 | 미실행 |
| GitHub | main Git 초기화, origin 연결 및 빈 원격 확인. 업로드 결과는 아래 기록 |

## 구현한 동작

- `backend/kakaoreply/domain.py`: 기존 JSON Schema/기본값 검증, 시간 구간·NFC 길이·모델 응답 계약.
- `adapters.py`: MockClock, MockLLM, FakeTransport. 실제 네트워크·shell·카카오톡 호출 경로 없음.
- `engine.py`: 첫 미응답 600초, settle 20초, 본인 cooldown 900초, epoch 기반 생성 결과 폐기, 최종 전송 조건, 고정 AI 표시, 한도, 중지와 정확한 상대 `/봇중지`.
- `storage.py`: SQLite v1 metadata journal, 중복 이벤트 기록, 트랜잭션 기반 작업당 단일 전송 시도, OS 잠금, 재시작 시 취소/DELIVERY_UNKNOWN 복구. 불명확 작업은 모드 재시작으로 우회하지 못함.
- `api.py`: 명시적 세션 토큰, Host/Origin/교차 사이트 검사, 오류 원문 제거, 빌드된 UI 제공.
- `frontend/`: 모의 자동/초안 시작, 합성 메시지, 시간 이동, 즉시 중지, 이력·상세, 오류·로딩·빈 상태. 늦은 응답이 중지 상태를 덮지 않음.
- `scripts/smoke.py`, `Makefile`: 재현 가능한 실행과 통합 검증.

원문·생성문은 메모리에만 보관합니다. SQLite·WAL에는 본문을 쓰지 않습니다. **민감 데이터 암호화 및 Keychain 구현 완료를 뜻하지 않습니다.** 재시작 후 이력 메타데이터는 남고 상세 생성문은 null입니다.

## 환경 및 의존성

- macOS 26.5.2 (25F84), Codex CLI 0.152.1, Node 26.5.0, npm 11.17.0.
- 기본 shell python3는 3.10.20이므로 별도 Python 3.12.13과 프로젝트 `.venv`를 준비했습니다.
- FastAPI 0.165.0, Pydantic 2.14.4, Uvicorn 0.54.0, pytest 9.2.0, Vite 7.3.8. 정확한 모든 버전은 `uv.lock`, `frontend/package-lock.json`에 고정.
- 의존성 다운로드와 로컬 bind는 환경의 정상 승인 절차를 사용했습니다. TLS는 검증을 유지하고 시스템 인증서 저장소로 설치했습니다. 전역 보안·Codex 설정은 변경하지 않았습니다.

## 실제 실행한 검증

| 명령/행동 | 결과 |
|---|---|
| `uv sync --python 3.12` (임시 cache/Python 경로, 시스템 인증서 사용) | Python 및 29개 패키지 설치, uv.lock 생성 |
| `uv sync --locked --offline` (같은 cache/Python 경로) | 잠금 파일 재현 검증 통과 |
| `npm install --cache /private/tmp/kakaoreply-npm-cache` (frontend) | 설치·잠금 파일 생성, 설치 시 audit 0 vulnerabilities |
| `.venv/bin/python -m pytest -q` | 44 passed; 백엔드 37 + 독립 공개 계약 7 |
| `npm test` (frontend) | 2개 파일, 10 tests passed |
| `npm run build` (frontend) | TypeScript 검사 + 프로덕션 빌드 통과 |
| `.venv/bin/python scripts/smoke.py` | 격리 DB에서 599/600초 경계, 모의 1회 발송, AI 표시, 중복 방지, 본인 취소, 중지 통과 |
| `.venv/bin/python -m compileall -q backend` | 통과 |
| 스킬 `quick_validate.py` 3회 및 tomllib 3개 | 모두 통과 |
| Uvicorn `127.0.0.1:8765` + 인앱 브라우저 | 실제 UI 시작→입력→10분 이동→모의 발송 1회→상세 AI 표시→다음 입력 본인 취소→즉시 중지 확인 |

Starlette가 TestClient의 httpx 사용 중단 예정 경고 1개를 표시합니다. 현재 검증은 통과하며 향후 호환성 정리가 필요합니다. npm 초기 설치에서는 esbuild postinstall 승인 안내가 있었으나 TypeScript/Vite 빌드는 정상 통과했습니다.

## 실제 사용한 AI 작업 구성

- 프로젝트 로컬 스킬 3개, custom agent TOML 3개를 문서 템플릿에서 생성·구문 검증.
- `reply-implement`, `reply-review`, `reply-eval`을 명시적으로 읽어 적용했습니다. 자동 발견은 이번 기존 세션에서 검증하지 않았습니다.
- backend/frontend/reviewer를 실제 병렬 실행했습니다. 파일 책임을 분리하고 공통 API·잠금 파일·문서는 주 에이전트가 관리했습니다.
- 독립 리뷰가 연속 메시지로 인한 무기한 PENDING 결함을 재현했습니다. due 이전에도 만료를 검사하도록 수정하고 회귀 테스트 통과를 확인했습니다. UI 이유 코드 한국어 표시도 수정했습니다.
- UI 테스트 중 Node 26 global localStorage 차이로 발생한 1건 실패는 브라우저 저장소 쓰기 spy 검증으로 수정했습니다. JSON 파싱 오류의 원문 노출 경로도 차단했습니다.

## 미완료 및 다음 작업

M2–M5 전체는 완료하지 않았습니다. 실제 MCP/CLI, live SendGate/GUI 결과 확인, 암호화·Keychain·보존/삭제, 실시간 타이머·절전 복구, 실제 모델·말투·사실 메모리·전체 설정 화면이 남습니다. 현재 MockLLM은 결정적인 합성 응답이며 실제 말투/생성 품질을 검증하지 않았습니다.

다음 세션은 HANDOFF를 읽고 M2를 진행합니다. 실제 전송은 대상·내용·횟수의 별도 승인 범위가 있을 때만 검증합니다. 현재 인수 시나리오 49개 전부를 통과했다고 보고하지 않습니다.
