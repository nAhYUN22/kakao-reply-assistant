# 데이터·설정 계약 보충

이 파일은 사람이 읽는 명세와 `schemas/` 사이의 의미를 연결합니다. JSON Schema 검증 통과만으로 전송을 허용하지 않습니다.

## 1. 설정 검증

- `examples/app-config.example.json`은 안전한 초기 설정입니다. 실제 모델·대상·작동 시간은 미설정입니다.
- 숫자 시간 단위는 초입니다. `active_windows.days`는 ISO 요일(월요일 1, 일요일 7)입니다.
- `start == end`인 구간은 거절합니다. 24시간 운영이 필요하면 서로 겹치지 않는 두 구간 등 의미가 명확한 입력을 사용합니다.
- 유효한 IANA 시간대인지 `zoneinfo` 등으로 추가 검사합니다. 지원하지 않는 DST 정책은 거절합니다.
- `reply_delay < max_incoming_age`와 사용자 정책에 맞는 settle/cooldown 관계를 검사하고, 응답이 불가능해지는 조합을 안내합니다.
- 공급자가 mock이 아니면 실제 adapter와 endpoint·model을 확인합니다. 특정 vendor URL·SDK 형식을 추측해 고정하지 않습니다.
- `credential_ref`는 키체인의 참조 이름이며 API 키 자체가 아닙니다.
- 로컬 서버 허용 URL과 외부 공급자 URL을 구별합니다. 임의 URL이 수신 메시지에서 설정으로 들어오지 않습니다.
- 설정 저장에는 `settings_revision`을 사용하며, 오래된 revision의 갱신은 거절합니다. revision과 대상 식별자는 사용자 편집 설정 JSON과 분리한 엔진 envelope에 둡니다.
- 정지/초안 모드로 전환할 때 `live_send_enabled`를 함께 false로 갱신합니다.

## 2. 메시지 이벤트

`message-event.schema.json`은 복호화된 메모리 안의 자료형입니다. 실제 대화를 이 JSON 그대로 로그나 파일에 저장하라는 요구사항이 아닙니다.

| 필드 | 정의 |
|---|---|
| `event_id` | 해당 메시지 발생에 앱이 부여한 ID. 카카오 원본 메시지 ID가 아님 |
| `binding_id` | 사용자가 확인한 1:1 대화의 앱 내부 식별자 |
| `origin` | partner / owner(직접 발신) / bot / system / unknown |
| `source` | mock / live_poll / live_watch / history_import |
| `observed_at` | 앱이 관측한 UTC 시각 |
| `source_time` | 원본에서 읽은 시각. 모르면 null을 유지 |
| `sequence` | 해당 관측 세션의 발생 순서 |
| `authorship` | 인간 직접 작성 또는 봇 작성 여부의 증거 |
| `confidence` | 발신자·신규성·시각의 확실성을 분리한 범주 |

연속 관측 중 짧고 검증된 간격의 스냅샷 차이로 신규 발생이 확인되면, 원본 시각이 없어도 `observed_at`을 응답 대기의 기준으로 사용할 수 있습니다. 이때 `source_time`을 임의로 채우지 않고 `confidence.time=observation_only`로 보관합니다. 관측 공백, 초기 기준선, 가져온 과거 자료에는 이 규칙을 적용하지 않습니다.

동일한 문장의 실제 두 발생을 보존합니다. 내용·작성자·분 단위 시각 해시만으로 합치지 않습니다. 스냅샷 겹침과 순서·발생 횟수를 검사합니다. 구분할 수 없으면 발송을 보류합니다.

추가 의미 검증:

- `origin=owner`는 본인 직접 발신이 확인된 경우만 사용합니다. UI가 모호하면 unknown입니다.
- `origin=bot`는 outbox의 실제 발송과 대응되는 근거가 있어야 합니다.
- `authorship=human_verified`만으로 충분하지 않고, 본인 작성 예시에는 `origin=owner`도 필요합니다.
- system/unknown 이벤트로 답장 작업을 만들지 않습니다.
- history_import와 baseline은 말투/검토 자료일 수 있지만 신규 자동 답장의 트리거는 아닙니다.

