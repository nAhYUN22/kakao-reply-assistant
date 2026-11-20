# M2 저장·연결 구현 계약

기본 앱은 계속 mock/off이며 실제 메시지를 전송하지 않습니다. 이번 구현은 M2 코드와 합성 검증이며 실제 카카오톡 읽기 검증과 구분합니다.

## 파일 책임

- 주 에이전트: storage/engine/API 통합, 마이그레이션, 공통 의존성·잠금·문서.
- m2_crypto: crypto.py, keys.py, tests/security.
- m2_mcp: kakao 패키지, tests/kakao. 실제 SDK stdio 및 읽기 도구만 허용.
- reviewer: 독립 검토, 소스 수정 없음.

## 암호화 저장

- `DataCipher(key: bytes, key_id: str)`; `encrypt(table,row_id,plaintext)->bytes`, `decrypt(table,row_id,payload)->str`, `digest(value)->str`.
- AES-256-GCM, 임의 nonce, table/row/schema/key ID를 인증하는 AAD. 키/본문을 repr·예외·로그에 노출하지 않습니다.
- `MacOSKeychainProvider.get_key`는 기존 키만 읽고, `provision`은 별도 명시적 설정 명령입니다. 임시 키/다른 backend로 fallback하지 않습니다.
- `Journal(path, cipher=None, key_check=None)`은 v1 metadata DB를 v2로 transaction 마이그레이션합니다. 기존 작업·attempt·event 기록을 보존합니다.
- 기본 metadata-only는 원문 비영속입니다. 암호화 활성화 DB는 저장된 키 ID와 인증 검증값에 맞는 키가 있어야 다시 열립니다. 잘못된 키·키 누락·암호문 변조는 중단 사유입니다.
- 생성문은 발송 전에 암호화 저장하고, 실패하면 발송하지 않습니다. 같은 키를 주입한 합성 재시작 테스트로 본문 복구와 불명/한도 보존을 검증합니다.
- `KAKAOREPLY_KEY_STORE=keychain`, `KAKAOREPLY_KEY_ID`로 명시적 선택. 환경변수는 키 참조만 가지며 키 자체를 받지 않습니다. 설정하지 않으면 기존 metadata-only입니다.
- 본문 보존은 7일, 삭제는 본문만 제거하며 발송 방지에 필요한 작업·시도 기록은 유지합니다. OS 백업까지 완전 삭제를 보장하지 않습니다.

## 실제 연결 경계

MCP 어댑터는 초기화·tools/list·읽기·종료를 구현합니다. 모의 엔진을 실제 계정에 자동 연결하지 않습니다. 실제 설치본 스키마 확인이 선행되며, 가짜 서버 테스트 성공은 실제 Mac 접근 성공이 아닙니다. baseline·관측 공백·중복/동일 문구·모호한 작성자는 전송 허용 근거로 승격하지 않습니다. 실전송 연결은 M4에 남깁니다.

## UI/API 추가 계약

- 인증된 `GET /api/storage`: `{schema_version:2, body_storage:"aead"|"memory_only", raw_retention_days:7}`.
- 인증된 `DELETE /api/jobs/{job_id}/body`: 요청 본문 없음, 성공 응답은 RuntimeState. 없는 작업 404, 발송 중 409, 기존 Host/Origin/session 보호 적용.
- 삭제는 로컬 생성문에만 적용합니다. 발송 회수가 아니며 작업/시도 이력은 보존합니다. 생성 중인 결과는 epoch로 폐기하고, 발송 중에는 삭제하지 않습니다.
- frontend 담당 범위는 App/api/types 및 해당 테스트입니다. 공통 API와 의존성은 주 에이전트가 관리합니다.

## 이름 직접 읽기

인증된 POST /api/kakao/read-by-name은 name과 one_to_one_confirmed=true를 받습니다. 기존 읽기 진단과 같은 사용자별 잠금 아래 CLI read를 한 번만 실행합니다. 성공 응답은 {"status":"READ","count":N}이며 N은 0~3입니다. 요청 이름과 kmsg가 반환한 창 제목이 일치하지 않으면 결과를 폐기합니다. 출력과 오류에 방 이름과 메시지를 포함하지 않습니다. 이 API에는 대상을 발송 가능 상태로 등록하는 효과가 없습니다.

## 남은 통합

진단에서는 CLI 목록과 HMAC 재검사, 사용자별 프로세스 잠금, 확인된 chat_id를 사용합니다. 진단 verify의 선택 인자 allow_open_window는 기본 false입니다. true면 kmsg가 해당 방을 찾아 열 수 있도록 background_safe=false를 명시합니다. 호출 전 최신 목록에서 비슷한 제목의 충돌을 검사하고 결과 창 제목도 확인합니다. kmsg가 반환하는 카운트는 대화 참여자나 실제 메시지 영역의 귀속을 독립적으로 입증하지 않습니다.

터미널에서 실행한 앱으로 실제 목록 조회는 확인했습니다. 닫힌 방 본문 실기기 검증, 연속 관측과 엔진 통합, 직접 작성/봇 판별, 실제 Keychain, 실시간 보존 및 감사 기록 만료는 후속입니다.
