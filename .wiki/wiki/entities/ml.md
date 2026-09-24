---
type: entity
title: ml
tags:
  - module
  - ml
  - research
created: '2026-09-24T10:17:26.493Z'
---
## 역할
ML 연구 트랙(Track B)의 첫 구체 구현. `docs/research/ML-RESEARCH-PROTOCOL.md`가 정의한 거버넌스(leakage 방지, TRAIN/VALIDATION/TEST 구조, TEST-1 lock, 실험 거버넌스, 의존성 정책)에 구속됨.

## 관련 ADR
ADR-0043(ML-first 모델), ADR-0041(TEST-1 lock 및 ML 연구 트랙).

## 핵심 인터페이스/클래스
- `MLSample`, `TargetSpec`, `FeatureSpec`
- `MLStrategy`(`backtest.strategy.Strategy` Protocol 구현) / `MLStrategyParameters`
- `ModelSpec` / `LinearRegressionModel`

## 경계
ML-RESEARCH-PROTOCOL.md의 TEST-1 lock 규칙을 반드시 준수 — 테스트 세트 누출은 전체 연구 결과를 무효화함.
