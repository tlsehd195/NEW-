# ADR-0209: Lock TEST-2 (retroactively) + human review findings on the 51-candidate report

**Status:** Accepted
**Date:** 2026-09-26
**Deciders:** account owner (explicit "팩터에만 집중하자" + "2 3 진행"), Claude Code session

**Related documents:** `docs/decisions/ADR-0041-test-1-lock-and-ml-research-track.md`
(TEST-1, RULE 0.8), `docs/decisions/ADR-0045` (CANDIDATE evidence level
is not a safe signal to skip human review, the `leverage` -26.43%
precedent), `src/strategy_research/locked_windows.py`,
`src/strategy_research/evidence.py`, `docs/research/reports/
full-validation-20260925T160732Z.json` (the report this ADR reviews).

## Context

The account owner asked for a human review of the 2026-09-25
`run_full_validation.yml` report (51 strategy/factor candidates,
RESEARCH_UNIVERSE stage4, 87 symbols, all classified `INCONCLUSIVE`) --
this project's own `strategy_research.evidence.classify_evidence_level`
structurally cannot itself return `VALIDATED`; that requires an explicit
human decision. Four angles were reviewed: (1) the 51 candidates
themselves, (2) whether a locked-window gap exists, (3) whether new
factor ideas should be added, (4) whether the PBO/DSR methodology itself
is trustworthy. This ADR records findings 1 and 2 (both resolved this
session); finding 3 (new S-tier factor search) is tracked separately as
follow-up work; finding 4 (PBO/DSR methodology) needed no action --
`ADR-0207`'s existing cross-check against `purgedcv` already bounds the
known convention-difference at ~7pp, which does not change any
conclusion below (0.186 + 0.07 = 0.256, still comfortably under the 0.5
`MAX_PBO_FOR_CANDIDATE` threshold).

## Finding 1: no candidate should be marked VALIDATED

Of the 51 candidates, exactly 4 reached this project's highest
automated tier, `EvidenceLevel.CANDIDATE` (walk-forward fold-consistency
bar cleared, AND `pbo_probability < 0.5`, AND `deflated_sharpe_ratio >=
0.95`): `altman_z` (DSR 0.998, the single best of all 51),
`rank_average_ensemble` (0.990), `merton_dd` (0.961), and
`asset_turnover_change` (0.957). The other 47 stayed at
`ROBUSTNESS_PENDING` or lower.

Per `ADR-0045`'s own established discipline ("a human must have
reviewed its held-out TEST result specifically, not merely its evidence
label"), each of these 4 candidates' real held-out TEST performance
(2020-08-28..2023-04-28, the `chronological_split.test_*` range) was
inspected directly:

| candidate | walk-forward DSR | held-out TEST net Sharpe | held-out TEST net CAGR | excess return vs. SPY |
|---|---|---|---|---|
| `altman_z` | 0.998 | -0.28 | -11.1% | **-44.5pp** (max drawdown -52.9%) |
| `rank_average_ensemble` | 0.990 | 0.17 | +1.3% | -14.0pp |
| `merton_dd` | 0.961 | 0.04 | -0.6% | -19.2pp |
| `asset_turnover_change` | 0.957 | 0.07 | -0.6% | -19.1pp |

All 4 substantially underperformed SPY on real, held-out data --
`altman_z`, the single best-scoring candidate on the walk-forward folds,
produced the worst held-out result of the four (a real -52.9% maximum
drawdown, worse than the `leverage` precedent ADR-0045 already flagged
at -26.43%). This is the same failure mode recurring, not a new one:
`CANDIDATE` grades walk-forward fold consistency plus a
multiple-testing-adjusted Sharpe, not held-out generalization, and
nothing here contradicts that this project's own gate
(`LiveActivationApproval.strategy_evidence_reviewed`, `src/broker/live/
approval.py`) already treats `CANDIDATE` as necessary, never sufficient.

**Decision: none of the 51 candidates are marked VALIDATED.** No code
change follows from this finding by itself (there is no field to flip
-- `VALIDATED` is a target state a human assigns by *not* proceeding to
build on a candidate, not a database row to update). This is recorded
here as the actual outcome of the human review CLAUDE.md's pending-items
list called for.

## Finding 2 (action taken): TEST-2 lock, added retroactively

