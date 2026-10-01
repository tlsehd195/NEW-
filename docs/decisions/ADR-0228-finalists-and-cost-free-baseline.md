# ADR-0228: Finalists from the point-in-time screen; exam baselines are cost-free buy-and-hold

**Status:** Accepted
**Date:** 2026-10-02
**Deciders:** account owner (asked Claude to finish its open ADR items, 2026-10-01), Claude Code session

## Context

The survivorship-free screen (ADR-0224, PR #202 fixes) is
`docs/research/reports/full-validation-20261001T172810Z.json`: 602
point-in-time S&P 500 names, walk-forward over 2000-01-01..2013-03-21
(76 two-month folds), held-out TEST 2013-03-21..2016-07-11 not run. All
22 candidates are INCONCLUSIVE, PBO 0.43, no Deflated Sharpe above 0.67.
That run predates ADR-0227, so its Sharpe ratios use 0%; nothing below
depends on Sharpe levels.

Reading it exposed a problem with the baseline. The default cost model
charges $1 per order (`TransactionCostModel.fixed_per_trade`). With
$10,000 spread equal-weight over hundreds of names, each position is
about $20, so the commission is about 5% of it. The net `buy_and_hold`
paid a median $357 per fold (3.6% of capital) and trailed SPY in 89% of
folds, while its gross version beat SPY slightly. The factor candidates
hold few names and pay about $18 per fold. Any "beats the same-names
buy-and-hold, net vs net" comparison therefore mostly measured the
baseline's commissions. ADR-0225's exam verdict was exactly that
comparison, and no exam has been taken, so fixing it now changes no
result anyone has seen.

ADR-0222 says the held-out TEST runs once, for a short list of finalists.
The script could only run it for every candidate at once.

## Decision 1: the baseline is the cost-free buy-and-hold

A candidate's net result is compared with the same-names equal-weight
buy-and-hold's **gross** result (no commission, no spread, no slippage),
the stand-in for a cheap equal-weight index fund. This is stricter for
the candidate than the old rule. `unseen_exam.verdict_against_buy_and_hold`
implements it and is used by the ADR-0225 exam and by the held-out
verdict below; either run failing the integrity checks is INVALID.

## Decision 2: finalists, fixed before any held-out run

Rule, applied to the PIT walk-forward folds above, candidate net against
buy-and-hold gross, fold by fold: (a) median difference above 0, (b) more
than half the folds ahead, (c) the folds chained together compound above
the buy-and-hold. Five candidates clear all three:

| candidate | median fold lead | folds ahead | chained annual, net | DSR |
|---|---|---|---|---|
| high_volume_return_premium | +0.87% | 57% | 9.2% | 0.26 |
| low_beta | +0.78% | 58% | 10.3% | 0.67 |
| illiquidity | +0.48% | 51% | 11.9% | 0.26 |
| max_effect | +0.31% | 54% | 8.0% | 0.49 |
| price_delay | +0.17% | 53% | 11.4% | 0.38 |

Buy-and-hold gross chains to 7.4% a year over the same folds. Of the
ADR-0214 factors, price_delay is a finalist; frog_in_the_pan and
intermediate_momentum trail the buy-and-hold and are dropped.
fifty_two_week_high fails (c). The leads are small and none clears the
DSR bar, so these are the least-bad candidates, not validated ones.

## Decision 3: the held-out TEST runs for named finalists only

`run_long_horizon_validation.py --held-out-candidates a,b` backtests the
held-out TEST only for those names and `buy_and_hold`, and adds
`verdict_vs_buy_and_hold` (Decision 1) to each finalist's
`held_out_test`. Walk-forward and PBO/DSR still cover every candidate, so
the trial count behind DSR is unchanged. Unknown names are refused.
`run_full_validation.yml` gets `final_exam_candidates` and refuses
`final_exam` without it.

The finalists' held-out run is the PIT screen's configuration with
`final_exam=true` and the five names above. After it, 2013-03-21..
2016-07-11 is added to `strategy_research.locked_windows`, as ADR-0222
requires. Caveat: earlier 203-name runs already covered 2013-2016, so for
those names this window is not fresh; ADR-0225's exam on post-2016
unseen names remains the stronger test.

## Consequences

- Earlier reports' "net buy_and_hold" numbers understate an equal-weight
  holding by its commissions; read the gross column for that baseline.
- The ADR-0225 exam, when taken, uses Decision 1.
- Tests: `tests/strategy_research/test_unseen_exam.py`
  (`TestVerdict`, `TestCandidateList`),
  `tests/strategy_research/test_run_long_horizon_validation_wiring.py`,
  `tests/deploy/test_run_full_validation_workflow.py::test_final_exam_needs_named_finalists`.

## Result (2026-10-02, workflow run 36902629473)

`docs/research/reports/full-validation-20261001T193219Z.json`, held-out
TEST 2013-03-21..2016-07-11, 602 point-in-time names, Sharpe with the
ADR-0227 risk-free rate. Buy-and-hold gross: CAGR 11.7%, Sharpe 0.96
(SPY 12.4%).

| finalist | net CAGR | net Sharpe | verdict |
|---|---|---|---|
| price_delay | 17.4% | 1.32 | PASS |
| max_effect | 11.6% | 1.15 | FAIL (CAGR) |
| low_beta | 11.1% | 0.99 | FAIL (CAGR) |
| high_volume_return_premium | 9.6% | 0.65 | FAIL |
| illiquidity | 7.2% | 0.50 | FAIL |

price_delay's gain is spread out (56 names, largest share of profit
10%). It still has DSR 0.38 from the screen, so this is one more piece of
evidence, not a validation. The window is now locked as `TEST_4`
(`strategy_research.locked_windows`), so the research window is
2000-01-01..2013-03-21. price_delay alone goes on to the ADR-0225
unseen-names exams on TEST-3, TEST-2 and TEST-1, one window at a time.
