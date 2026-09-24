---
type: entity
title: orchestration
tags:
  - module
  - phase-15
  - orchestration
  - paper-trading
created: '2026-09-24T10:17:21.371Z'
---
## 역할
Phase 15 스펙이 명시적으로 미룬 부분("A real, running Trading Engine loop... this phase builds the simulated broker and its orchestration primitives; wiring them into an always-on scheduled process is a later phase's concern")을 구현하는 합성(composition) 계층 — 페이퍼 트레이딩 루프.

## 핵심 인터페이스/클래스
- `PredictionRepository`/`RegimeRepository`/`DecisionRepository`/`SizingRepository`/`RiskRepository`/`TradeJournalRepositoryLike`(각 Protocol)
- `PaperRunnerState`, `CycleOutcome`
- `PaperStrategyKind`(Enum), `PaperStrategySpec`

## 경계
각 Phase(Predict/Regime/Decision/Risk/TradeJournal)를 사이클 단위로 결합만 함 — 개별 로직을 포함하지 않음. 모듈 크기 작음(5 파일).
