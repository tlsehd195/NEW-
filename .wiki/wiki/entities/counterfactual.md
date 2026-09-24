---
type: entity
title: counterfactual
tags:
  - module
  - phase-10
created: '2026-09-24T10:17:02.803Z'
---
## 역할
Phase 10 — 반사실 분석/성과 귀속(performance attribution). 전적으로 additive — Phase 1-9의 어떤 모듈도 수정하지 않고 재사용만 함(trade_journal.models, trade_journal.analysis, backtest.experiment 등).

## Phase / 관련 ADR
Phase 10. ADR-0016(반사실 귀속).

## 핵심 인터페이스/클래스
- `AttributionRepository`(Protocol) / `InMemoryAttributionRepository`

## 경계
가장 작은 모듈 중 하나(5 파일) — 기존 데이터를 다른 관점에서 재분석만 함.
