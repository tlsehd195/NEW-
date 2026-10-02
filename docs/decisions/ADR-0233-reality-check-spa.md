# ADR-0233: White Reality Check와 Hansen SPA를 폴드 수익률에 추가

**Status:** Accepted
**Date:** 2026-10-02
**Deciders:** account owner, Claude Code session

## Context

테스트 구간 고갈 조사(`reports/test-window-exhaustion-papers-2026-10-02.md`)의 추천 2번(연구 구간 CPCV)은 폐기했다. 후보 대부분이 폴드마다 학습하지 않는 규칙 기반이라, 폴드를 어떻게 이어 붙여도 경로 수익률이 같아 CPCV가 새 정보를 주지 못한다. 같은 폴드 수익률로 이미 CSCV(PBO)가 돈다. 코드에 없던 다중검정 보정인 White Reality Check(2000)와 Hansen SPA(2005)를 대신 추가한다.

## Decision

- `src/strategy_research/reality_check.py`: 후보별 폴드 초과수익(후보 − `buy_and_hold`, ADR-0228 관례)에 stationary bootstrap(Politis-Romano, 기본 평균 블록 길이 max(2, round(n^(1/3))), 2000회, seed 고정)을 돌려 Reality Check p값과 SPA p값(Hansen 하한 재중심화)을 계산한다. 새 백테스트는 없다.
- `run_long_horizon_validation.py`는 `buy_and_hold`가 후보에 있을 때 `pbo_dsr_result.reality_check`를 리포트에 **추가로만** 기록한다. 증거 등급 분류는 바꾸지 않는다.

## Consequences

- 커밋된 리포트에 소급 적용해 본 값(분석용, 파일은 바꾸지 않음): 2026-09-25 리포트(후보 50개, 2개월 비중첩 폴드 58개)는 RC p=0.000, SPA p=0.000, 최고 후보 altman_z. 2026-10-01T193219Z 리포트(후보 21개, 폴드 76개)는 RC p=0.009, SPA p=0.000, 최고 long_term_reversal. 블록 길이 4/8/16에서도 같은 결론.
- **해석 주의:** altman_z는 이 검정을 통과하는데 held-out TEST에서는 SPY 대비 크게 졌다(ADR-0209). Reality Check는 "K개 중 최고를 골랐다"는 선택 편향만 보정한다. 폴드 평균 초과수익은 위험 조정이 아니고, 연구 구간과 이후 시장의 비정상성(regime 변화)은 보정하지 않는다. 따라서 통과는 홀드아웃 진출 허가가 아니라 "연구 구간 안에서 우연은 아니다" 정도의 필요조건이다.
- 이 값을 증거 등급이나 홀드아웃 진출 게이트로 쓸지는 별도 결정으로 남긴다.
