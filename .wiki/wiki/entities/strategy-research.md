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



## 봉인된 시험 구간 (locked_windows, RULE 0.8)
`locked_windows.py`에 등록된 구간은 어떤 새 전략의 TRAIN/VALIDATION/TEST로도 다시 쓸 수 없다: TEST_1(2023-04-28~2026-08-27, ADR-0041), TEST_2(2020-08-28~2023-04-28, ADR-0209), TEST_3(2016-07-11~2020-08-28, ADR-0222), TEST_4(2013-03-21~2016-07-11, ADR-0228: 결승 후보 5개의 held-out, price_delay만 PASS. 이어서 본 TEST-3 새 종목 시험에서는 price_delay FAIL, TEST-2/TEST-1 새 종목 시험은 다음 후보용으로 미사용). `earliest_locked_window_start()`가 스크립트 기본 `--end`를 정한다(현재 2013-03-21). ADR-0222부터 `run_long_horizon_validation.py --skip-held-out`(워크플로 `final_exam=false` 기본값)로 스크리닝 실행은 held-out TEST를 건드리지 않고, 후보를 좁힌 뒤 한 번만 `final_exam=true`로 시험한 다음 그 구간을 봉인한다. ADR-0228부터 `final_exam`에는 `final_exam_candidates`(스크립트 `--held-out-candidates`)가 필수라 held-out은 지정한 결승 후보와 buy_and_hold만 응시하고(walk-forward·PBO/DSR은 전체 후보 그대로), 각 후보에 `verdict_vs_buy_and_hold`가 붙는다.



## 봉인 구간의 유일한 예외: 새 종목 시험 (unseen_exam, ADR-0225)
`unseen_exam.py` + `run_long_horizon_validation.py --unseen-names-exam TEST-n --exam-candidates a,b` (워크플로 입력 `unseen_names_exam`/`exam_candidates`). 봉인 구간에서 한 번도 평가하지 않은 S&P 500 편입 이력 종목만으로(ADR-0224 point-in-time 유니버스 − 이름 붙은 연구 유니버스 − SPY − 그 구간과 겹치는 `docs/research/reports/*.json`의 `security_ids`), 미리 정한 최종 후보만, 구간당 한 번 시험한다. 기준은 같은 종목의 균등 매수보유(ADR-0223)이며, 후보의 순(net) CAGR과 순 Sharpe가 매수보유의 **비용 없는(gross)** CAGR·Sharpe를 둘 다 이겨야 PASS다(ADR-0228: $1/주문 수수료 때문에 수백 종목 매수보유의 net은 수 % 손해라 기준선으로 부적합). 리포트가 커밋되면 그 구간의 재시험은 거부되고 그 종목들도 "본 종목"이 된다. PASS는 "반쯤 새로운" 결과일 뿐 DSR 검증이 아니다.
