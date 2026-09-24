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
