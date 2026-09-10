# ADR-0090: RS Rating (O'Neil/IBD Relative Strength) added, wired blind before any real result

**Status:** Accepted
**Session:** 36 (continued)

## Context

The account owner asked for an analysis of an external repository,
`dragon1086/prism-insight` (an LLM-agent-driven US/Korean stock trading
system), compared against this project, and then for a prioritized list
of applicable ideas. `prism-insight` itself has no backtesting rigor --
its own README acknowledges this -- the key philosophical contrast to
this project's RULE 0.8/PBO-DSR discipline. Five items were identified
as applicable regardless of that contrast: (1) RS Rating, (2)
Distribution Days regime signal, (3) a lookahead-bias audit tool, (4) a
reentry-cooldown risk rule, (5) a shadow-evaluation-harness pattern. The
account owner then said "전부 적용" (apply all). This ADR covers the
first item only.

## Decision

Added `strategy_research.factor_scores.rs_rating_score` -- William
O'Neil / Investor's Business Daily's Relative Strength Rating, in its
underlying weighted-return form:

```
RS Rating raw score = 2*R63 + R126 + R189 + R252
```

where `R_n` is the trailing `n`-trading-day simple return, matching
IBD's own quarterly weighting (most recent quarter double-weighted,
each subsequent quarter weighted once). Price-only, uses only data
already in the catalog -- no new data pipeline, unlike the two prior
Session 36 additions (SUE, insider trading).

**Deliberately does NOT apply IBD's own 1-99 percentile-rank transform**,
decided before any result exists rather than after: this project's two
consumers of a factor score -- `compute_ic_series`'s Spearman rank
correlation, and top-N portfolio sorting in `factor_strategy.py` -- are
both invariant to any strictly monotonic transformation of the input
score. Percentile-ranking a score is one such monotonic transform, so
computing it would change no downstream number this project ever
produces; it exists in IBD's own published methodology to make the
score human-readable on a 1-99 scale for retail publication, a purpose
this project has no analogous need for. Recorded here and in the
function's own docstring specifically so this decision cannot later be
read as a result-driven simplification.

Wired into both places every earlier candidate is wired into, before
any real IC or walk-forward result exists for it (RULE 0.8, the same
"wire it in blind" discipline ADR-0051/ADR-0053/ADR-0054/ADR-0084/
ADR-0086 already established): `--strategy rs_rating` in
`compute_signal_ic_from_catalog.py`, and the walk-forward candidate pool
in `run_long_horizon_validation.py` (`_PRICE_FACTOR_CANDIDATES`, the
pool's 33rd candidate, alongside `insider_buying`'s 32nd).

## What this does NOT do

Does not run raw IC screening or walk-forward/PBO/DSR against real
data -- this session's own outbound network has no real price catalog
to query directly; the account owner needs to run
`compute_signal_ic_from_catalog.py --strategy rs_rating` and then a full
`run_long_horizon_validation.py` pass in their own environment before
any real result exists. Does not decide or predict whether
`rs_rating_score` will show a positive raw IC -- stated here, before
that real run, so this ADR cannot later be read as having cherry-picked
the formula or the percentile-rank decision after seeing a result. Does
not implement any of the other 4 `prism-insight`-derived items (tracked
separately).

## Tests

`tests/strategy_research/test_factor_scores.py::TestRsRatingScore` (5
tests, synthetic fixtures only): a security with uniformly higher
trailing returns at every lookback horizon scores higher than one with
uniformly lower returns; the most recent quarter is weighted more than
older quarters (a return concentrated in the most recent 63 days scores
higher than the same total return spread evenly across the full 252
days); fewer than 252 trading days of history returns `None`; a price
bar filed after `as_of_time` is correctly excluded (point-in-time
safety, mirroring every other score in this module); a flat price
series scores exactly zero. `tests/strategy_research/
test_compute_signal_ic_from_catalog_cli.py::test_rs_rating_option_runs_
end_to_end` (CLI wiring, synthetic fixtures). `tests/strategy_research/
test_run_long_horizon_validation_factor_wiring.py` updated: the
5-table candidate-name set grows from 24 to 25 (`rs_rating` added),
duplicate-name and callable-score_fn checks re-verified. Full suite
re-run, 2488 tests pass (RS Rating's own plus every pre-existing test
unaffected).
