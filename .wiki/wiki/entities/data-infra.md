---
type: entity
title: data_infra
tags:
  - module
  - phase-1
  - data
created: '2026-09-24T10:16:32.783Z'
---
## 역할
Phase 1 — 데이터 인프라. 시세/펀더멘털 등 원천 데이터의 point-in-time 안전성, 유니버스 정의, survivorship-aware 심볼 관리를 담당.

## Phase / 관련 ADR
Phase 1. ADR-0002(데이터 저장), ADR-0003(데이터 모델), ADR-0004(point-in-time 데이터), ADR-0005(데이터 프로바이더 전략), ADR-0033(실데이터 소스 결정 트리), ADR-0037(S&P500 point-in-time membership).

## 핵심 인터페이스/클래스
- `DatasetVersion`, `SymbolMetadata`, `UniverseDefinition`, `SurvivorshipAudit`
- `TradingCalendar`(Protocol) / `SimpleTradingCalendar`
- `TickerMembershipInterval`, `PriceDataCoverageReport`
- `TwelveDataRateLimiter` (외부 데이터 프로바이더 레이트리밋)

## 경계
다른 모든 Phase가 의존하는 기반 계층 — 여기서 point-in-time 위반(미래 데이터 누출)이 생기면 이후 전체 백테스트/학습 결과가 무효화됨.
