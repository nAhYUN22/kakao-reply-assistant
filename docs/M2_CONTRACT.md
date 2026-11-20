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

## 남은 통합

실제 읽기 catalog 확보·재확인 UI, 엔진 live 경로, 작성자/bot echo 증거, 서로 다른 프로세스 간 UI 직렬화, 실시간 보존 작업과 30일 audit 정리는 미구현입니다. 실제 Keychain 및 Mac 읽기 검증도 수행하지 않았습니다.
