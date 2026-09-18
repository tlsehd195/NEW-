# ADR-0161: Wire `TrendVolatilityStrategy`'s real filter values into `OrderIntent.features`

**Status:** Accepted
**Date:** 2026-09-18
**Deciders:** Claude Code (session continued)
**Related documents:** `docs/decisions/ADR-0153-backtest-strategy-order-intent-features.md`
(closed this same gap for six other `Strategy` implementations and
explicitly disclosed `TrendVolatilityStrategy` as the one deliberate,
deferred residual), `docs/decisions/ADR-0048` (`OrderIntent.features`'s
original context)

---

## Context

ADR-0153 wired real per-security scores into `OrderIntent.features` for
six ranking-based `Strategy` implementations, but explicitly deferred
`strategy_research.trend_volatility.TrendVolatilityStrategy`: its
`_passes_filter` internally computes real numeric values (`moving_average`,
`current_price`, `realized_vol`) to decide a boolean pass/fail, but only
the boolean ever left the method — extracting those values would need a
refactor of `_passes_filter`'s own return shape, judged out of scope for
that session and left for a future one.

`_passes_filter(security_id, as_of_time, data) -> bool` is also called
directly from outside `TrendVolatilityStrategy`, as a plain boolean
`FilterFn`: `strategy_research.signal_ic.bucket_return_analysis` (and its
test, `tests/strategy_research/test_signal_ic.py::TestBucketReturnAnalysis`)
calls `strategy._passes_filter` and uses the return value directly in an
`if filter_fn(...)` check. Changing `_passes_filter`'s return type would
have broken that external boolean-filter contract.

## Decision — a new `_evaluate` computes once, `_passes_filter` stays a bool wrapper

Added `_evaluate(security_id, as_of_time, data) -> FilterEvaluation`
(`passed: bool`, `features: Optional[dict]`), which does the exact same
computation `_passes_filter` already did, and builds `features`
incrementally with exactly what was actually computed before each early
return:

- `len(trend_bars) < 2`, or `moving_average <= 0`: nothing meaningful was
  computed yet -- `features=None`.
- `current_price <= moving_average` (trend check fails): `moving_average`
  and `current_price` were both real and computed -- `features=
  {"moving_average": ..., "current_price": ...}`, `realized_vol` never
  computed so never present.
- `len(vol_bars) < 2` (not enough history to compute volatility): same
  two-key `features` as above.
- Everything computed: `features` carries all three keys, regardless of
  whether `realized_vol <= vol_threshold` ends up `True` or `False` --
  the values were genuinely computed this call either way.

`_passes_filter` is now a thin wrapper, `return self._evaluate(...).passed`
-- its own signature and boolean return are unchanged, so
`bucket_return_analysis` and its tests keep working unmodified.

`generate_orders` computes `_evaluate` once per security in
`self._security_ids` (same as the old single `_passes_filter` call per
security, no new computation), and attaches the result's `features` to
both sides:

- **BUY**: every bought security is, by construction, one that passed
  the filter, so its `features` always carries the full three-key dict.
- **SELL**: a held position whose `security_id` is in `self._security_ids`
  gets whatever `features` its own `_evaluate` call this cycle produced
  (`None`, two keys, or three, per the cases above) -- never a value
  computed in a previous cycle. A held position whose `security_id` is
  NOT in `self._security_ids` was never evaluated this call at all (it
  fell outside the strategy's own universe), so its `features` is `None`
  -- there is no real, actually-computed-this-call value to attach, and
  none is fabricated.

## Consequences

### Positive

- `trade_journal.backtest_adapter.ingest_backtest_result` now produces
  real, non-`None` `DecisionSnapshot.features` for `TrendVolatilityStrategy`
  too, closing the one residual gap ADR-0153 disclosed -- every
  ranking/filter-based `Strategy` in this codebase now feeds the Learning
  Engine real decision-time signal instead of discarding it.
- No new computation: `_evaluate` computes exactly what the old
  `_passes_filter` computed, once per security per call, same as before.
- `_passes_filter`'s external contract (a plain bool, called directly by
  `signal_ic.bucket_return_analysis` and its own tests) is unchanged.

### Negative / Trade-offs

- `generate_orders`'s SELL-side `features` are structurally uneven (`None`,
  two keys, or three keys) depending on exactly where `_evaluate` returned
  for that security this cycle -- a consumer reading `DecisionSnapshot.
  features` for a SELL order from this strategy must not assume
  `realized_vol` is always present, only that whatever key is present is
  real. This mirrors the same never-fabricate discipline
  `orchestration.paper_runner`'s `_prediction_features`/`_regime_features`
  already established (omit a key rather than write it as `None` or a
  placeholder), just applied per-key here instead of per-dict.

## Tests

New `TestOrderIntentFeatures` class in
`tests/strategy_research/test_trend_volatility.py` (5 new tests):
BUY carries all three real values; SELL carries only the two trend
values when the trend check itself fails (no fabricated `realized_vol`);
SELL carries all three when only the volatility check fails; SELL omits
`features` entirely for a held position outside `self._security_ids`;
SELL omits `features` entirely when there isn't even enough history to
compute a moving average. Existing `_passes_filter`-based tests
(`test_signal_ic.py::TestBucketReturnAnalysis`, `test_no_future_leakage.py`,
this file's own `TestTrendAndVolatilityFilters`) pass unmodified, confirming
`generate_orders`'s buy/sell/sizing control flow is behaviorally identical.

Full suite re-run: 3227 passed (up from 3222 at ADR-0159).

## Status of Implementation at Time of This ADR

Code, tests, and documentation complete and committed.
