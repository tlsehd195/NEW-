---
type: entity
title: baseline
tags:
  - module
  - phase-4
created: '2026-09-24T10:16:46.050Z'
---
## 역할
Phase 4 — 베이스라인 전략 실행/리포팅. 다른 전략들의 성능을 비교할 기준선을 제공.

## 핵심 인터페이스/클래스
- `BaselineRunResult`, `BaselineComparisonReport`

## 경계
`backtest.strategy.Strategy` Protocol을 구현하는 가장 단순한 참조 구현 — 모듈 크기가 작음(3 파일).
