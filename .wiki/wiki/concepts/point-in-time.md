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

## 관련 ADR
- ADR-0004: point-in-time 데이터
- ADR-0033: 실데이터 소스 결정 트리
- ADR-0037: S&P500 point-in-time membership
- ADR-0038: momentum window trim fix
- ADR-0040: non-finite value 데이터 품질 체크
- ADR-0032: 보안 식별자(security identity) 및 survivorship-aware 유니버스

## 관련 엔티티
[data_infra](../entities/data-infra.md), [regime](../entities/regime.md), [backtest](../entities/backtest.md)(BacktestClock)
