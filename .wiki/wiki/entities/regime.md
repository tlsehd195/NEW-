---
type: entity
title: regime
tags:
  - module
  - phase-5
created: '2026-09-24T10:16:48.577Z'
---
## 역할
Phase 5 — 시장 국면(regime) 탐지. 해석 가능하고 결정론적이며 point-in-time-safe한 국면 분류. Prediction/Decision/Risk와 독립적.

## Phase / 관련 ADR
Phase 5. ADR-0011(시장 국면 탐지).

## 핵심 인터페이스/클래스
- `RegimeDetector`, `RegimeConfig`
- `RegimeRepository`(Protocol) / `InMemoryRegimeRepository`
- `RegimeAxis`, `SubjectKind`, `TrendState` (Enum)
- `RegimeConditionedStrategy`

## 경계
독립 모듈 — Prediction/Decision/Risk를 import하지 않음. 국면 판단만 하고 매매 신호는 만들지 않음.
