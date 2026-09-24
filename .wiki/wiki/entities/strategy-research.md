---
type: entity
title: strategy_research
tags:
  - module
  - phase-23
  - strategy
  - research
created: '2026-09-24T10:17:29.806Z'
---
## 역할
Phase 23 전략 연구 프레임워크. 모든 전략이 기존의 `backtest.strategy.Strategy` Protocol(Phase 2)을 구현 — 새 포트폴리오 실행 경로를 추가하지 않음.

## Phase / 관련 ADR
Phase 23. ADR-0029(전략 연구 프레임워크). 참고: `docs/research/STRATEGY-RESEARCH-REPORT.md`, ADR-0190(Alpha101 재구현).

## 핵심 인터페이스/클래스
- `CandidateClassification`(Enum), `PromisingCriteria`, `CandidateEvaluation`
- `Alpha101Spec` (Alpha101 팩터 재구현)
- `LongTermMomentumStrategy` / `LongTermMomentumParameters`
- `RankAverageEnsembleStrategy` / `RankAverageEnsembleParameters`
- `ResearchLog`, `EvidenceLevel`(Enum)

## 경계
가장 큰 전략 모듈(20 파일) — `backtest` 엔진을 재사용만 하고 자체 실행 엔진은 없음.
