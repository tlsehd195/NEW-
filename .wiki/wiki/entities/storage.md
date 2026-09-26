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


## 스키마 변경과 기존 DB
`init_schema`는 `CREATE TABLE IF NOT EXISTS` 뒤에 추가형 마이그레이션을 실행한다(ADR-0211). DDL에 새로 추가된 **nullable** 컬럼은 기존 DB 테이블에 `ALTER TABLE ... ADD COLUMN`으로 자동 추가되고(기존 행은 NULL), **NOT NULL** 컬럼이 빠져 있으면 백필 값을 추측하지 않고 `RuntimeError`로 멈춘다. 컬럼 타입 변경/이름 변경/삭제는 자동 처리되지 않으므로 별도 마이그레이션이 필요하다.
