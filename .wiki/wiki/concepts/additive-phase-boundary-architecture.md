---
type: concept
title: Additive Phase Boundary Architecture
tags:
  - architecture
  - principle
created: '2026-09-24T10:17:48.943Z'
---
## 정의
이 프로젝트의 핵심 아키텍처 원칙: 각 Phase(모듈)는 이전 Phase의 소스 코드를 **수정하지 않고 재사용만** 하며, 자신의 책임 범위를 벗어난 산출물(특히 주문/브로커 호출/리스크 변경)을 만들지 않는다.

## 왜 필요한가
`PROJECT_MASTER_PLAN.md`가 정의한 전체 파이프라인(Data → Backtest → TradeJournal → Storage → Regime → Predict → Decision → Risk → Learning → Counterfactual → Evolution → AIGateway → Broker → Monitoring → PaperTrading → LiveTrading)이 20개 가까운 독립 모듈로 쪼개져 있는데, 하위 Phase 변경이 상위 Phase를 깨뜨리지 않도록 각 Phase 경계에서 "무엇을 하지 않는가"를 명시적으로 강제한다.

## 실제로 관찰되는 패턴
- `predict`: "Produces expected_return/... — never an order"
- `decision`: "Never creates orders, quantities, or broker calls"
- `regime`: "independent of Prediction/Decision/Risk"
- `counterfactual`(Phase 10): "Entirely additive: no Phase 1-9 module is imported for modification, only for reuse"
- `evolution`(Phase 11): "fully additive... no Phase 0-10 source file[가 수정됨]"
- `monitoring`: "지속적 관찰, 이상 감지, 피드백 트리거" O, "모델 재학습 자체 실행" X
- `orchestration`: Phase 15 스펙이 "always-on scheduled process로 wiring하는 건 후속 Phase 몫"이라고 명시적으로 범위를 미룸

## 관련 ADR
ADR-0001(마스터 아키텍처)이 이 원칙의 근간. 각 Phase별 ADR(ADR-0002~ADR-0020대)이 개별 구현.

## 관련 엔티티
[predict](../entities/predict.md), [decision](../entities/decision.md), [risk](../entities/risk.md), [counterfactual](../entities/counterfactual.md), [evolution](../entities/evolution.md), [monitoring](../entities/monitoring.md), [orchestration](../entities/orchestration.md)
