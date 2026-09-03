# ADR-0046: External cross-checks of this project's hand-rolled statistical machinery (PBO/DSR, Sharpe/max drawdown, Spearman IC, look-ahead guard, data quality checks)

**Status:** Accepted (verification-only, no production code changed)
**Session:** 36

## Context

While waiting on the user's real-data raw-IC results for the 8 built
factor candidates, the user asked for a survey of external open-source
projects that could help this project, then specifically asked to
proceed with whichever of those were immediately actionable without
real market data. Five items qualified: cross-checking this project's
hand-rolled `strategy_research.pbo_dsr` (PBO/DSR), `backtest.metrics`
(Sharpe ratio, max drawdown), and `strategy_research.signal_ic.
spearman_ic` against independent reference implementations
(`purgedcv`, `empyrical-reloaded`, `scipy.stats.spearmanr`), a
property-based (Hypothesis) exploration of the core look-ahead guard,
and a review of `data_infra.quality.DataQualityFramework` against what
a generic schema-validation library (`pandera`) would offer.

**This project has zero numpy/pandas/scikit-learn dependency** --
`pyproject.toml`'s entire dependency list is `duckdb`, `pyarrow`, and
`pytest` (dev). Every statistical module (`pbo_dsr.py`, `signal_ic.py`,
`backtest/metrics.py`) is deliberately hand-written in pure stdlib
Python. This was a conscious choice (see `pbo_dsr.py`'s own module
docstring). Installing `purgedcv`/`empyrical-reloaded`/`hypothesis`/
`pandera` as real project dependencies to run these checks would
reverse that choice for a one-time verification exercise, which is a
worse trade than the value gained.

**Decision**: run all five checks with these libraries installed only
in an isolated `/tmp` virtualenv, never touching `pyproject.toml` or
any committed dependency file. This ADR records the RESULTS of that
verification, not new production code -- no file under `src/` changed
as part of this entry. Verification scripts live only in the session's
ephemeral scratchpad, not in the committed repository.

## Results

### 1. PBO/DSR vs `purgedcv` -- two real, precisely-identified discrepancies found, neither a bug

Synthetic test: 5 candidates x 32 folds, varied mean/vol, seeded.

- **`expected_max_sharpe_under_null` (sr0)**: matched `purgedcv.
  deflated_sharpe_ratio_full(...).sr_star` to `5.55e-17` (floating-point
  noise) -- the Gumbel/extreme-value expected-maximum-order-statistic
  formula (the trickiest part of the whole DSR machinery) is bit-for-bit
  correct.
- **PSR/DSR**: small but real discrepancy, max `2.18e-03` across the 5
  candidates. Root cause found by reading `purgedcv._metrics.
  _sharpe_moments`: `purgedcv` uses `scipy.stats.skew(arr, bias=False)`/
  `kurtosis(arr, bias=False, fisher=False)` -- the BIAS-CORRECTED
  (small-sample-adjusted) sample skewness/kurtosis estimators. This
  project's `_sample_skewness`/`_sample_kurtosis` compute the BIASED
  (plug-in / method-of-moments) estimators directly:
  `sum((x-mean)**3)/n/stdev**3`. Both are legitimate, commonly-used
  conventions for these moments; the original Bailey & Lopez de Prado
  papers do not pin down which correction to use, and this project's
  own `_sample_kurtosis` docstring only specifies raw-vs-excess
  kurtosis, not the bias correction. **Not changed** -- flagged here so
  a future reader does not mistake this for an unexplained numerical
  drift, and so the choice (biased estimator) is understood as
  deliberate-by-omission rather than re-litigated without cause.
