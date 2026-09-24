---
type: entity
title: decision
tags:
  - module
  - phase-7
created: '2026-09-24T10:16:54.275Z'
---
## 역할
Phase 7 — 결정 에이전트. Prediction + Regime + Portfolio State + Risk State를 결합해 BUY/SELL/HOLD/EXIT/NO_TRADE를 산출 — 주문/수량/브로커 호출은 절대 만들지 않음.

## Phase / 관련 ADR
Phase 7. ADR-0013(결정 에이전트).

## 핵심 인터페이스/클래스
- `DecisionAgent`(Protocol) — `BaselineRuleDecisionAgent`
- `DecisionRepository`(Protocol) / `InMemoryDecisionRepository`
- `DecisionOutput`, `DecisionConfig`

## 경계
Prediction/Regime/Risk 출력을 조합만 함 — 포지션 크기 결정은 `risk` 모듈(Phase 8)의 몫.
