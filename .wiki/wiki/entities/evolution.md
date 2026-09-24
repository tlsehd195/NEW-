---
type: entity
title: evolution
tags:
  - module
  - phase-11
created: '2026-09-24T10:17:06.131Z'
---
## 역할
Phase 11 — 모델 진화(승격/계보 관리). Phase 9 Learning Engine과 Phase 3/10 Trade Journal/Counterfactual 위에 전적으로 additive하게 구축 — Phase 0-10 소스 파일을 수정하지 않음.

## Phase / 관련 ADR
Phase 11. ADR-0017(모델 진화).

## 핵심 인터페이스/클래스
- `TrailingWindowMeanTrainer`
- `ModelStatusTransitionRepository`(Protocol) / `InMemoryModelStatusTransitionRepository`
- `ModelLineageRepository`(Protocol) / `InMemoryModelLineageRepository`
- `ModelStatusTransition`, `ModelLineageRecord`, `CandidateComparison`, `PromotionConfig`

## 경계
CANDIDATE 모델의 승격/강등 상태 전이와 계보만 관리 — 학습 자체는 `learning` 모듈의 몫.
