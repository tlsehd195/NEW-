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
Sharpe/Sortino는 평가 구간의 평균 3개월 국채 금리(FRED `DGS3MO`)를 무위험수익률로 쓴다 — `backtest.risk_free.RiskFreeRates`. 연구 검증은 매크로 저장소(`--risk-free-db-path`), 페이퍼 리포트는 FRED API(`--risk-free-from-fred`)에서 읽는다. DSR/PBO는 원시 fold 수익률이라 영향 없음. 현금 이자는 기본으로 붙이지 않음 (아래 ADR-0229 참고). 상장폐지 ERROR 게이트는 보유 종목의 마지막 SecurityMaster를 기억해서 판단하고, 마지막 종가로 평가된 종목은 제외한다.

## 벤치마크 상대 지표와 현금 이자 (ADR-0229)
`PerformanceReport`에 SPY 대비 `beta`, `tracking_error`, `information_ratio`, `jensen_alpha`가 있다 (`backtest.metrics.benchmark_relative_metrics`, 날짜 기준으로 맞춘 일별 수익률). `BacktestConfig.cash_interest`에 `RiskFreeRates`를 주면 양(+)의 현금에 전날까지의 `DGS3MO` 금리(최대 10일 직전 값 유지)로 매일 복리 이자가 붙는다. 기본은 꺼짐이며, 현재는 `run_macro_filter_validation.py --cash-interest`(워크플로 기본 켜짐)만 사용한다.
