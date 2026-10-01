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


## 무위험수익률 (ADR-0227)
Sharpe/Sortino는 평가 구간의 평균 3개월 국채 금리(FRED `DGS3MO`)를 무위험수익률로 쓴다 — `backtest.risk_free.RiskFreeRates`. 연구 검증은 매크로 저장소(`--risk-free-db-path`), 페이퍼 리포트는 FRED API(`--risk-free-from-fred`)에서 읽는다. DSR/PBO는 원시 fold 수익률이라 영향 없음. 현금 이자는 붙이지 않음. 상장폐지 ERROR 게이트는 보유 종목의 마지막 SecurityMaster를 기억해서 판단하고, 마지막 종가로 평가된 종목은 제외한다.
