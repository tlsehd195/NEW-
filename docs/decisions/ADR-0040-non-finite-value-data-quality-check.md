# ADR-0040: Add a NaN/Infinity data-quality check

## Context

The second of two gs-quant-comparison findings deferred earlier this
session (ADR-0038 covers the first, the lookback-window trim fix). Per
ADR-0038's own note, it was deliberately not bundled into that fix
since the exact content of this finding predated a context compaction
and needed independent re-verification rather than being applied from
an uncertain recollection.

Re-verified by comparing this codebase against `gs-quant`'s
`timeseries` module: `gs_quant.timeseries` is pandas-based, so
`mean`/`std`/`volatility` all inherit pandas' automatic NaN
propagation/exclusion behavior "for free." This project's own
arithmetic (`backtest.metrics`, every `strategy_research` candidate)
is pure stdlib with no such safety net.

## The gap

`data_infra.quality.DataQualityFramework`'s existing numeric checks all
use plain comparison operators, which are silently `False` against a
NaN:

- `_check_negative_or_zero_price`: `min(open, high, low, close) <= 0`
- `_check_ohlc_consistency`: `high >= max(open, close)` etc.
- `_check_impossible_movement`: `move > _EXTREME_MOVE_THRESHOLD`

Verified directly (new regression test
`test_nan_close_previously_slipped_past_every_other_numeric_check`): a
`PriceBar` with `close=float("nan")` passes `ohlc_consistency` and
`negative_or_zero_price` cleanly (Python's `min`/`max`/comparisons
against NaN do not reliably surface it), yet `PriceBar.__post_init__`
itself has no numeric-field validation (only datetime-awareness
checks), so nothing upstream of this framework would catch it either.
A NaN or +-Infinity price/volume reaching this framework would
previously be silently accepted as PASSED and then propagate through
every downstream computation (portfolio value, Sharpe ratio, momentum
score, ...) without ever raising -- a silent-corruption risk, not just
a cosmetic gap.

## Decision

Added `DataQualityFramework._check_non_finite_values`
(`src/data_infra/quality.py`): checks `open`/`high`/`low`/`close`/
`volume` (and `adjusted_close`/`vwap` when present) with
`math.isfinite()`, flagging any non-finite field as a new
`"non_finite_value"` check at `DataQualitySeverity.CRITICAL` (higher
than `negative_or_zero_price`'s `ERROR` -- a non-finite value is
corruption at the source, not merely an implausible-but-well-formed
reading). Wired into `run()` immediately after
`_check_timestamp_monotonicity`, before the other numeric checks it
complements. Purely additive: no existing check's behavior changed,
`_CHECK_NAMES` gained one new entry.

## Consequences

- Real ingestion (Tiingo/Stooq/local-file-import) that ever produces a
  NaN/Infinity field now fails loudly (`CRITICAL_FAILURE`) at the data
  quality boundary instead of silently corrupting every downstream
  backtest/strategy computation that reads the bar.
- 6 new tests (`tests/data/test_quality.py::TestNonFiniteValueGuard`),
  including a direct regression guard proving the exact prior gap
  (NaN slips past both pre-existing numeric checks). Full suite:
  1834/1834 passing.
- No parameter, strategy, or backtest logic touched -- this is a
  data-quality-boundary fix only, unrelated to and independent of any
  specific strategy's performance, so it carries none of ADR-0038's
  RULE 0.8 TEST-window caveats.
