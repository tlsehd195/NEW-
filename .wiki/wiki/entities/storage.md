---
type: entity
title: storage
tags:
  - module
  - phase-4
  - storage
  - source-of-truth
created: '2026-09-24T10:16:43.763Z'
---
## 역할
Phase 4 — 영속 저장 계층. DuckDB + Parquet 기반으로 이전 Phase들이 정의한 Repository Protocol(DataRepository, TradeJournalRepository, ExperimentRepository, ExperienceRepository 등)을 실제 구현.

## Phase / 관련 ADR
Phase 4. ADR-0010(영속 저장 백엔드).

## 핵심 인터페이스/클래스
- `DuckDBKillSwitchRepository`, `DuckDBReconciliationRepository`
- `DuckDBRegimeRepository`, `DuckDBPositionSizingRepository`, `DuckDBRiskRepository`
- `DuckDBPredictionRepository`, `DuckDBTrainingDatasetRepository`, `DuckDBExperienceRepository`
- `StorageConfig`

## 경계
**DuckDB가 이 프로젝트의 진실 공급원(source of truth)** — llmwiki 같은 2차 뷰가 이 계층의 의사결정 경로를 대체하면 안 됨(CLAUDE.md 명시). 다른 모듈들이 정의한 Protocol을 구현만 할 뿐, 비즈니스 로직을 갖지 않음.
