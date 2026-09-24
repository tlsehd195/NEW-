---
type: entity
title: predict
tags:
  - module
  - phase-6
created: '2026-09-24T10:16:51.440Z'
---
## 역할
Phase 6 — 예측 레이어. expected_return/probability/expected_volatility/uncertainty/confidence를 산출 — 주문은 절대 만들지 않음. Decision/Risk/Execution과 독립.

## Phase / 관련 ADR
Phase 6. ADR-0012(예측 레이어).

## 핵심 인터페이스/클래스
- `Predictor`(Protocol) — `RandomWalkPredictor`, `DriftPredictor`, `RegimeAwarePredictor`
- `PredictionRepository`(Protocol) / `InMemoryPredictionRepository`
- `PredictionOutput`, `PredictionMethodType`(Enum), `PredictionConfig`

## 경계
주문/수량/브로커 호출 절대 생성 안 함 — `decision` 모듈이 이 출력을 입력으로만 소비.