- **PBO**: real discrepancy, `0.214286` (ours) vs `0.142857` (purgedcv)
  on the same synthetic data. Root cause found by reading `purgedcv.
  _pbo._aggregate_pbo`: `purgedcv` counts `pbo = mean(logit < 0)`
  (STRICT inequality), while this project's `compute_pbo` counts
  `sum(1 for lam in logits if lam <= 0) / len(logits)` (logit `<= 0`,
  INCLUDING the exact tie at the median). With an odd candidate count
  (5 here), `omega = rank/(n+1)` can land exactly on `0.5` (logit
  exactly `0`) whenever the IS-best candidate ranks exactly at the
  OOS median -- this project's convention counts that boundary case as
  "did not pay off," `purgedcv`'s does not. This only matters for
  smaller candidate pools (an exact-median tie is more likely with
  5-8 candidates than with the much larger pools the original CSCV
  paper's worked examples use); this project's own docstring already
  states the `<= 0` boundary explicitly ("the logit ... is <= 0 exactly
  when the IS-winner's OOS rank is at or below the median"), so the
  convention is intentional, not accidental. **Not changed** -- same
  reasoning as above: a real, understood convention difference, not a
  formula bug, recorded here rather than silently discovered later or
  "fixed" without cause.

### 2. `backtest.metrics` vs `empyrical-reloaded` -- exact match

Synthetic 252-bar price series, seeded.

- `sharpe_ratio`: `1.29842085` (ours) vs `1.29842085` (empyrical) --
  diff `0.00e+00`.
- `compute_max_drawdown`: `-0.12536629` vs `-0.12536629` -- diff
  `6.66e-16` (floating-point noise). (First script attempt passed price
  LEVELS to `empyrical.max_drawdown`, which expects a RETURN series and
  silently overflowed on `cumprod` -- a verification-script bug, not a
  finding; corrected before the result above.)

### 3. `spearman_ic` vs `scipy.stats.spearmanr` -- exact match, including ties

Random 30-security case and a deliberately tie-heavy 5-security case
(the case that actually exercises `rank_average`'s average-rank tie
handling): both matched to `0.00e+00`/`1.11e-16`. `alphalens-reloaded`
uses the same underlying Spearman rank-correlation methodology, so this
scipy cross-check (a simpler, lower-setup-risk path than alphalens's
heavier factor-DataFrame API) covers the same ground.

### 4. Look-ahead guard vs `Hypothesis` -- no leak found in 500 random trials

Property: for any randomly generated set of bars (random `timestamp`/
`available_time` offsets, including bars filed AFTER their own bar
date) and any random `as_of_time` query, `InMemoryDataRepository.
get_bars` must never return a bar whose `available_time > as_of_time`.
500 examples generated by Hypothesis, all passed. This is an
exploratory finding, not a permanent regression test -- see "What this
does NOT do" below for why it was not committed to the suite.

### 5. `DataQualityFramework` vs `pandera` -- no gap found

Reviewed the 15 checks `DataQualityFramework` already runs (duplicates,
timestamp monotonicity, non-finite values, OHLC consistency, negative/
zero price, negative volume, impossible movement, symbol mismatch,
future-dated, stale data, ingestion-precedes-availability, missing
gaps, insufficient coverage, split consistency, dividend consistency)
against what a generic schema-validation library like `pandera`
provides out of the box (column type/range/nullability checks).
`pandera` would not natively know about any of the finance-specific
checks this project already has (split/dividend consistency,
ingestion-precedes-availability is itself a point-in-time-safety check,
not a generic schema property) -- those would have to be written as
custom `pandera` checks regardless, which is exactly what this
project's own framework already is, just not expressed in `pandera`'s
DSL. No adoption recommended; no gap found to close.

## What this does NOT do

- Does not add `purgedcv`/`empyrical-reloaded`/`hypothesis`/`pandera`/
  `scipy`/`numpy` to `pyproject.toml` or any dependency file. This
  project's dependency footprint is unchanged by this ADR.
- Does not change `pbo_dsr.py`'s PBO tie-handling or skew/kurtosis
  estimator convention -- both discrepancies found are understood,
  legitimate alternate conventions, not bugs, and changing tested,
  already-validated statistical code on the basis of a one-off
  cross-check script (rather than a deliberate, separately-reasoned
  decision) is exactly the kind of unreviewed change this project's
  own discipline warns against.
  Reconsider only if a future session has a specific reason to prefer
  `purgedcv`'s conventions (e.g. matching an external published result).
- Does not commit the Hypothesis property-based test to the permanent
  test suite -- doing so would make `hypothesis` a real, lasting `dev`
  dependency (a genuine departure from the stdlib-only-tests
  convention this project has followed throughout), which deserves its
  own explicit decision rather than being folded silently into a
  verification-only ADR. If the user wants permanent property-based
  coverage of the look-ahead guard, that is a separate, explicit next
  step, not implied here.
- Does not change `DataQualityFramework` -- the pandera comparison
  found no gap to close.
