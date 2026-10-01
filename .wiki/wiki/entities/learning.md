---
type: entity
title: learning
tags:
  - module
  - phase-9
created: '2026-09-24T10:17:00.294Z'
---
## 역할
Phase 9 — 학습 엔진. `Experience -> Data Cleaning -> Labeling -> Training Dataset -> Candidate Training -> Evaluation` 파이프라인. Trade Journal/Experience Dataset(Phase 3/4)을 읽기 전용 소스로만 사용.

## Phase / 관련 ADR
Phase 9. ADR-0015(학습 엔진).

## 핵심 인터페이스/클래스
- `DataCleaningConfig`, `LabelConfig`, `SplitConfig`, `SamplingConfig`, `TrainingDatasetConfig`
- `TrainingDatasetRepository`(Protocol)
- `Evaluator`, `DatasetBuildResult`

## 경계
새 주문/브로커/리스크 변경 경로를 만들지 않음 — 오직 CANDIDATE 상태 모델 아티팩트만 생성(실전 승격은 `evolution` 모듈의 몫).


## 오염 체결 제외 (ADR-0227)
`DataCleaner`는 체결 가격의 기준 봉이 결정 시점에 이미 공개돼 있던 거래(같은 봉 체결, ADR-0154/0226)를 `fill_priced_on_decision_bar`로 INVALID 처리한다. 근거는 `Fill.reference_bar_available_time`이며, 이 필드가 없는 과거 체결은 판별하지 못하고 통과한다.
