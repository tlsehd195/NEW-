---
type: concept
title: Point in Time 데이터 무결성
tags:
  - architecture
  - data-integrity
created: '2026-09-24T10:17:54.150Z'
---
## 정의
백테스트/학습 시점에 미래 데이터(향후 확정된 재무제표 수정치, 사후 편입/편출된 종목 등)가 누출되지 않도록 보장하는 원칙. 이 프로젝트 전체 검증 결과의 신뢰도를 좌우하는 가장 근본적인 제약.

## 왜 중요한가
`regime` 모듈 docstring: "interpretable, deterministic, point-in-time-safe regime classification". `data_infra`가 survivorship-aware 유니버스(`SurvivorshipAudit`, `TickerMembershipInterval`)를 관리하는 이유도 동일 — 상장폐지/합병된 종목을 사후에 제거하면 생존편향(survivorship bias)이 생겨 백테스트 성과가 부풀려짐.

## 기업활동(분할·배당)의 available_time 규칙 (ADR-0216)
분할/배당의 `available_time`은 `min(ingestion_time, 이벤트 당일 장 마감 20:00 UTC)`이다(`data_infra.provider.corporate_action_available_time`). 예전에는 수집 시각을 그대로 썼는데, 과거를 한꺼번에 백필하면 모든 분할·배당이 "수집한 날까지 모름"으로 가려졌다. 반면 같은 날의 가격 바는 그날 장 마감 시각으로 찍혀 보였다. 그래서 백테스트는 분할 후 원시 가격 하락만 보고 분할은 못 봤다(research-catalogs-v1에서 AAPL 2014년 7:1 분할이 -84% 손실로 계산됨). 기존 카탈로그는 `scripts/repair_corporate_action_available_time.py`로 보정한다.

## 관련 ADR
- ADR-0004: point-in-time 데이터
- ADR-0033: 실데이터 소스 결정 트리
- ADR-0037: S&P500 point-in-time membership
- ADR-0038: momentum window trim fix
- ADR-0040: non-finite value 데이터 품질 체크
- ADR-0032: 보안 식별자(security identity) 및 survivorship-aware 유니버스
- ADR-0216: 기업활동 available_time을 이벤트 당일 장 마감으로

## 관련 엔티티
[data_infra](../entities/data-infra.md), [regime](../entities/regime.md), [backtest](../entities/backtest.md)(BacktestClock)



## Macro data: vintages, not latest values (ADR-0217)

Macro series (CPI, payrolls, PCE) are released with a lag and revised later. A point-in-time read must use the value as published at that time: `DuckDBMacroRepository.get_series_as_of` picks, per observation date, the latest ALFRED vintage whose `available_time <= as_of`. Reading today's FRED value for a past date is a look-ahead bug.
