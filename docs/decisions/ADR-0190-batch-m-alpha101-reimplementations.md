# ADR-0190: Batch M -- 10 Kakushadze "101 Formulaic Alphas" reimplementations

**Status:** Accepted
**Date:** 2026-09-24
**Deciders:** Claude Code (session continued), account owner (asked to
work through `EXTERNAL_REPO_APPLICABILITY_REPORT.md`'s remaining items
in size order after Batches K/L; this is priority 9)

## Context

`EXTERNAL_REPO_APPLICABILITY_REPORT.md` recommends reimplementing 10-20
of Vibe-Trading's `alpha101` factor zoo entries (Kakushadze 2015, "101
Formulaic Alphas," arXiv:1601.00991) as pure Python, citing this
project's own `long_term_momentum.py` as evidence this "reimplement, do
not vendor" pattern already fits. Vibe-Trading's own implementations are
pandas-vectorized panel operations against a cross-sectional universe
(some using `rank()`/industry-neutralization, which need the whole
universe's data at once); this project's `strategy_research` factor
functions are all single-security `ScoreFn`s (`(security_id, as_of_time,
data) -> Optional[float]`), and `src/` stays duckdb+pyarrow-only (no
pandas/numpy per `pyproject.toml`).

## Decision

Add `src/strategy_research/alpha101.py` with 10 alphas selected from
Vibe-Trading's 101, chosen as the subset that (a) needs only OHLCV --
excludes any alpha requiring `vwap`, which this project's providers
rarely populate -- and (b) has no cross-sectional `rank()`/industry
dependency, since this project has no cross-sectional-operator
infrastructure a single-security `ScoreFn` could call into:
`alpha101_006`, `_009`, `_012`, `_023`, `_046`, `_049`, `_051`, `_053`,
`_054`, `_101` (Kakushadze equation numbers).

**Verification discipline**: every formula was read directly from
Vibe-Trading's own source (`agent/src/factors/zoo/alpha101/alpha_NNN.py`,
each citing the same paper equation), not reconstructed from memory --
the same "never reconstruct a cited algorithm from memory alone"
standard `factor_scores.bid_ask_spread_score` already established in
this codebase. Not a copy of Vibe-Trading's pandas code: reimplemented
per-security in plain Python against this project's own
`AsOfDataView`/`PriceBar`.

**Adjusted-price handling** (a design point Vibe-Trading's own
pandas-panel code does not need to make, since it operates on a single
already-adjusted price panel): where a formula compares a raw price
LEVEL across different days, `adjusted_close`/`adjusted_high` is
preferred with a fallback to the raw field, matching every existing
momentum-style factor's own established pattern. Where a formula
computes a same-day ratio of the shape `(a*close - b*low - c*high) /
(close - low)` and only diffs THAT ratio across days (#53/#54/#101),
raw OHLC is used directly and is mathematically identical to using
adjusted prices -- a uniform per-day split-adjustment factor cancels out
of such a ratio, proved in the module's own docstring. `open`/`volume`
have no adjusted counterpart in `PriceBar` at all (#6) -- a
pre-existing schema limitation this module inherits, not introduces.

**`Alpha101Spec`/`ALPHA101_SPECS`**: the report's own recommendation to
adopt Vibe-Trading's `__alpha_meta__` metadata schema, applied as this
project's existing `ml.features.FeatureSpec` convention instead of a
bare dict -- `alpha_id`/`columns_required`/`min_warmup_bars` kept under
the same names as Vibe-Trading's schema for direct cross-reference.

**Not wired into `ml.features`/`signal_ic` in this batch.** These are
standalone, independently tested score functions, matching how
`factor_scores.py`'s own functions started (later phases graduated
individual factors into ML features or full strategies once their real
IC was evaluated against real data -- ADR-0043's own precedent). Real,
non-synthetic evaluation via `signal_ic.compute_ic_series` against this
project's actual data is separate, unscheduled follow-up work, not part
of adding the reimplementations themselves.

## Consequences

### Positive
- 10 well-documented, independently-cited, independently-tested factor
  functions are available for future IC evaluation, at zero new runtime
  dependencies.
- The `Alpha101Spec` registry makes each factor's exact formula, data
  requirements, and warmup independently inspectable without reading
  the implementation.

### Negative / Trade-offs
- No real evaluation of these alphas' actual predictive power (real
  Information Coefficient against real market data) is part of this
  batch -- they are verified for FORMULA correctness (a hand-computed
  reference value per alpha) only, the same "pipeline-validation, not
  real-signal evidence" caveat every other `strategy_research` module's
  tests already carry.
- Only 10 of the paper's 101 alphas are covered here -- the remaining
  ~91 either need `vwap` (rarely populated), cross-sectional `rank()`/
  industry-neutralization (no infrastructure to support it), or were
  simply not selected in this pass; a future session extending this
  module should re-triage Vibe-Trading's full `alpha101/` directory
  rather than assume this batch's 10 are the only OHLCV-only,
  non-cross-sectional candidates.

## Tests

`tests/strategy_research/test_alpha101.py`: a hand-computed reference
value (or a clearly-distinguished categorical branch) per alpha,
insufficient-history-returns-`None` cases, division-by-zero guards for
`#53`/`#54`, a threshold-boundary test that makes `#49` and `#51`
disagree on the same input (proving they are not accidentally
identical), and 4 registry-consistency tests for `ALPHA101_SPECS`.
Verified as real regression guards: temporarily flipped 4 comparison
operators (branch conditions in `#23`/`#46`/`#49`/`#51`) and confirmed
2 of the corresponding tests fail (the other 2 mutations did not cross
any of this test file's specific example values -- a known, disclosed
gap in boundary-exactness for `#46`/`#49`, not a correctness defect);
restored and confirmed all 26 tests pass again. Separately renamed a
function to confirm the registry-consistency test's `hasattr` check
(and the module's own import) catches a missing function.

Full suite run before merge as the merge gate (see PR).

## Status of Implementation at Time of This ADR

Code and tests complete for the 10 alphas listed above. This is Batch
M, following Batches K/L's own priority-ordered work through
`EXTERNAL_REPO_APPLICABILITY_REPORT.md`'s remaining recommendations.
