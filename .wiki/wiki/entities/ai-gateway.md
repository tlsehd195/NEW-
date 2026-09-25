---
type: entity
title: ai_gateway
tags:
  - module
  - phase-12
  - ai-gateway
created: '2026-09-24T10:17:10.142Z'
---
## 역할
Phase 12 — AI Gateway. 프로젝트 전체에서 AI/LLM 프로바이더를 호출하는 **단일 진입점**(`ai_gateway.gateway.AIGateway`). PROJECT_MASTER_PLAN.md 5절: "전체 애플리케이션에서 AI API를 직접 호출하지 않는다"의 구현체.

## Phase / 관련 ADR
Phase 12. ADR-0018(AI 게이트웨이). ADR-0206(실제 Gemini 프로바이더 어댑터, 2026-09-25).

## 핵심 인터페이스/클래스
- `AIProviderAdapter`(Protocol) — `ai_gateway.provider.MockProviderAdapter`(결정론적, 오프라인, 이 플랫 패키지가 유일하게 출하하는 구현체)
- `ProviderError`/`ProviderTimeoutError`/`ProviderAuthError`/`ProviderRateLimitError`
- `RawProviderOutput`, `ProviderConfig`, `GatewayConfig`
- `AIRequestRepository`(Protocol)

## 실제(non-mock) 프로바이더 — `ai_gateway.providers` 서브패키지 (ADR-0206, 2026-09-25)
`ai_gateway/*.py`(위 플랫 패키지)는 여전히 mock-only/오프라인이며 `tests/ai_gateway/test_ai_gateway_boundary.py`가 그대로 검증한다(`os.environ` 미사용, 네트워크 라이브러리 미import). 실제 네트워크 호출이 필요해지자 `data_infra.providers.*`(Tiingo 등)와 동일한 config/auth/transport 분리 패턴으로 **별도 서브패키지**를 신설:
- `ai_gateway.providers.gemini.GeminiProviderAdapter` — Google Gemini API 실제 호출 어댑터(stdlib `urllib`만 사용)
- `ai_gateway.providers.gemini_auth` — 비밀키(`GEMINI_API_KEY`) 해석이 격리된 유일한 파일
- `ai_gateway.providers.gemini_transport` — 실제 HTTP 트랜스포트. 429 응답의 실제 재시도 신호가 `Retry-After` 헤더가 아니라 JSON 바디 `error.details[].retryDelay`에 있다는 점, `gemini-3.8-flash`의 무료 티어 실제 한도가 5 RPM이라는 점을 실측으로 확인해 반영

**유일한 실제 호출부(현재 전체 `src/` 기준)**: `scripts/run_ai_prediction_experiment.py`(주가 방향 예측 정확도를 기록만 하는 리서치 실험)와 `scripts/verify_gemini_adapter.py`(수동 실 API 검증). `predict`/`decision`/`risk`/`broker`는 여전히 이 서브패키지를 전혀 import하지 않는다(`tests/ai_gateway/test_ai_gateway_gemini_boundary.py`가 AST로 검증) — Grounding Gate 배선 보류 결정(CLAUDE.md)은 이 실험으로도 해제되지 않았다.

## 경계
다른 모듈이 LLM을 쓰려면 반드시 이 게이트웨이를 거쳐야 함 — 프로바이더별 직접 호출 금지가 이 모듈이 존재하는 이유. `ai_gateway.providers.*`의 실제 어댑터도 이 원칙의 예외가 아니라 적용 대상이며(반드시 `AIGateway.generate()`를 통해서만 호출됨), 실거래 파이프라인(predict/decision/risk/broker)과는 완전히 분리되어 있다.
