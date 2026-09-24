---
type: entity
title: risk
tags:
  - module
  - phase-8
  - risk
created: '2026-09-24T10:16:57.438Z'
---
## 역할
Phase 8 — 포지션 사이징 + 포트폴리오 리스크 엔진. Decision Agent(Phase 7)와 주문 생성(후속 Phase) 사이에 위치: `DecisionOutput -> PositionSizer -> PortfolioRiskEngine -> RiskCheckedPosition`.

## Phase / 관련 ADR
Phase 8. ADR-0014(포지션 사이징/리스크 엔진).

## 핵심 인터페이스/클래스
- `PositionSizer`(Protocol), `PortfolioRiskEngine`(Protocol) — `DeterministicPortfolioRiskEngine`
- `RiskRepository`(Protocol) / `InMemoryRiskRepository`
- `PositionSizingRepository`(Protocol) / `InMemoryPositionSizingRepository`
- `PositionSizingConfig`, `RiskConfig`

## 경계
BUY/SELL 결정을 구체적 수량으로 변환하고 리스크 한도를 체크 — 실제 주문 실행은 하지 않음(브로커 호출은 `broker`/`orchestration`의 몫).