`src/strategy_research/locked_windows.py` had only ever recorded
`TEST_1`. The 2026-09-25 report's own held-out TEST range
(2020-08-28..2023-04-28, RESEARCH_UNIVERSE stage4) had already been
observed by all 51 candidates above but was never added to
`LOCKED_WINDOWS` -- per this project's own RULE 0.8 ("once a date range
has been used as the held-out TEST for ANY strategy... that range is
retired... for any future one"), this was a real, if narrow, gap: a
future run (this 87-symbol universe or a different one, any new
candidate) could have silently re-evaluated against this exact
already-seen answer key with nothing to stop it.

`TEST_2` is added, ending exactly where `TEST_1` begins (adjacent, not
overlapping -- both lock independently). `observed_by` lists all 51
candidate names verbatim from the report. `overlaps_any_locked_window`
now correctly refuses (via `scripts/run_long_horizon_validation.py`'s
existing, pre-established refusal check, the same one that already
protects `TEST_1`) any future `[--start, --end]` overlapping either
window -- including a naive re-run of `run_full_validation.yml` with
its original `2010-01-01`/`2023-04-28` inputs, which is exactly the
intended effect (that workflow is `workflow_dispatch`-only with
caller-supplied `start`/`end` inputs, so this does not silently break
any existing schedule).

## Real regression found and fixed while adding TEST-2

Adding `TEST_2` immediately broke 5 existing tests
(`test_compute_signal_ic_from_catalog_cli.py`,
`test_compute_fundamentals_ic_from_catalog_cli.py`,
`test_compute_filter_bucket_returns_from_catalog_cli.py`,
`test_verify_signal_ic_with_alphalens_cli.py`,
`tests/ml/test_train_ml_model_from_catalog_cli.py`) -- not a test-only
fixture problem, a real latent bug these tests correctly caught: each of
the 5 corresponding scripts hardcoded its own default `--end` (used
when the flag is omitted) directly to `TEST_1.start`. That was correct
while `TEST_1` was the only locked window, but `TEST_2.start`
(2020-08-28) is *earlier* than `TEST_1.start` (2023-04-28), so a
caller's default `[start, TEST_1.start)` range now legitimately overlaps
`TEST_2` -- exactly the class of already-observed-data reuse this
project's locked-window guard exists to catch, now correctly firing
against these scripts' own previously-"safe" default for the first
time.

Fixed at the source, not by loosening a test: added
`strategy_research.locked_windows.earliest_locked_window_start()`
(`min(w.start for w in LOCKED_WINDOWS)`) and switched all 5 scripts'
default `--end` to call it instead of naming `TEST_1` directly -- stays
correct automatically if a `TEST_3` is ever added starting earlier than
both, instead of silently reintroducing this exact bug a third time.

## Testing

- `tests/strategy_research/test_locked_windows.py`: added `TestTest2Constant`
  (exact start/end, adjacency to TEST-1, all 51 names present, no
  duplicates), `TestEarliestLockedWindowStart` (returns TEST-2's start,
  and that value itself never overlaps any locked window), and extended
  `TestOverlapDetection` for the two-window case (a range spanning both
  windows flags both; a range fully inside each window flags that one;
  the old single-window assertions kept where still accurate, one
  corrected where a fixture range now also legitimately overlaps
  TEST-2).
- The 5 previously-broken CLI test files: renamed their
  `test_default_end_is_test_1_start_and_is_therefore_safe` tests to
  `..._is_the_earliest_locked_window_start_and_is_therefore_safe`,
  added an explicit `overlaps_any_locked_window(...) == ()` assertion on
  the computed default (not just trusting the CLI's exit code), kept
  each test's original exit-code expectation (all still pass -- the fix
  restores the original "safe by default" property, it does not change
  what "safe" means for these scripts' actual callers).
- Full suite run before merge (branch-merge rule).

## Deferred: new S-tier factor search (finding 3)

Not resolved in this ADR -- `ADR-0107`/`0108`/`0109` (coskewness,
Ohlson O-score, Merton distance-to-default) were the last "keep
searching for S-tier papers" round; no session since has resumed that
search. Tracked as separate follow-up work, not bundled here to keep
this ADR's diff reviewable (locked-window registration and a fresh
factor-literature search are unrelated changes).
