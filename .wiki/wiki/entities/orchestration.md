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

## Phase / 관련 ADR
Phase 15. ADR-0195(외부 감사 P1-3 수정: BUY_AND_HOLD 리스크 평가를 이 계층으로 이동).

## 핵심 인터페이스/클래스
- `PredictionRepository`/`RegimeRepository`/`DecisionRepository`/`SizingRepository`/`RiskRepository`/`TradeJournalRepositoryLike`(각 Protocol)
- `PaperRunnerState`, `CycleOutcome`
- `PaperStrategyKind`(Enum), `PaperStrategySpec`
- `compute_portfolio_snapshot` — BUY_AND_HOLD 전용, 전체 Predict/Decision/Sizing/Risk 체인 없이 체크포인트별 포트폴리오 평가만 필요할 때 재사용
- `build_buy_and_hold_risk_check`(ADR-0195) — BUY_AND_HOLD의 동일가중 목표치를 실제 `risk.engine.PortfolioRiskEngine`에 넣어 실제 `risk.models.PositionSizingResult`(decision_action=BUY)를 만드는 콜백을 생성. `broker.paper.us_longterm_runner`가 `risk.engine`/`decision.*`를 직접 import할 수 없어서(`tests/broker/test_broker_boundary.py`) 이 함수가 orchestration 쪽에 있음 — broker는 이 함수가 반환하는 콜백만 받음.

## 경계
각 Phase(Predict/Regime/Decision/Risk/TradeJournal)를 사이클 단위로 결합만 함 — 개별 로직을 포함하지 않음. 모듈 크기 작음(5 파일). 단 `build_buy_and_hold_risk_check`처럼 broker 경계 제약 때문에 이 계층에 놓인 로직도 있음(ADR-0195).
