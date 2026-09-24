---
type: entity
title: broker
tags:
  - module
  - phase-13
  - broker
created: '2026-09-24T10:17:13.844Z'
---
## 역할
Phase 13 — 브로커 어댑터. PROJECT_MASTER_PLAN.md 9.3절: "core system은 Toss API에 직접 의존하지 않는다" — `broker.protocol.BrokerAdapter`가 모든 브로커 구현체(Toss, 향후 KIS 등)가 따라야 할 중립 인터페이스.

## Phase / 관련 ADR
Phase 13. ADR-0019(Toss 증권 어댑터), ADR-0027(Toss 브로커 어댑터 완성).

## 핵심 인터페이스/클래스
- `BrokerAdapter`(Protocol) — `TossBrokerAdapter`
- `TossAuthClient`, `TossHttpTransport`
- `BrokerError`/`BrokerAuthError`/`BrokerTimeoutError`/`BrokerRateLimitError`/`BrokerProviderError`

## 경계
core 시스템은 이 Protocol에만 의존 — 브로커별 세부사항(Toss API 등)은 어댑터 내부에 캡슐화. **KIS 모의투자 어댑터는 사용자 액션(API 키 발급) 대기 중** — CLAUDE.md "사용자 액션 대기 항목" 참고.
