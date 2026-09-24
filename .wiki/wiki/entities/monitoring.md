---
type: entity
title: monitoring
tags:
  - module
  - phase-14
  - monitoring
created: '2026-09-24T10:17:17.395Z'
---
## 역할
Phase 14 — 모니터링/관측성. PROJECT_MASTER_PLAN.md 3절 모듈 테이블: "Monitoring/Drift Detection | 지속적 관찰, 이상 감지, 피드백 트리거 | 모델 재학습 자체 실행(X)" — 관찰과 트리거만 하고 실행은 하지 않음.

## Phase / 관련 ADR
Phase 14. ADR-0020(모니터링).

## 핵심 인터페이스/클래스
- `MonitoringConfig`, `MonitoringComponent`(Enum)
- `MonitoringEventRepository`/`ComponentHealthRepository`/`DriftResultRepository`/`AlertRepository`(각 Protocol + InMemory 구현)

## 경계
드리프트 감지·알림만 하고 모델 재학습이나 킬스위치를 직접 실행하지 않음 — 실행 주체는 다른 모듈(운영 레벨).
