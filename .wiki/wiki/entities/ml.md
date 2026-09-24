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
ML 연구 트랙(Track B). `docs/research/ML-RESEARCH-PROTOCOL.md`가 정의한 거버넌스(leakage 방지, TRAIN/VALIDATION/TEST 구조, TEST-1 lock, 실험 거버넌스, 의존성 정책)에 구속됨. 6개 팩터 스코어를 입력으로 미래 수익률을 예측하는 모델을 실험.

## 관련 ADR
ADR-0043(ML-first 모델, `ml_ols`/`ml_ridge` 도입), ADR-0041(TEST-1 lock 및 ML 연구 트랙), ADR-0087(정규화 강화 + 데이터 확장 재실행), ADR-0192(비선형 모델 `ml_tree` 추가).

## 핵심 인터페이스/클래스
- `MLSample`, `TargetSpec`, `FeatureSpec`
- `MLStrategy`(`backtest.strategy.Strategy` Protocol 구현) / `MLStrategyParameters` — `model_builder`로 모델 패밀리 교체 가능
- `LinearRegressionModel`(선형, `ml_ols`) / `select_ridge_via_expanding_window_cv`(`ml_ridge`)
- `RegressionTreeModel`/`BaggedTreeModel`(비선형, `ml_tree` — bagged shallow CART 트리 앙상블, ADR-0192)

## 실제 결과 (2026-09-24 기준)
`ml_ols`/`ml_ridge` 둘 다 실제 데이터로 walk-forward/PBO/DSR 파이프라인을 통과 못 함(CANDIDATE 기준 60% fold 미달, 53~58%대) — `docs/research/STRATEGY-VALIDATION-REPORT.md` 참고(살아있는 최신 소스). `ml_tree`는 코드/테스트만 완성, 아직 실 데이터로 미실행(이 세션 네트워크 차단 확인됨) — 계정 소유자의 실행이 다음 단계.

## 경계
ML-RESEARCH-PROTOCOL.md의 TEST-1 lock 규칙을 반드시 준수 — 테스트 세트 누출은 전체 연구 결과를 무효화함. `ml_tree`의 하이퍼파라미터는 CV 탐색이 아니라 사전 고정(작은 표본 크기에서 탐색 자체가 또 다른 multiple-comparisons 위험이 되는 걸 피하기 위함).

## 알려진 문제
`ML-RESEARCH-PROTOCOL.md`는 다른 문서들처럼 과거 히스토리 리셋 시점 스냅샷에서 멈춰있던 이력이 있음(2026-09-24에 발견·수정됨) — 실제 최신 상태는 `STRATEGY-VALIDATION-REPORT.md`를 신뢰할 것.
