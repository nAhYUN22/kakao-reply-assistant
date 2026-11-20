# 다음 Codex 세션 인수인계

기준일: 2026-11-20. **M0/M1 구현·모의 검증 완료, 다음은 M2입니다.**

## 읽을 파일

AGENTS.md → PROGRESS.md → PLAN.md → PRODUCT_SPEC/ARCHITECTURE/CONTRACTS → M1_API.md → 작업에 맞는 KAKAO_ADAPTER/RELIABILITY/TEST_PLAN. 기존 상세 명세는 전체 제품 요구이며 M1 구현보다 넓습니다.

## 실제 구조와 명령

- `backend/kakaoreply/{domain,adapters,storage,engine,api}.py`
- `frontend/src/` React/TypeScript 화면과 API 테스트
- `tests/backend/` 37개 + `tests/test_contracts.py` 7개
- `scripts/smoke.py`, `Makefile`, `pyproject.toml`, `uv.lock`, `frontend/package-lock.json`
- 프로젝트 스킬 `.agents/skills/reply-{implement,review,eval}/SKILL.md`
- 역할 정의 `.codex/agents/{backend,frontend,reviewer}.toml`

```bash
make install
make test
make build
make smoke
make serve
```

127.0.0.1:8765에서 빌드 UI를 제공합니다. 개발 UI는 별도 `make dev-ui`로 5173에서 실행합니다. Python 3.12 이상, uv, Node 22.12 이상/npm이 필요합니다. 현재 `.venv`는 임시 위치에 설치한 Python 3.12.13 기반이므로 임시 런타임이 정리되면 `uv sync --locked`로 재생성하세요.

## 동작과 불변조건

- 기본 mock/off/실전송 false. 모의 시작만 합성 대상과 데모 활성 구간을 설정합니다.
- UI/API로 시간을 명시적으로 전진합니다. 실시간 운영 타이머가 아닙니다.
- 생성은 MockLLM, 발송은 FakeTransport. 실제 카카오톡/LLM 호출은 없습니다.
- 첫 600초·settle 20초·cooldown 900초, 수동 답장/불명 작성자/문맥 변경/중지의 후보 취소.
- 모든 모의 발송도 최종 정책·길이·AI 표시 검사 및 durable outbox를 통과합니다.
- 불명확 전송 자동 재시도 금지. start(auto)로 우회할 수 없습니다.
- `data/mock.sqlite` 기본 또는 `KAKAOREPLY_DB_PATH`; 동일 DB에 프로세스 잠금. 일반 원문은 DB·로그에 없습니다.
- 생성문은 메모리 전용이라 재시작 후 상세 null. 재시작은 off, 미완료 작업 취소·DISPATCHING 불명 복구. 민감 자료 영속 암호화/Keychain은 미구현.

## 검증 결과와 알려진 사항

Python 44개, UI/API 10개 통과; build 및 API smoke 통과. 인앱 브라우저에서 모의 발송·상세·본인 취소·중지 확인. Starlette TestClient의 httpx deprecation warning 1개는 후속 정리 항목입니다.

독립 리뷰의 무기한 PENDING 문제는 만료를 due보다 먼저 검사해 수정했습니다. 사용자 개입·취소·중복·다른 대상·UNKNOWN 복구·API 원문 비노출 회귀가 있습니다. 기존 인수 시나리오 49개 전부나 실제 Mac 연동은 검증하지 않았습니다.

## 다음 구현

1. 실제 설치된 kmsg 버전·help 및 MCP tools/list를 확인할 어댑터/가짜 MCP 계약 테스트를 구현합니다. 현재 PATH에 kmsg는 없습니다.
2. 민감 컬럼 AEAD·Keychain, 명시적 DB 마이그레이션/삭제·보존 정책을 추가합니다. M1의 본문 없는 metadata journal을 실데이터 저장으로 그대로 확대하지 마세요.
3. 실제 스냅샷 정규화·baseline·대상/작성자 증거·직접 답장 관측을 구현합니다. 계정/권한이 없어도 mock 테스트는 계속합니다.
4. 개인화·외부 모델·live 전송은 이후 M3/M4입니다. 최종 제품에는 자동 발송이 포함됩니다.

실제 Mac 읽기·실제 전송·자동 실운영 모두 미실행입니다. 이번 개발 요청은 실제 사람에게 메시지를 보내는 권한을 포함하지 않습니다. 개인 전역 Codex 설정도 바꾸지 마세요.

Git `main`과 origin은 사용자 지정 https://github.com/nAhYUN22/kakao-reply-assistant.git 에 연결되어 있습니다. 최신 업로드 결과와 커밋은 PROGRESS 및 `git status`/`git log`로 확인하세요. 원격 이력을 강제로 덮어쓰지 않습니다.
