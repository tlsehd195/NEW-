---
type: concept
title: 프로덕션 안전 및 Kill Switch
tags:
  - architecture
  - safety
  - kill-switch
  - production
created: '2026-09-24T10:18:11.523Z'
---
## 정의
실계좌 라이브 트레이딩으로 가기 전/후 시스템이 스스로를 정지시킬 수 있는 안전장치 계층. `storage.DuckDBKillSwitchRepository`가 영속 상태를 관리하고, `monitoring`이 이상 감지 트리거를 제공하지만 재학습/매매 실행은 직접 하지 않는다.

## 관련 ADR
- ADR-0021: 페이퍼 트레이딩
- ADR-0022: 라이브 트레이딩
- ADR-0023: 프로덕션 안전 리뷰
- ADR-0045: 라이브 안전 정책 결정 (Session 36)
- ADR-0181: 배치 D — 페이퍼 트레이딩 oversell/restart amnesia
- ADR-0182: 배치 E — kill-switch auto-engage 배선
- ADR-0183: 배치 F — 모니터링 프로덕션 배선
- ADR-0184: 배치 G — 워크플로 동시성/타임아웃

## 관련 문서
`docs/operations/LIVE-RISK-POLICY.md`, `docs/operations/LIVE-TRADING-RUNBOOK.md`, `docs/operations/PRODUCTION-READINESS-MATRIX.md`

## 왜 중요한가
2026-09월 배치 감사(batch A~N, ADR-0177~0191)에서 다수의 "fail-open" 취약점(킬스위치 미배선, 모니터링 미배선 등)이 발견되어 순차 수정됨 — 이 영역은 회귀에 특히 민감하므로 새 Phase 추가 시 반드시 기존 킬스위치/리스크 정책과의 상호작용을 재검토해야 함.

## 관련 엔티티
[storage](../entities/storage.md), [monitoring](../entities/monitoring.md), [risk](../entities/risk.md), [orchestration](../entities/orchestration.md)

## See also

- [2026-09 Independent Audit 배치 시리즈](2026-09-independent-audit.md)
