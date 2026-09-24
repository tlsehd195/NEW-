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
Phase 12. ADR-0018(AI 게이트웨이).

## 핵심 인터페이스/클래스
- `AIProviderAdapter`(Protocol) — `MockProviderAdapter`
- `ProviderError`/`ProviderTimeoutError`/`ProviderAuthError`/`ProviderRateLimitError`
- `RawProviderOutput`, `ProviderConfig`, `GatewayConfig`
- `AIRequestRepository`(Protocol)

## 경계
다른 모듈이 LLM을 쓰려면 반드시 이 게이트웨이를 거쳐야 함 — 프로바이더별 직접 호출 금지가 이 모듈이 존재하는 이유.
