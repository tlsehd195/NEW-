# ADR-0038: Fix lookback-window dilution in momentum/moving-average/volatility signal calculations

**Status:** Accepted

## Context

Earlier this session, at the user's explicit request, this codebase was
compared line-by-line against `gs-quant`'s `timeseries` module
(`moving_average`, `volatility` in `gs_quant/timeseries/technicals.py`
and `econometrics.py`). Two findings were identified and deliberately
**deferred** rather than applied immediately, specifically to avoid the
appearance (or reality) of tuning strategy logic in reaction to the
40-symbol real walk-forward result that was in flight at the time
(RULE 0.8). That result has since completed and been recorded
(`docs/research/STRATEGY-VALIDATION-REPORT.md`, "40-Symbol
(RESEARCH_UNIVERSE Stage 2) Re-Validation"); this ADR documents
applying the first of the two deferred findings now that doing so.

## The bug

`long_term_momentum.py`, `risk_controlled_momentum.py`, and
`trend_volatility.py` each fetch a lookback window like:

```python
lookback_days = self._params.lookback_months * TRADING_DAYS_PER_MONTH
bars = data.get_bars(security_id, as_of_time - timedelta(days=lookback_days * 2), as_of_time)
```

`strategy_research/_dates.py`'s own docstring for
`TRADING_DAYS_PER_MONTH` is explicit that the `*2` (or `*1.6` for the
volatility/trend filters) multiplier exists **only to size the query
generously enough to guarantee `lookback_days` trading days are present
after accounting for weekends/holidays** -- it was never meant to
define the actual signal window. But the un-trimmed code then used
`bars[0]` (the earliest bar in that whole padded fetch) as the momentum
window's start price, and `trend_volatility.py`'s moving average
averaged every close in the padded fetch. Since a padded fetch reliably
returns *more* than `lookback_days` trading days once a backtest is
more than a few months into its data history, every one of these
signals was silently computed over roughly 1.4-1.6x more trading days
than each strategy's own `lookback_months`/`trend_lookback_months`/
`vol_lookback_days` parameter documents -- a real mismatch between
documented intent and actual behavior, not a design choice, and not
something any test previously caught (no existing test asserted the
window's exact trading-day span).

gs-quant's `moving_average`/`volatility` both operate on a precisely
window-sized rolling series (`Window(w.w, 0)`), which is what surfaced
the discrepancy in the first place.

## Decision

Added `strategy_research._dates.trim_to_lookback(bars, lookback_days)`:
trims an already-padded, ascending-by-timestamp bar list down to its
most recent `lookback_days + 1` entries (or returns it unchanged if it
has fewer). All three strategies now pass their padded `get_bars(...)`
result through this before using it as the actual signal window:

- `long_term_momentum.py` / `risk_controlled_momentum.py`:
  `_momentum_score`'s start/end price window.
- `risk_controlled_momentum.py`: `_realized_vol`'s window.
- `trend_volatility.py`: both the moving-average window and the
  volatility-filter window.

This is treated as a **correctness fix** (implementation now matches
each strategy's own documented parameter), not a tuning change: no
parameter *value* (`lookback_months`, `vol_lookback_days`,
`vol_threshold`, `max_position_weight`, `top_n`, etc.) was touched,
only the window the existing parameter was already supposed to define.

## Why this is applied now without violating RULE 0.8

The finding was identified and its application deliberately deferred
*before* the 40-symbol result existed, specifically to keep the
40-symbol result's own evidentiary value uncontaminated by a
mid-flight logic change (see the deferral note in
`STRATEGY-VALIDATION-REPORT.md`'s PBO addendum discussion). Applying it
now, after that result is already recorded, does not retroactively
change what was measured -- the 16-symbol and 40-symbol PBO/DSR/
held-out-TEST numbers already in this project's history remain exactly
what the un-fixed code produced, honestly labeled as such. What this
ADR does NOT do: re-run any strategy against the 2023-2026 held-out
TEST window and present that as new evidence. That window has already
been observed once (by the un-fixed strategies); evaluating the
corrected strategies against it now would be evaluating against an
already-seen TEST set, which this project's own train/validation/TEST
discipline forbids regardless of which specific defect motivated the
change. Any future evidence about these three strategies' corrected
behavior requires a fresh TRAIN+VALIDATION walk-forward and a
not-yet-observed TEST window.

## Consequences

- `_realized_vol`/momentum/moving-average signals for these three
  strategies now measure the trading-day span their own parameters
  claim, rather than a diluted ~1.4-1.6x-wider one.
- One existing test's expected numeric value changed as a direct,
  expected consequence:
  `test_signal_ic.py::TestComputeIcSeriesAgainstRealMomentumScore::
  test_a_confounding_third_security_can_produce_a_partial_ic`
  (`LongTermMomentumStrategy._momentum_score` against synthetic
  fixtures) went from `mean_ic=0.5` to `mean_ic=-1/6` -- still a
  partial (non-extreme) IC, consistent with that test's own purpose,
  just a different exact value under the corrected window. Updated in
  place with an explanatory comment rather than treated as a
  regression.
- 5 new tests for `trim_to_lookback` itself
  (`tests/strategy_research/test_dates.py`). Full suite: 1828/1828
  passing.
- No new dependency; no change to `PositionSizingConfig`/
  `RiskConfig`/order-generation code paths outside these three
  strategies' own signal-computation methods.
- The second deferred gs-quant finding (a "NaN guard" gap) is **not**
  addressed by this ADR -- it needs its own separate, independently
  re-verified diagnosis before being applied, rather than being bundled
  into this fix on the strength of an old, pre-compaction recollection
  of what it was.
