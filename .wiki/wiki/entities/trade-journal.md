---
type: entity
title: trade_journal
tags:
  - module
  - phase-3
created: '2026-09-24T10:16:40.114Z'
---
## 역할
Phase 3 — 거래 기록/사후분석. 모든 결정·체결을 감사 가능한 형태로 기록하고, 사후 분석(post-trade analysis)과 대안 결과(alternative outcome) 추적을 제공.

## Phase / 관련 ADR
Phase 3. ADR-0009(trade journal 데이터 모델).

## 핵심 인터페이스/클래스
- `TradeJournalRepository`(Protocol) / `InMemoryTradeJournalRepository`
- `TradeRecord`, `DecisionSnapshot`, `PostTradeAnalysis`, `AlternativeOutcome`
- `DecisionAction`(Enum), `TradeProvenance`(Enum), `CorrectionTargetType`(Enum)
- `IngestSummary`

## 경계
읽기 전용 기록 계층 — `learning`, `counterfactual` 등 후속 Phase가 이 데이터를 소스로 소비하지만, trade_journal 자체는 주문/브로커 로직을 갖지 않음.
