---
type: entity
title: backtest
tags:
  - module
  - phase-2
  - backtest
created: '2026-09-24T10:16:36.820Z'
---
## 역할
Phase 2 — 백테스팅 엔진. 브로커 체결 타이밍, 거래비용/슬리피지 모델, 벤치마크 비교, 무결성 검증을 담당.

## Phase / 관련 ADR
Phase 2. ADR-0006(백테스트 브로커 체결 타이밍), ADR-0007(거래비용/슬리피지 모델), ADR-0008(검증 프로토콜), ADR-0026(벤치마크 수익률 타입).

## 핵심 인터페이스/클래스
- `BenchmarkEngine` / `BenchmarkResult`
- `TransactionCostModel`, `SlippageModel`(Protocol) — `FixedBpsSlippageModel`, `VolumeScaledSlippageModel`
- `BacktestClock` (point-in-time 시뮬레이션 시계)
- `BacktestIntegrityChecker` / `IntegrityReport` / `IntegrityIssue`

## 경계
`strategy_research`, `baseline`, `ml` 등 상위 전략 모듈이 공통으로 재사용하는 `Strategy` Protocol의 실행 엔진 — 전략 로직 자체는 포함하지 않음.
