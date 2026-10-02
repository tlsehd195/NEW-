# ADR-0232: 누적 시험 횟수 장부로 Deflated Sharpe 보조 계산

**Status:** Accepted
**Date:** 2026-10-02
**Deciders:** account owner, Claude Code session

## Context

테스트 구간 고갈 논문 조사(`reports/test-window-exhaustion-papers-2026-10-02.md`)에서, Deflated Sharpe의 N이 "한 번 실행의 후보 수"뿐이라 과거 실행에서 시험한 후보가 벌점에 반영되지 않는다는 점이 확인됐다(Harvey-Liu-Zhu 2016, Bailey 외 2014는 지금까지 시험한 전부를 세라고 한다).

## Decision

- `src/strategy_research/trial_ledger.py` 추가: 커밋된 `full-validation-*.json`의 `pbo_dsr_result.deflated_sharpe_by_candidate`에 등장한 모든 후보 이름을 누적 장부로 보고, 이번 실행에 없는 이름 수를 `zero_sharpe_trials`(ADR-0220 관례)로 넣어 DSR을 다시 계산한다. 별도 상태 파일은 없다.
- `run_long_horizon_validation.py`는 리포트에 `cumulative_deflated_sharpe_by_candidate`와 `cumulative_num_trials`를 **추가로만** 기록한다. 증거 등급 분류기가 쓰는 기존 DSR은 바꾸지 않는다.
- 과거 후보의 샤프는 저장돼 있지 않아 0으로 취급한다. 따라서 누적 DSR은 근사치다.

## Consequences

- 판정 기준(t>3 등)은 바꾸지 않았다. 누적 DSR을 판정에 쓸지는 값이 쌓인 뒤 별도로 결정한다.
- 이름이 바뀐 후보는 새 시험으로 중복 집계될 수 있다(보수적 방향).
- 로컬/구버전 리포트에 후보가 없으면 장부는 비어 있고 결과는 기존 DSR과 같다.
