# 출처와 검증 범위

확인 기준일: 2026-11-20. 링크의 기능과 경로는 이후 변경될 수 있으므로 구현 시 설치 버전·도구 스키마와 함께 다시 확인합니다. 이 문서의 외부 사실과 제품의 설계 제안을 구분합니다.

## 1. Codex 공식 문서

| 자료 | 확인한 사항 |
|---|---|
| [AGENTS.md](https://developers.openai.com/codex/guides/agents-md) | 프로젝트 지침 발견·계층·override와 기본 크기 제한 |
| [Skills](https://developers.openai.com/codex/skills) | `.agents/skills` 경로, SKILL.md 형식, 명시/암묵 사용 |
| [Subagents](https://developers.openai.com/codex/multi-agent) | `.codex/agents/*.toml`, 역할 정의, 부모 권한 상속, 동시성 설정 |
| [Config basics](https://developers.openai.com/codex/config-basic) | 프로젝트 설정과 신뢰한 프로젝트 범위 |

확인 시 위 Codex 문서는 OpenAI의 `learn.chatgpt.com` 문서로 연결됩니다. 사용자 Mac의 Codex 버전·계정 정책·활성 기능은 이 문서 확인만으로 검증되지 않습니다.

`docs/agents/*.md`는 이 프로젝트가 정한 일반 문서 구조입니다. 이를 자동 에이전트 생성 기능이라고 설명하지 않습니다. 실제 스킬·서브에이전트 설정은 AI_WORKFLOW의 템플릿이며 현재 계정에 설치하지 않았습니다.

## 2. 카카오톡 연결 구현 작성자 자료

| 자료 | 확인한 사항 |
|---|---|
| [kmsg README](https://github.com/channprj/kmsg/blob/main/README.en.md) | macOS 13+, Mac 카카오톡, 손쉬운 사용 권한, 읽기·감시·전송·MCP 제공 |
| [kmsg USAGE](https://github.com/channprj/kmsg/blob/main/USAGE.md) | CLI·MCP 스키마, pretty JSON stream, background-safe 조건, confirm 의미 |
| [kmsg ARCHITECTURE](https://github.com/channprj/kmsg/blob/main/ARCHITECTURE.md) | UI 기반 동작과 로컬 식별자·스냅샷 비교의 성격 |

kmsg는 카카오가 제공하는 공식 도구가 아닙니다. 작성자 문서를 확인했으며 실제 Mac 설치·읽기·전송은 이 패키지 제작 중 수행하지 않았습니다. 실제 버전이 다르면 문서 내용을 억지로 맞추지 말고 어댑터와 계약 테스트를 수정합니다.

## 3. 프로토콜과 프롬프팅

- [MCP 클라이언트 개발](https://modelcontextprotocol.io/docs/develop/build-client): 실제 MCP 클라이언트와 서버 호출의 개념·현재 SDK 사용법 확인용입니다. 예제의 특정 공급자·모델을 이 프로젝트의 필수값으로 복제하지 않습니다.
- [모델 프롬프팅 안내](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices): 말투와 출력 형식을 예시로 유도하는 방식의 참고입니다. 어떤 모델에서도 같은 품질을 보장하는 근거가 아닙니다.

## 4. 본 프로젝트가 정한 설계

기본 대기시간, 응답 한도, Python/FastAPI/React 선택, 상태 이름, 암호화 설계, 화면, JSON Schema, 스킬 템플릿과 테스트 사례는 이 프로젝트를 위해 작성한 설계안입니다. 외부 제품이 이 요구사항을 이미 제공한다는 의미가 아닙니다.

## 5. 다음 구현자가 기록할 환경 증거

- Codex 클라이언트와 버전
- Python·Node·패키지 관리자와 잠금 파일
- macOS·KakaoTalk·kmsg 버전
- MCP 서버 초기화와 도구 목록 스키마
- mock·읽기·전송·자동 모드 각각의 실제 검증 여부
- 문서와 설치 버전이 다른 지점 및 결정 기록

환경 증거에는 대화 원문·토큰·비밀번호·개인 이름을 넣지 않습니다.


## M0/M1 구현 중 확인한 출처 (2026-11-20)

- https://learn.chatgpt.com/docs/build-skills — 프로젝트 스킬 경로·메타데이터·점진적 읽기. 실제 파일 생성 및 명시적 읽기는 수행, 자동 발견은 별도 미검증.
- https://learn.chatgpt.com/docs/agent-configuration/subagents — custom agent 필수 필드와 역할 설정. 현재 세션의 실제 병렬 도구로 backend/frontend/reviewer 실행.
- https://fastapi.tiangolo.com/tutorial/testing/ — TestClient 기반 API 테스트. 설치본 FastAPI 0.165.0과 httpx 0.28.1을 잠금 파일에 기록.
- https://docs.astral.sh/uv/concepts/projects/sync/ — uv 의존성 잠금 및 동기화.
- https://vite.dev/guide/ — Vite 빌드와 개발 서버. 프로젝트는 설치·빌드로 검증한 Vite 7 계열을 사용.

실제 설치 버전의 최종 값은 `uv.lock`, `frontend/package-lock.json`과 PROGRESS를 확인합니다. kmsg가 PATH에 없어 이번 단계에서 kmsg 도움말·MCP tools/list·카카오톡 읽기 및 전송은 실행하지 않았습니다.
