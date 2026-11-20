# 백엔드 에이전트 작업 지침

## 담당

할당된 범위의 domain, runtime, adapters, generation, delivery, storage, API를 구현합니다. 경로는 실제 저장소 구조에 맞추며 주 에이전트가 지정한 파일만 수정합니다.

## 먼저 읽기

`PRODUCT_SPEC.md`, `ARCHITECTURE.md`, `KAKAO_ADAPTER.md`, `RELIABILITY.md`, `CONTRACTS.md`, `schemas/`를 확인합니다.

## 필수 기준

- 정책과 IO를 분리하고 FakeClock·FakeTransport·MockLLM으로 검증합니다.
- 전체 UI 접근은 단일 dispatcher를 사용하고 LLM 대기 중에는 UI lock을 잡지 않습니다.
- outbox와 epoch로 수동 개입·오래된 생성 결과·불확실 전송을 처리합니다.
- `mode=draft`와 `transport=mock`에서는 실제 전송 호출이 0회입니다.
- MCP와 CLI 구현을 구분하고 실제 스키마를 확인합니다.
- 공급자 키와 민감 데이터가 로그·API 응답에 노출되지 않게 합니다.
- 마이그레이션·공통 스키마 변경은 주 에이전트와 계약을 맞춘 뒤 수행합니다.
- 실제 사람에게 테스트 메시지를 보내지 않습니다.

## 완료 보고

변경 파일, 구현한 계약, 테스트 명령·결과, 재현 가능한 제약을 반환합니다. 외부 전송을 완료하지 못한 이유와 mock에서 검증한 범위를 분리합니다.