## 3. 모델 응답

- 허용 필드는 `action`, `reply_text`, `reason_codes`, `used_fact_ids` 네 개입니다.
- `reply`만 자동 발송 후보이며 `hold`·`no_reply`의 본문은 빈 문자열입니다.
- `notify_owner`는 로컬 알림입니다. 본문이 있으면 사용자에게 보여줄 초안이며 상대에게 보내지 않습니다.
- 스키마상 최대 본문 길이는 1,000자이지만 실제 발송은 사용자 설정 `max_chars`를 적용합니다. 초기값 240자는 표시 문구와 줄바꿈까지 포함한 최종 길이입니다.
- 길이는 NFC 정규화 후 Unicode code point 수로 평가합니다. JS의 UTF-16 `string.length`와 다른 이모지 사례를 테스트합니다.
- `used_fact_ids`는 현재 요청에 넣은 유효한 사실의 부분집합이어야 합니다.
- 앱의 epoch·설정 revision·프로필 버전·수신자는 엔진이 붙이는 envelope입니다. 모델의 네 필드 출력에 넣지 않습니다.

### 이유 코드

| 코드 | 표시 의미 |
|---|---|
| ROUTINE_REPLY | 일상 대화 |
| ACKNOWLEDGEMENT | 짧은 확인·공감 |
| MISSING_FACT | 필요한 정보 없음 |
| CONFLICTING_FACTS | 근거 정보가 충돌함 |
| EXPIRED_FACT | 정보 유효시간이 지남 |
| COMMITMENT_REQUEST | 본인의 약속·확정이 필요함 |
| RELATIONSHIP_DECISION | 중요한 관계 판단이 필요함 |
| MONEY_REQUEST | 금전 관련 확인 필요 |
| URGENT_OWNER_ATTENTION | 본인의 빠른 확인 필요 |
| UNSUPPORTED_CONTENT | 지원하지 않는 입력 |
| UNTRUSTED_INSTRUCTION | 대화 안에 제어 지시가 있음 |
| NO_REPLY_NEEDED | 답장 불필요 |
| INVALID_CONTEXT | 문맥 정보가 불완전함 |

이는 짧은 제품 상태 코드입니다. 모델의 비공개 사고 과정을 요구하거나 이 코드를 감정 진단 점수로 사용하지 않습니다. 코드 목록을 바꾸면 스키마·UI 표시·fixture·테스트를 함께 갱신합니다.

## 4. 설정·작업 envelope 권장 필드

`binding_revision`, `settings_revision`, `conversation_epoch`, `monitor_session_id`, `auto_session_id`, `reply_job_id`, `candidate_id`, `generation_snapshot_digest`, `style_profile_version`, `prompt_version`, `provider_version`을 엔진이 기록합니다. digest는 평문 내용 해시를 공개하지 않고 키를 가진 HMAC 등으로 처리합니다.

같은 문맥이라는 확인은 모델에 질문해서 얻는 값이 아니라 앱 상태와 관측 증거로 계산합니다.

봇의 `CONFIRMED_LOCAL` 이후에는 후보의 context에 포함된 미응답 입력만 해결합니다. 후보에 포함되지 않은 새 입력을 함께 지우지 않습니다. 새 묶음은 새 최초 시각을 가지며, 봇 발신 자체로 본인 우선 기간·연속 응답 한도를 초기화하지 않습니다.

## 5. 스키마 변경 절차

1. 변경 이유와 호환성을 `DECISIONS.md`에 기록합니다.
2. 스키마 버전·마이그레이션·Pydantic 모델·UI 타입을 함께 갱신합니다.
3. 유효/무효 fixture로 계약 테스트합니다.
4. 기존 발송 작업을 조용히 새 의미로 해석하지 않습니다.

이 패키지의 스키마는 구현 계약입니다. 아직 앱의 실행 코드나 실제 카카오톡 출력 스키마를 대체하지 않습니다.
