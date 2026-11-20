# 진행 상태

기준일: 2026-11-20 (Asia/Seoul)

## 최신 작업 — 이름으로 대화방 조회

- **실제 Mac 목록 조회**. 앞선 Codex 실행에서는 목록 조회가 실패했습니다. 이후 사용자가 터미널에서 시작한 로컬 앱으로 목록 조회에 성공했고 요청한 제목과 정확히 일치하는 항목 1건을 확인했습니다. 실행 환경별 결과를 구분해 기록했습니다.
- **실제 본문 읽기와 전송**. 해당 목록 확인에서 본문 읽기와 실제 발송은 각각 0회입니다. 닫힌 창을 직접 여는 동작의 실기기 검증은 남아 있습니다.
- **코드**. 진단에서 기존 대화 제목을 입력하거나 목록에서 고를 수 있습니다. 창 열기를 선택하면 현재 목록에서 대상을 재확인하고 선택한 chat_id로 전경 읽기를 요청합니다. 확인·읽기에 사용한 개인 이름과 대화 내용은 이 기록에서 제외합니다.

- **검증 명령**. `.venv/bin/python -m pytest -q`에서 160개 통과(기존 경고 1개). 마지막 유사 이름 회귀 추가 후 MCP·관측·진단 묶음 56개와 유사 이름 사례 6개 통과. `npm --prefix frontend test` 45개 및 `make build` 성공. 실제 본문 귀속은 kmsg의 창 제목만으로 확인할 수 없어 UI에는 관측 건수만 표시합니다.

## 이전 작업 — 설치본 연결과 대화 선택형 읽기 진단

- **설치 및 MCP 검증**. Homebrew로 kmsg 1.260921.0을 설치했습니다. 설치본의 버전·도움말, 실제 stdio initialize·tools/list·읽기 스키마 검사를 통과했습니다. 이 검사에서는 tool 호출이 없습니다.
- **실제 Mac 읽기**. kmsg status 결과 손쉬운 사용 권한 미허용. 후속 실기기 진단에서 사용자 지정 대상 확인을 시도했으나 목록 조회가 HTTP 409 CATALOG_FAILED로 종료되었습니다. 같은 Mac의 kmsg status로 손쉬운 사용 미허용을 재확인했습니다. 대상 선택·본문 읽기·전송은 모두 0회입니다.
- **코드**. 로컬 앱에서 사용자가 목록을 요청하고 1:1 대상을 확인하면 CLI로 대상을 재검증하고 MCP로 두 번 읽습니다. 결과로 기준선과 신규 관측 건수를 반환합니다. 답장 엔진에는 전달하지 않습니다.
- **실제 전송**. 0회.
- **모의 검증**. `.venv/bin/python -m pytest -q` 149개 통과(기존 TestClient 경고 1개). 프런트엔드 테스트 37개 통과, 최종 설치 안내 조정 후 관련 테스트 9개 재검증, TypeScript 및 Vite 빌드 성공. `make smoke`와 `make smoke-m2` 통과.
- **로컬 앱 검증**. 127.0.0.1:8765에서 새 빌드 HTTP 200 및 인증된 `GET /api/kakao/status`의 installed=true 확인. 실제 목록 조회 시도 결과는 위 실제 Mac 읽기 항목에 기록했습니다.

## 이전 M2 저장·연결 기반 구현 당시 상태

| 구분 | 실제 상태 |
|---|---|
| 코드 구현 | M0/M1 완료, M2 저장·읽기 어댑터/관측·생성문 삭제 UI 구현. M2 전체는 부분 완료 |
| 모의 검증 | Python 131개·UI 18개 통과, build·smoke 2종·브라우저 검증 통과 |
| 실제 macOS Keychain | 공급자 구현, 가짜 backend 테스트 완료. 실제 접근·키 생성 0회 |
| 실제 Mac 카카오톡 읽기 | 미실행. PATH에 kmsg 없음, 계정·권한·대상 미확인 |
| 실제 전송/자동 운영 | 미실행, 0회. 이번 개발 요청에서 실제 사람에게 보내지 않음 |
| GitHub | origin/main 연결 유지. M2 변경의 최종 커밋/동기화는 git log/status 확인 |

## 이번 M2 구현

