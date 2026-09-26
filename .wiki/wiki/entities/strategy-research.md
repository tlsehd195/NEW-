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
Phase 23. ADR-0029(전략 연구 프레임워크). 참고: `docs/research/STRATEGY-RESEARCH-REPORT.md`, ADR-0035(PBO/Deflated Sharpe 구현), ADR-0190(Alpha101 재구현), ADR-0104(institutional_ownership_change_score, 13F 전체 filer 집계), ADR-0194(guru_consensus_score, 13F 특정 filer 추적 — 학술 인용 아님, 계정 소유자 본인 아이디어로 명시), ADR-0207(purgedcv 독립 교차검증 배선).

## 핵심 인터페이스/클래스
- `CandidateClassification`(Enum), `PromisingCriteria`, `CandidateEvaluation`
- `Alpha101Spec` (Alpha101 팩터 재구현)
- `LongTermMomentumStrategy` / `LongTermMomentumParameters`
- `RankAverageEnsembleStrategy` / `RankAverageEnsembleParameters`
- `ResearchLog`, `EvidenceLevel`(Enum)
- `pbo_dsr.compute_pbo`/`compute_dsr_for_all_candidates`(ADR-0035) — CSCV 기반 Probability of Backtest Overfitting/Deflated Sharpe Ratio. 폴드를 `num_groups`(기본 8)개 연속 블록으로 나눌 때 나머지를 마지막 그룹에 몰아주는 방식(다른 라이브러리인 `purgedcv`는 앞쪽 그룹에 분산 — 논문 자체가 나머지 처리 방식을 규정하지 않아 둘 다 정당한 선택, ADR-0207에서 51종목/58폴드 실데이터로 두 구현을 직접 교차검증해 PBO 7.1%p 격차의 정확한 원인으로 확인·문서화됨. DSR은 0.0014 이내로 일치 — 독립 검증 통과).
- `factor_scores.py`: ~54개 팩터 함수(2026-09-26 ADR-0214로 가격 기반 3개 추가, 개별 나열 안 함, 전량 ingest 지양 원칙). 예외적으로 `guru_consensus_score`는 이 프로젝트에서 학술 인용 없이 "계정 소유자 본인 아이디어"로 명시적으로 문서화된 드문 사례라 여기 기록 — `data_infra.tracked_institutional_filers`의 point-in-time registry를 읽음.

## 경계
가장 큰 전략 모듈(20+ 파일) — `backtest` 엔진을 재사용만 하고 자체 실행 엔진은 없음.
