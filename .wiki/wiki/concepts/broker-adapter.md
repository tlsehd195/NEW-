---
type: concept
title: Broker Adapter 중립성 패턴
tags:
  - architecture
  - broker
created: '2026-09-24T10:18:21.799Z'
---
## 정의
core 트레이딩 시스템이 특정 증권사 API(Toss, KIS 등)에 직접 의존하지 않고, `broker.protocol.BrokerAdapter`라는 중립 Protocol에만 의존하도록 강제하는 패턴. PROJECT_MASTER_PLAN.md 9.3절: "core system은 Toss API에 직접 의존하지 않는다".

## 구조
`BrokerAdapter`(Protocol) ← `TossBrokerAdapter`(현재 구현) / KIS 어댑터(예정, 사용자 액션 대기 중).
공통 예외 계층: `BrokerError` → `BrokerAuthError`/`BrokerTimeoutError`/`BrokerRateLimitError`/`BrokerProviderError`.

## 관련 ADR
ADR-0019(Toss 증권 어댑터), ADR-0027(Toss 브로커 어댑터 완성), ADR-0028(미국 장기 페이퍼 트레이딩 운영 모델), ADR-0191(참고: 사용자 액션 대기 항목에서 KIS 인용).

## 관련 문서
`docs/operations/TOSS-API-GAP-ANALYSIS.md`

## 현재 상태
KIS(한국투자증권) 모의투자 어댑터는 CLAUDE.md "사용자 액션 대기 항목"에 등록되어 있음 — 실계좌 개설 + APP KEY/SECRET 발급이 선행되어야 `src/broker/kis/` 작성이 시작됨.

## 관련 엔티티
[broker](../entities/broker.md)
