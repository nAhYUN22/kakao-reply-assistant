# KakaoReply

Mac용 카카오톡 대리 답장 앱을 개발하고 있습니다. 현재 **M0/M1 합성 시뮬레이터와 M2 저장·읽기 어댑터의 코드/모의 검증**을 구현했습니다.  FastAPI와 React UI에서 합성 메시지 입력 → 대기 → MockLLM 후보 생성 → 모의 발송 → 이력 조회를 실행할 수 있습니다. 실제 대화 읽기는 아래의 별도 진단에서 실행합니다.

## 실행

Python 3.12 이상, uv, Node 22.12 이상과 npm이 필요합니다. 저장소 루트에서 실행하세요.

```bash
make install
make build
make serve
```

[로컬 앱 열기](http://127.0.0.1:8765) 후 **모의 자동 시작**을 선택하고 합성 상대 메시지를 입력하세요. 가짜 시간을 600초 진행하면 모의 답장과 이력을 확인할 수 있습니다. 직접 답장을 입력하거나 즉시 중지하면 아직 발송하지 않은 작업이 취소됩니다. 실제 시간의 흐름으로 시뮬레이터 시간이 진행되지는 않습니다.

화면 개발 중에는 `make serve`와 별도 터미널의 `make dev-ui`를 실행하고 [개발 UI](http://127.0.0.1:5173)를 엽니다.

```bash
make test
make smoke
make smoke-m2
```

초기 모드는 `mock/off`, 실제 전송은 항상 비활성화입니다. 합성 문장만 입력하세요. 기본 저장은 SQLite 작업·시도 메타데이터와 메모리 본문입니다. Keychain을 명시적으로 설정하면 생성문을 AES-GCM으로 암호화해 보관하며, 키가 없으면 시작/발송을 중단합니다. 설정 명령은 [RUNBOOK](docs/RUNBOOK.md)에 있습니다. 화면에서 로컬 생성문을 삭제해도 발송 시도 기록은 남습니다. `data/`는 Git에 포함되지 않습니다.

실제 Mac 연결은 **Mac 카카오톡 읽기 진단 → 진단 열기**에서 시작합니다. 카카오톡에 로그인한 뒤 1:1 대화 제목을 입력하고 **이름으로 바로 읽기**를 누르면 터미널의 kmsg read처럼 한 번 조회합니다. 화면에는 반환 제목이 일치한 경우에만 읽은 건수가 표시됩니다. 목록에서 고르는 방식은 별도로 두 번 관측해 변화를 확인합니다. 설치된 kmsg 1.260921.0의 MCP 초기화와 도구 조회도 확인했습니다. 실제 Keychain 및 카카오톡 읽기는 미검증이며, 읽기 관측과 엔진의 연결, 개인화, 실제 자동 발송은 후속 작업입니다. 최종 제품에는 자동 발송이 포함됩니다. 실제 검증 범위와 명령 결과는 [PROGRESS](docs/PROGRESS.md), 다음 작업은 [HANDOFF](docs/HANDOFF.md), 운영 절차는 [RUNBOOK](docs/RUNBOOK.md)를 확인하세요.

## 무엇이 들어 있나요?

| 경로 | 역할 |
|---|---|
| `backend/kakaoreply/` | 합성 엔진·정책·어댑터·SQLite journal·FastAPI |
| `frontend/` | React/TypeScript 시뮬레이터와 사용자 흐름 테스트 |
| `tests/`, `scripts/{smoke,m2_smoke}.py` | 정책·암호화·저장·MCP·API 합성 검증 |
| `Makefile`, `pyproject.toml`, `uv.lock` | 실행 명령·Python 의존성과 잠금 |
| `CODEX_MASTER_PROMPT.md` | Codex에 복사할 상세 구현 프롬프트 |
| `AGENTS.md` | 프로젝트 공통 개발 지침 |
| `docs/PRODUCT_SPEC.md` | 목표·기능·우선순위·화면·완료 기준 |
| `docs/ARCHITECTURE.md` | 실행 구조·상태·시간·저장·API |
| `docs/KAKAO_ADAPTER.md` | MCP/CLI 구분과 kmsg 연결 제약 |
| `docs/RELIABILITY.md` | 중복·취소·불확실 전송·보호 원칙 |
| `docs/TEST_PLAN.md` | 인수 사례·합성 시나리오·검증 단계 |
| `docs/CONTRACTS.md` | 스키마와 설정의 추가 의미 |
| `docs/AI_WORKFLOW.md` | AGENTS·역할·스킬·실제 서브에이전트 사용법 |
| `docs/agents/` | 주 에이전트·백엔드·프런트엔드·리뷰·QA 역할 문서 |
| `docs/PLAN.md` | 단계별 구현 체크리스트 |
| `docs/DECISIONS.md` | 설계 선택의 이유와 변경 기록 |
| `docs/PROGRESS.md`, `docs/HANDOFF.md` | 실제 진행과 다음 세션 연결 |
| `docs/RUNBOOK.md` | 구현 후 설치·진단·실기기 검증 절차 |
| `docs/SOURCES.md` | 외부 기능의 공식 근거와 검증 범위 |
| `prompts/runtime/` | 앱이 LLM에 전달할 운영 프롬프트 템플릿 |
| `schemas/` | 설정·메시지 이벤트·LLM 응답 JSON Schema |
| `examples/` | 초기 설정과 합성 대화·응답 예시 |

## `.agent`와 Markdown 지침

- `AGENTS.md`는 프로젝트 지침입니다.
- `.agents/skills/<이름>/SKILL.md`는 반복 작업 절차를 담는 Codex 스킬 경로입니다.
- `.codex/agents/*.toml`은 지원되는 Codex에서 실제 서브에이전트를 정의하는 설정입니다.
- `docs/agents/*.md`는 역할 문서이며, 파일 존재만으로 별도 에이전트가 실행되지 않습니다.
- `prompts/runtime/*.md`는 개발 지침이 아니라 운영 앱의 생성 프롬프트입니다.

프로젝트에 스킬 3개와 서브에이전트 TOML 3개를 템플릿으로 생성했습니다. 이번 구현에서는 파일을 직접 읽어 지침을 적용하고 실제 backend/frontend/reviewer 서브에이전트를 사용했습니다. M2 세션에서는 호스트 스킬 목록에 프로젝트 스킬 3개가 표시되는 것을 확인했습니다. custom agent TOML 자동 선택은 별도 미검증이며 개인 전역 설정은 변경하지 않았습니다.

## 현재 검증 상태

코드와 모의 검증의 실제 결과는 [PROGRESS](docs/PROGRESS.md)에 기록합니다. 실제 Mac 카카오톡 읽기·전송·자동 운영은 미검증입니다. 이번 개발에서는 실제 메시지를 보내지 않습니다.

## 설계 핵심

실제 자동 발송은 제품 범위입니다. 초기 실행은 mock/off이며, 사용자가 대상과 시간·한도를 정해 자동 모드를 켠 뒤 그 범위에서 응답합니다. 본인 직접 답장과 문맥 변경을 우선하고, 결과가 불명확한 전송은 자동 재시도하지 않습니다. 말투·사실·현재 상태를 분리하고 모든 자동 발송에는 AI 대리 답장 표시를 붙입니다.
