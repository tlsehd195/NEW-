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
Phase 1. ADR-0002(데이터 저장), ADR-0003(데이터 모델), ADR-0004(point-in-time 데이터), ADR-0005(데이터 프로바이더 전략), ADR-0033(실데이터 소스 결정 트리), ADR-0037(S&P500 point-in-time membership), ADR-0104(13F 기관 보유 집계), ADR-0194(13F 특정 filer 추적 registry, guru_consensus_score).

## 핵심 인터페이스/클래스
- `DatasetVersion`, `SymbolMetadata`, `UniverseDefinition`, `SurvivorshipAudit`
- `TradingCalendar`(Protocol) / `SimpleTradingCalendar`
- `TickerMembershipInterval`, `PriceDataCoverageReport`
- `TwelveDataRateLimiter` (외부 데이터 프로바이더 레이트리밋)
- `InstitutionalHoldingRecord`(13F 전체 filer 집계) / `InstitutionalFilerHoldingRecord`(13F 개별 filer, ADR-0194)
- `tracked_institutional_filers.TrackedFiler`/`TRACKED_FILERS`/`active_tracked_filers` — point-in-time-aware "guru investor" registry(ADR-0194). `tracked_from`/`tracked_until`로 특정 filer의 은퇴/펀드 청산을 과거 backtest 결과에 영향 없이 반영 (실제 사례: Scion Asset Management, 2025-11-10 SEC 등록 취소).

## 경계
다른 모든 Phase가 의존하는 기반 계층 — 여기서 point-in-time 위반(미래 데이터 누출)이 생기면 이후 전체 백테스트/학습 결과가 무효화됨.