- `crypto.py`, `keys.py`: AES-256-GCM, schema/table/row/key ID 인증, HKDF 분리 HMAC, 명시적 macOS Keychain 공급자와 가짜 키 공급자. 키 준비는 별도 명령이며 기존 키를 덮어쓰지 않습니다.
- `storage.py`, `storage_setup.py`: SQLite v1→v2 트랜잭션 마이그레이션, 키 참조/검증값, 생성문 암호화 저장·7일 만료·삭제, 기존 attempts/UNKNOWN/중복 기록 보존. 키가 없거나 틀리면 평문으로 fallback하지 않습니다.
- `engine.py`, `api.py`: 발송 전 암호화·키 확인, 실패 시 off/발송 0회, 재시작 본문 복구, 저장 상태 API와 로컬 본문 삭제 API. 생성 중 삭제는 결과를 폐기하고 발송 중 삭제는 거부합니다.
- `kakao/`: 실제 MCP SDK stdio initialize/list/read/close, 읽기 도구 allowlist, schema/대상 검사, timeout/프레임 상한/프로세스 그룹 종료, 원문 진단 제거. 실제 엔진이나 계정에 연결하지 않습니다.
- `observation.py`: catalog 확인/동명·변경 거부, baseline/순서 overlap, 반복 문구와 축소·rollback 보류. 모호성 후 REVALIDATION_REQUIRED 상태로 유지하며 재확인 뒤 reset이 필요합니다. `(me)`를 본인 확인 근거로 쓰지 않습니다.
- React: 저장 방식 안내, 생성문 삭제 확인·결과·실패 표시. 저장 상태 조회가 실패해도 즉시 중지를 사용할 수 있습니다.
- `make smoke-m2`: 합성 암호화 복구/삭제와 실제 SDK↔가짜 서버 handshake/read를 재현합니다.

기본은 metadata-only/mock/off입니다. 암호화는 환경변수의 키 참조로 명시적으로 선택하며, 실제 키 값은 환경변수나 저장소에 넣지 않습니다. 현재 암호화 저장을 엔진에 통합한 대상은 생성문입니다. 일반 메시지/바인딩 원문 수집·보관은 live 통합과 함께 후속 작업입니다.

## M2 실행 기록

| 명령/행동 | 실제 결과 |
|---|---|
| `UV_SYSTEM_CERTS=true ... uv sync` | cryptography 50.0.2, keyring 25.7.0, mcp 1.30.0 설치 및 uv.lock 갱신 |
| 같은 cache/Python 경로의 `uv sync --locked --offline` | 잠금 파일 재현 성공: 50 resolved / 44 checked |
| `.venv/bin/python -m pytest -q` | 131 passed, 1 warning (backend 37 + 계약 7 + security 40 + storage 18 + kakao 29) |
| `npm --prefix frontend test` | 18 tests passed (2 files) |
| `make build` | TypeScript 검사/Vite production build 통과 |
| `make smoke` | 합성 입력→599/600초→모의 발송·중복 방지·본인 취소·중지 통과 |
| `make smoke-m2` | 합성 암호화 재오픈·삭제/시도 보존, 실제 SDK 가짜 MCP 읽기 통과 |
| `.venv/bin/python -m compileall -q backend` | 통과 |
| Uvicorn + 인앱 브라우저 | 합성 입력→600초→발송 1회→AI 표시→생성문 삭제 확인→본문 없음/이력 유지→중지 통과 |
| `git diff --check` | 통과 |

Starlette TestClient의 httpx deprecation warning 1개가 유지됩니다. 실제 Keychain/카카오톡/외부 LLM 호출은 위 테스트에 없습니다. 인수 요구사항 49개 전체 완료를 뜻하지 않습니다.

## M2 독립 리뷰 및 역할

프로젝트 로컬 reply-implement/reply-review를 읽어 적용했고 호스트 목록에 로컬 스킬 3개 등록을 확인했습니다. custom agent TOML 자동 선택은 별도 미검증입니다. 실제 m2_crypto/m2_mcp/frontend/reviewer를 파일 책임별로 위임하고 주 에이전트가 저장소·엔진·API·잠금·문서를 통합했습니다. 전역 Codex 설정은 변경하지 않았습니다.

독립 리뷰에서 발견한 아래 결함은 수정·재현 검증을 마쳤습니다.

