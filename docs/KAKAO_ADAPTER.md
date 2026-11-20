# KakaoReply 카카오톡 어댑터 명세

- 적용 대상: `mock`, `kmsg_mcp`, `kmsg_cli` transport입니다.
- 기준일: 2026-11-20입니다. 구현 시 설치한 버전의 기능을 다시 확인합니다.
- 이 문서는 읽기·전송의 계약과 검증 방법을 정의합니다. 실기기 검증 완료 보고서가 아닙니다.
- 기본값은 `mock`, `off`, `live_send_enabled=false`이며 이 문서만 읽었다고 실제 메시지를 보내지 않습니다.
- 런타임 LLM에는 이 어댑터의 전송 도구를 노출하지 않습니다.

## 1. 확인된 upstream 계약

[kmsg 사용 문서](https://github.com/channprj/kmsg/blob/main/USAGE.md)에 따르면 다음을 주의해야 합니다.

| 항목 | 문서상 동작 | 구현 시 반영 |
| --- | --- | --- |
| 환경 | macOS 13 이상, Mac 카카오톡, 손쉬운 사용 권한 | Mac 실연동 capability 확인 |
| 채팅 ID | 로컬 synthetic `chat_id` | 서버 영구 ID로 취급하지 않음 |
| 이름 변경 | 새 로컬 identity가 생길 수 있음 | 대상 자동 재바인딩 금지 |
| 작성자 | 판별 실패도 `"(me)"`로 나타날 수 있음 | 이 문자열만으로 본인 확정 금지 |
| 메시지 시각 | date/time이 빠질 수 있음 | 누락과 신뢰도를 보존 |
| watch JSON | 여러 줄 pretty JSON 객체 스트림 | JSONL 전용 파서 금지 |
| 시작 기준선 | 기존 기록은 재방출하지 않음 | 시작 전 기록을 신규 입력으로 취급하지 않음 |
| background-safe | 이미 노출된 대상 창만 읽음 | 숨은 창에서도 무조건 된다고 표시하지 않음 |
| dry-run | 카카오톡에 접근하지 않고 대상·본문 출력 | 실제 대상·UI 검증 완료로 오인 금지 |
| MCP confirm | 생략/false는 전송, true는 확인 필요 반환 | 앱 내부 정책과 별도로 취급 |

이 표는 카카오 공식 API 보장에 관한 설명이 아닙니다. kmsg 작성자 문서에 따른 연동 정보입니다.
MCP 전송 성공 응답을 상대방 수신·읽음 확인으로 해석하지 않습니다.

## 2. transport별 책임

| transport | 사용 목적 | 실제 UI 접근 |
| --- | --- | --- |
| `mock` | 개발·시뮬레이션·CI·장애 주입 | 절대 수행하지 않음 |
| `kmsg_cli` | CLI subprocess를 통한 연결 | 허용된 작업만 수행 |
| `kmsg_mcp` | 실제 stdio MCP 초기화·tools/list·tools/call | 허용된 작업만 수행 |

`kmsg_cli`만 실행하고 MCP 연결이 완료됐다고 보고하지 않습니다.
두 실어댑터는 동일한 domain 인터페이스를 구현하되 지원 capability 차이를 숨기지 않습니다.
MCP가 지원하지 않는 기능을 CLI로 보완하는 경우 설정·진단·ADR에 실제 경로를 표시합니다.
mock에서 받은 채팅 ID를 실어댑터의 수신자로 사용하지 않습니다. transport 전환 시 binding을 다시 검증합니다.

## 3. 제안 인터페이스

아래 이름은 앱 내부 인터페이스입니다. upstream CLI나 MCP에 그대로 존재한다고 가정하지 않습니다.

```python
class KakaoTransport(Protocol):
    async def capabilities(self) -> TransportCapabilities: ...
    async def check_readiness(self) -> Readiness: ...
    async def discover_chats(self) -> list[ChatCandidate]: ...
    async def verify_binding(self, binding: ConversationBinding) -> BindingEvidence: ...
    async def read_snapshot(self, binding: ConversationBinding) -> TranscriptSnapshot: ...
    async def preview_send(self, intent: SendIntent) -> SendPreview: ...
    async def dispatch(self, permitted: PermittedSend) -> DispatchResult: ...
    async def close(self) -> None: ...
```

`PermittedSend`는 SendGate가 생성한 내부 객체입니다. API 요청 body나 LLM JSON에서 직접 만들지 않습니다.
객체에는 작업 ID·binding revision·epoch·최종 표시 포함 본문·정책 검증 시각을 담습니다.
어댑터는 호출 직전 객체의 대상과 현재 binding이 일치하는지 다시 검사합니다.
표시 문구와 길이 계산은 공통 delivery 계층에서 수행하고, 어댑터는 받은 최종 문구를 임의로 재작성하지 않습니다.

## 4. capability 탐지

최초 연결과 버전 변경 시 다음 정보를 기록합니다. 실제 본문·연락처 정보는 진단 로그에서 제외합니다.

- 실행 파일의 절대 경로, 확인된 버전, OS 버전, transport 종류입니다.
- `read`, `send`, `chats`, `watch`, `mcp-server`의 지원 여부입니다.
- 읽기·전송에서 `chat_id` 사용 가능 여부와 이름 기반 fallback 여부입니다.
- background-safe 읽기 지원 여부와 현재 동작 가능 여부입니다.
- 메시지 작성자·시각·방 식별에 제공되는 실제 증거의 수준입니다.
- MCP 초기화·도구 schema 버전·timeout·해당 버전의 전송 인자 의미입니다.

문서에 있는 옵션이라도 설치 버전에서 확인되지 않으면 사용하지 않습니다.
`status`가 성공했다고 채팅 읽기·정확한 상대 식별·전송 기능까지 검증됐다고 표시하지 않습니다.
`kmsg --version`이 성공해도 손쉬운 사용 권한이나 로그인 상태가 검증된 것은 아닙니다.
준비 상태는 `binary_ready`, `accessibility_ready`, `account_ready`, `binding_ready`, `read_ready`를 구별합니다.

## 5. CLI 연결 규칙

CLI 호출은 `asyncio.create_subprocess_exec`처럼 인자 배열을 사용하며 `shell=True`를 금지합니다.
본문·채팅방 이름을 shell 문자열로 결합하지 않습니다. 인자가 옵션처럼 해석되지 않는지도 계약 테스트합니다.
허용 실행 파일은 사용자가 설정하고 검증한 `kmsg` 절대 경로로 고정합니다.
명령의 stdout과 stderr는 별도 수집하며, stderr에 담길 수 있는 민감 정보를 그대로 로그에 남기지 않습니다.
출력 크기·실행 시간·동시 호출 수를 제한하고, 취소 시 자식 프로세스 종료와 결과 불확실성을 함께 처리합니다.

| 작업 | 문서상 CLI 형태 | 주의 |
| --- | --- | --- |
| 버전 | `kmsg --version` | 부작용 없는 기능 확인에 사용 |
| 준비 점검 | `kmsg status` | 앱 실행·인증 UI가 동작할 수 있음 |
| 채팅 목록 | `kmsg chats --json` | 이름과 합성 ID는 민감 데이터 |
| 읽기 | `kmsg read --chat-id ID --json` | 현재 ID 매칭을 검증 |
| 제한적 읽기 | `kmsg read --chat-id ID --json --background-safe` | 해당 창이 이미 노출돼야 함 |
| 미리보기 | `kmsg send --chat-id ID TEXT --dry-run` | 실제 대상 접근 검증을 하지 않음 |
| 전송 | `kmsg send --chat-id ID TEXT` | SendGate 통과 후 dispatcher만 호출 |
| 감시 | `kmsg watch CHAT --json` | 이름 매칭과 스트림 파싱을 별도 검증 |

이 표는 참고 형태입니다. 옵션 조합·값 전달 방식은 설치한 버전의 `--help`로 확인합니다.
첫 v1 실전송은 텍스트만 지원합니다. 사진·파일 전송 함수를 자동으로 활성화하지 않습니다.

## 6. MCP 연결 규칙

실제 MCP 어댑터는 `kmsg mcp-server`를 하위 프로세스로 실행하여 초기화와 도구 schema 확인을 수행합니다.
공식 MCP 클라이언트 라이브러리 사용을 우선하고, protocol version과 framing을 임의로 추정하지 않습니다.
현재 작성자 문서는 Content-Length framing과 한 줄 JSON-RPC 입력 지원을 설명하지만, 앱은 검증한 클라이언트 경로를 고정합니다.
`tools/list`에서 도구 이름·required 인자·결과 형식을 확인하고 최소 capability만 등록합니다.
런타임 LLM의 tools 목록에 `kmsg_send`, `kmsg_send_image`를 등록하지 않습니다.

| upstream 도구 | 앱의 사용 정책 |
| --- | --- |
| `kmsg_read` | binding으로 해석한 chat/chat_id와 제한된 읽기 범위 사용 |
| `kmsg_send` | 검증된 단일 대상과 SendGate 허가가 있을 때만 호출 |
| `kmsg_send_image` | v1에서는 노출·호출하지 않음 |

문서상 `kmsg_send`와 이미지 전송은 이름 기반입니다. `chat_id`를 받는다고 가정한 JSON을 만들지 않습니다.
동일한 이름의 방이 있으면 MCP 이름 기반 실전송을 막고, 검증 가능한 CLI ID 경로 또는 재설정을 안내합니다.
MCP 결과는 `isError`, structured payload, text payload를 구별하여 검증합니다. 사람이 읽는 문장 하나만으로 성공을 판단하지 않습니다.
`confirm=true`는 미리보기와 같은 의미가 아닙니다. 실제 대상 검증 없이 확인 요청만 반환할 수 있습니다.
`confirm=false` 또는 생략은 외부 발송입니다. 자동 세션에서는 별도 SendGate 허가가 이미 있는 경우에만 호출합니다.
초안·mock·off 모드의 구현은 전송 도구를 호출한 뒤 confirm으로 막는 방식이 아니라 호출 경로 자체를 차단합니다.

## 7. 읽기·감시의 조정

모든 UI 접근은 프로세스 전체 dispatcher를 통과합니다. 채팅방별 mutex만으로 충분하다고 가정하지 않습니다.
v1 기본 관측은 `poll=5`초 주기의 통제된 snapshot 읽기입니다. 매 poll마다 LLM을 호출하지 않습니다.
작업 시작·발송 직전·발송 이후의 읽기는 같은 dispatcher에서 순서를 보장합니다.
`watch`를 추가하면 이것도 카카오톡 UI를 읽는 별도 작업이라는 점을 반영합니다.
watch와 send의 동시 실행 안전성이 입증되지 않으면 둘을 겹쳐 실행하지 않습니다.
관측이 잠시 중단된 뒤에는 최신 snapshot과 DB 기록을 대조하고 빈 구간을 명시적으로 표시합니다.
백그라운드 모드를 기본으로 검증하되 동작 불가 시 조용히 foreground 조작으로 전환하지 않습니다.
창 열기·이동·검색이 필요한 복구는 사용자에게 상태를 보여주는 명시적 연결 과정으로 처리합니다.

## 8. JSON 파싱과 원본 검증

`read --json`은 하나의 JSON 문서, `watch --json`은 연속된 여러 JSON 객체로 취급합니다.
watch의 pretty JSON에는 개행이 포함되므로 `readline()` 한 번의 결과를 완성 객체로 보지 않습니다.
증분 UTF-8 디코더와 JSON decoder를 조합하여 부분 chunk·연속 객체·문자열 내부 개행을 처리합니다.
사용한 파서의 버퍼 최대 크기·부분 객체 timeout·오류 복구 정책을 명시합니다.
예기치 않은 stdout 로그·잘린 JSON·과대 payload는 이벤트를 억지 복원하지 말고 연결 오류로 처리합니다.
stderr는 파서 입력에 합치지 않습니다. 프로토콜·diagnostic 데이터가 원문 로그로 새지 않게 합니다.
수신 구조에서 unknown 필드는 보존 또는 무시 정책을 명시하되, 필수 필드 손실은 검증 실패로 다룹니다.

## 9. 정규화 메시지와 시각

정규화 시 다음 필드를 최소한 보존합니다.

| 필드 | 처리 |
| --- | --- |
| `event_id` | 앱 발급 ID; upstream 영구 ID가 아님 |
| `binding_id` | 검증한 내부 대화방 binding |
| `origin` | partner / owner / bot / system / unknown |
| `author_evidence` | 검증 근거와 신뢰 수준; 민감 값은 암호화 |
| `observed_at` | 앱이 기록한 UTC 관측 시각 |
| `source_time` | 원본에서 확실하게 해석할 수 있을 때만 UTC 값 |
| `source_time_raw` | 원본 표현과 해석 실패 사유; 암호화 |
| `body` | 정규화 전후 의미를 보존하는 암호화 본문 |
| `attachments_present` | 미지원 입력 판정용; 자동 다운로드하지 않음 |
| `snapshot_digest` | keyed digest와 순서 기반 대조 근거 |

기본 public schema 예시에 서버 message ID가 없다는 점을 전제로 설계합니다.
동일 문구·동일 분의 여러 메시지를 하나로 합치지 않습니다.
시간대 없는 문자열은 앱 timezone과 검증 가능한 날짜 문맥을 함께 사용합니다. 자정 경계를 임의 추정하지 않습니다.
원본 시간이 누락되면 관측 시각을 원본 발송 시각이라고 표시하지 않습니다.
신규성이나 나이를 신뢰할 수 없으면 `max_incoming_age` 검사를 통과시키지 않고 자동 응답을 보류합니다.

## 10. 방과 작성자 식별

운영자가 후보 목록에서 특정 1:1 방을 선택하고, 실제 읽기 결과의 표시 이름과 참여자 문맥을 확인합니다.
앱 binding에는 내부 UUID, 확인된 upstream ID, 암호화된 이름, revision, 검증 시각을 저장합니다.
이름 변경·방 재생성·등록 파일 변경·동명 충돌이 발생하면 binding 검증 상태를 해제합니다.
이전 이름과 비슷하다는 이유로 새 대상을 자동 선택하지 않습니다.
`"(me)"`는 본인 식별의 충분한 증거가 아닙니다. 불명확한 결과는 `origin=unknown`으로 남깁니다.
owner 판별이 신뢰 가능하다는 실기기 증거가 없으면 자동 모드는 활성화하지 않고 draft 진단을 제공합니다.
bot echo는 outbox 작업의 본문·대상·전후 순서·시각을 대조하여 분류합니다.
본인이 우연히 같은 문구를 보냈을 때 bot으로 확정하지 않습니다. 모호하면 자동 세션을 일시 정지합니다.
상대방 수신 메시지에서 보내온 이름이나 ID를 새 수신자로 실행하지 않습니다.

## 11. 신규성·중복·시작 기준선

최초 시작은 현재 transcript를 baseline으로 저장하고, 과거 기록에 자동 답장을 생성하지 않습니다.
최근 스냅샷의 ordered overlap을 이용해 뒤에 추가된 항목을 찾고, 같은 내용의 발생 횟수를 보존합니다.
본문 hash 하나만으로 중복 제거하지 않습니다. 짧은 확인 문구가 반복되는 상황을 필수 fixture로 둡니다.
watch의 신규 이벤트와 poll 결과가 같은 항목을 가리키면 내부 event ID 하나로 연결합니다.
앱 중단·절전·네트워크 복구 뒤에는 baseline을 재검증하고, 확인할 수 없는 중간 기록에 응답하지 않습니다.
old history를 직접 가져오는 import 작업은 관측 이벤트와 다른 경로를 사용하며 자동 응답 trigger를 발생시키지 않습니다.
시작과 복구에서 억제한 항목의 수·이유만 메타데이터로 남깁니다. 숨긴 대화 본문을 오류 로그에 넣지 않습니다.

## 12. 전송 경계와 결과 분류

전송 API를 호출하기 전에 다음 값이 있어야 합니다.

- 확정된 대상 binding과 revision, 자동 세션 범위입니다.
- 유효한 작업·후보 ID, 최신 epoch, 검증된 최종 문구입니다.
- 추가된 고정 suffix `— 부재중 AI 답장`과 `max_chars` 길이 검사 결과입니다.
- 최신 snapshot을 읽고 본인 답장·추가 입력·시간·한도를 재확인한 기록입니다.
- DB에 영속화한 `DISPATCHING` 및 작업당 유일한 outbox attempt입니다.

외부 호출 전에 확정적으로 실패하면 `FAILED_BEFORE_DISPATCH`입니다.
외부 호출이 시작된 후에는 nonzero 종료·timeout이 전송 실패를 확정하지 못할 수 있습니다.
이미 카카오톡 UI에 입력·전송이 이뤄졌을 수 있으므로 결과가 불명확하면 `DELIVERY_UNKNOWN`입니다.
로컬 transcript에 후보와 대응하는 새 outgoing 항목을 확인한 경우 `CONFIRMED_LOCAL`로 기록합니다.
상대에게 전달되었거나 상대가 읽었다는 보장은 하지 않습니다. 관련 upstream 증거가 없는 상태를 만들어내지 않습니다.
불확실 결과에서 동일 입력의 새 작업을 만들어 재전송하는 우회도 금지합니다.
실전송 시도는 성공 여부와 무관하게 hour/day/session 한도에 반영합니다.

## 13. 취소·재시작·복구

취소 토큰은 예약·생성·전송 전 단계에서 확인합니다. 외부 호출이 시작된 뒤 취소되어도 발송 여부 확인은 계속 관리합니다.
앱 재시작 시 `DISPATCHING` 잔여 작업은 자동 재실행하지 않고 불확실 결과로 처리합니다.
API timeout과 subprocess timeout을 구별하며, 어떤 단계에서 관측을 잃었는지 기록합니다.
기존 자식 프로세스가 살아 있는지 확인하지 않고 두 번째 watcher나 sender를 실행하지 않습니다.
로그인 해제·권한 철회·앱 종료·판독 실패는 readiness를 내리고 자동 발송을 중단합니다.
복구 후 바로 밀린 답장을 보내지 않습니다. 대상·최신 대화·입력 나이·시간대를 다시 검증합니다.
앱이 계정 비밀번호를 요청받으면 사용자에게 해당 인증 UI로 안내합니다. 챗봇 입력이나 로그로 비밀번호를 받지 않습니다.

## 14. 개인 데이터와 인증 저장소

chat 목록의 이름, 원문, 생성문, 메모리 등 앱이 영속화하는 민감 값은 앱 계층 AEAD로 암호화합니다.
키는 macOS Keychain에 저장하고, 실패하면 평문 fallback 없이 중단합니다.
어댑터의 원본 stdout은 필요한 범위에서 메모리로 파싱하며 파일·debug trace로 자동 보관하지 않습니다.
앱 로그에는 무작위 내부 ID와 상태 코드만 사용합니다. 해시 비교값은 keyed HMAC으로 생성합니다.
`kmsg`가 관리하는 자체 credential 파일·키 파일은 KakaoReply Keychain 관리와 별개입니다.
앱은 해당 파일을 읽어 키를 복사하거나 비밀번호를 중앙 서버로 전달하지 않습니다.
로컬 LLM과 외부 provider의 전송 범위를 설정 화면에서 구별합니다. provider 요청 본문 logging은 비활성화합니다.
실제 대화 fixture는 저장소·CI·이슈·스킬 문서에 넣지 않습니다. 재현에는 같은 구조의 합성 데이터를 씁니다.

## 15. mock 어댑터 필수 기능

mock은 성공 응답만 반환하는 stub이 아니라 다음 사건을 주입할 수 있어야 합니다.

- 상대 메시지, 본인 직접 답장, bot echo, 작성자 불명 메시지입니다.
- 동일한 문구의 반복, 순서가 바뀐 관측, 중복 이벤트, 날짜·시간 누락입니다.
- 읽기 실패, 끊어진 JSON, 느린 snapshot, 연결 해제, 대상 revision 변경입니다.
- 호출 전 실패, 호출 후 timeout, 전송 뒤 echo 지연, 실제 성공 후 응답 유실입니다.
- 앱 재시작, clock 이동, 허용 시간 종료, 절전 복귀에 해당하는 관측 공백입니다.

가상 clock으로 기다림을 진행하고, 실제 긴 sleep 없이 상태 전이를 검증합니다.
실어댑터 생성이나 프로세스 실행이 mock 테스트에 섞이면 테스트가 실패하도록 구성합니다.

## 16. 필수 계약·통합 테스트

| 시나리오 | 기대 결과 |
| --- | --- |
| pretty JSON 객체가 여러 chunk로 분할 | 원래 객체를 1회 복원 |
| stdout에 잘린 객체·비정상 로그 혼입 | 안전한 파싱 실패, 발송 0회 |
| 같은 분에 같은 본문 2건 | 별도 사건 2건 보존 |
| duplicate watch + poll | 하나의 입력에 활성 작업 1개 |
| 작성자 `(me)`만 존재 | 본인 확정 안 함, 자동 발송 보류 |
| 동명 채팅방 또는 이름 변경 | 다른 방으로 발송 0회 |
| draft/off/mock | 실전송 호출 0회 |
| 생성 중·READY 상태에서 본인 답장 | 후보 취소, 실전송 0회 |
| 발송 호출 뒤 timeout·restart | 자동 재전송 0회 |
| MCP confirm 인자 변경 | 의도하지 않은 호출을 계약 테스트가 탐지 |
| background-safe 대상 창 없음 | foreground fallback 없이 준비 상태 해제 |
| 봇 echo 재관측 | 본인 메시지 학습·신규 답장 trigger로 사용 안 함 |
| 읽기 결과에 prompt injection 포함 | 범위·수신자·전송 정책 유지 |
| 표시 제거를 요구하는 LLM 출력 | 엔진 suffix 유지 |

mock E2E, 어댑터 계약 테스트, 실제 Mac 검증 결과를 별도 항목으로 보고합니다.
권한·카카오 버전·앱 버전·검증한 모드·성공/실패한 capability를 검증 보고서에 기록합니다.
실제 발송 테스트는 사용자가 명시적으로 지정한 테스트 대상과 내용으로만 수행합니다.

## 17. 구현 완료 판정과 제한

CLI/MCP 양쪽 중 구현한 경로를 정확히 표시하고, 미구현 경로를 버튼만 있는 상태로 완료 처리하지 않습니다.
읽기 성공, 후보 생성 성공, 실전송 성공, 로컬 echo 확인 성공을 각각 구분합니다.
MCP의 도구 목록 확인만으로 자동 답장 제품 전체가 작동한다고 보고하지 않습니다.
원격 카카오 메시지 ID·서버 수신 확인·정확히 한 번 전송이 제공된다는 문구를 사용하지 않습니다.
대상·발신자·시각의 신뢰도가 확보되지 않은 실제 환경에서는 자동 모드 사용 불가 상태를 유지합니다.

## 18. 원문 근거

- [kmsg README](https://github.com/channprj/kmsg/blob/main/README.en.md): 요구 환경과 공개 기능입니다.
- [kmsg USAGE](https://github.com/channprj/kmsg/blob/main/USAGE.md): CLI/MCP 옵션과 JSON·confirm·ID 제약입니다.
- [kmsg ARCHITECTURE](https://github.com/channprj/kmsg/blob/main/ARCHITECTURE.md): 접근성 기반 구조와 로컬 식별·watch 방식입니다.
- upstream 자료의 설명과 본 프로젝트의 권고 정책을 구별합니다. 설치 버전과 다른 동작은 구현 중 증거를 남겨 갱신합니다.
