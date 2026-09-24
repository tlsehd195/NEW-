---
type: concept
title: Walk Forward PBO Deflated Sharpe 검증 프로토콜
tags:
  - architecture
  - validation
  - research
created: '2026-09-24T10:17:59.580Z'
---
## 정의
전략/모델의 백테스트 성과가 과최적화(overfitting)로 인한 우연이 아님을 통계적으로 검증하는 프로토콜. Walk-forward validation, PBO(Probability of Backtest Overfitting), Deflated Sharpe Ratio 세 기법을 결합.

## 관련 ADR
- ADR-0008: 검증 프로토콜(기반)
- ADR-0031: long-horizon walk-forward validation
- ADR-0035: PBO / deflated Sharpe 구현
- ADR-0046: 외부 통계적 교차검증(external statistical cross-checks)
- ADR-0047: 학술 인용 감사(academic citation audit)
- ADR-0041: TEST-1 lock 및 ML 연구 트랙

## 관련 문서
`docs/research/walk-forward-pbo-deflated-sharpe.md`, `docs/research/STRATEGY-VALIDATION-REPORT.md`, `docs/research/ML-RESEARCH-PROTOCOL.md`

## 왜 중요한가
`ml` 모듈이 구속되는 ML-RESEARCH-PROTOCOL.md의 핵심 내용(leakage 방지, TRAIN/VALIDATION/TEST 구조, TEST-1 lock)이 바로 이 검증 프로토콜의 실무 적용. TEST-1 세트 누출은 그동안의 모든 연구 결과를 무효화하는 가장 치명적인 실수로 취급됨.

## 관련 엔티티
[ml](../entities/ml.md), [strategy_research](../entities/strategy-research.md), [backtest](../entities/backtest.md)