1. 삭제 후 모의 전송기 복사본에 본문이 남음 → attempts/echoes의 본문도 삭제·만료 시 제거, 발송 시도 메타데이터 보존.
2. TERM 무시 하위 프로세스가 stdout 대기 중 잔존 → relay의 제한된 종료/kill 보강, 고아 프로세스 종료 확인.
3. 반복 anchor와 축소/rollback snapshot에서 과거 입력을 신규로 재방출 → 축소·위치 모호성을 latch, 재확인 전 이벤트 0개.

최종 독립 리뷰에서 추가 확정 결함은 없었습니다. 최종 생성/삭제 경쟁 회귀는 주 에이전트가 추가 검증했습니다.

## 남은 작업과 현재 실행 상태

M2 잔여: 실제 읽기 catalog 확보·재확인 UI, live 관측과 엔진 연결, 실작성자/본인 직접 답장/bot echo 증거, 서로 다른 프로세스/DB 간 UI dispatcher, 실제 Keychain 및 Mac 읽기 검증. 현재 MCP 관측은 authorship=unknown이며 학습 자료로 승격하지 않습니다.

7일 보존은 가짜 시계 기반이며 실시간 정리 스케줄러는 없습니다. 감사 메타데이터 30일 정리도 tombstone 설계와 함께 남깁니다. M3 개인화·실제 모델, M4 실제 자동 발송/복구, M5 전체 화면/운영은 미완료입니다.

현재 데모 서버는 `KAKAOREPLY_DB_PATH=/private/tmp/kakaoreply-browser-m2.sqlite`, `127.0.0.1:8765`, mode=off로 남겨 두었습니다. 합성 모의 발송 이력 1건과 삭제된 생성문을 확인할 수 있습니다. PID 91575로 시작했으며 다음 작업에서는 포트 점유 상태와 실행 명령을 확인한 뒤 종료/재시작하세요. 브라우저 증거는 `/private/tmp/kakaoreply-m2.jpg`이며 Git에는 포함하지 않습니다.

---

## 이전 M0/M1 실행 기록 (당시 상태)


기준일: 2026-11-20 (Asia/Seoul)

| 구분 | 실제 상태 |
|---|---|
| 명세·개발 지침 | 기존 패키지 보존, 구현 결과에 맞춰 실행·진행 문서 갱신 |
| 코드 구현 | M0/M1 완료. FastAPI + React 합성 시뮬레이터 실행 가능 |
| 모의 검증 | Python 44개, UI/API 10개 통과; API smoke 및 실제 브라우저 수직 흐름 통과 |
| 실제 Mac 카카오톡 읽기 | 미실행. kmsg 미설치(PATH에서 없음), 계정·권한·대상 미확인 |
| 실제 메시지 전송 | 미실행, 0회. 이번 요청에서는 금지 |
| 자동 모드 실기기 검증 | 미실행 |
| GitHub | main Git 초기화, origin 연결, 첫 커밋 8ac9104 업로드 완료; origin/main 추적 설정 |

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


## GitHub 및 최종 실행 상태

- `git init -b main`, `git remote add origin https://github.com/nAhYUN22/kakao-reply-assistant.git` 완료.
- `git ls-remote origin`으로 기존 원격 브랜치가 없는 것을 확인했습니다.
- 구현 커밋 `8ac9104` (`feat: implement M0 M1 synthetic reply simulator`) 생성 후 `git push -u origin main` 성공.
- 후속 문서 커밋은 업로드 결과만 기록합니다. `git log`와 원격 main으로 최종 커밋을 확인할 수 있습니다.
- 소스/문서/합성 fixture만 업로드했으며 `.venv`, `node_modules`, 빌드 산출물, DB, 로그, 비밀 파일은 제외했습니다.
- 최종 서버는 `KAKAOREPLY_DB_PATH=/private/tmp/kakaoreply-browser-m1.sqlite`로 127.0.0.1:8765에서 실행했습니다. 재시작 후 off이며 브라우저 합성 이력은 남고 이전 생성문은 메모리 소멸로 상세 조회 시 없어집니다. 화면이 이전 세션 토큰을 갖고 있으면 새로고침 또는 연결 다시 확인을 사용합니다.
- `git diff --cached --check`에서 기존 Markdown 줄 끝 공백 2건을 발견해 정리 후 통과했습니다.
