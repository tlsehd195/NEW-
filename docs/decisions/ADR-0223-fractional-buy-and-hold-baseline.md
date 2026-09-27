# ADR-0223: Fractional, fully invested buy-and-hold research baseline

**Status:** Accepted
**Date:** 2026-09-27
**Deciders:** account owner (asked to fix the known weaknesses), Claude Code session

## Context

The `buy_and_hold` candidate in `run_long_horizon_validation.py` and
`run_first_real_strategy_evaluation.py` is the equal-weight reference
baseline. It was mostly cash, for two reasons in `BuyAndHoldStrategy`:

1. **Whole shares.** $10,000 over the 203-name `RESEARCH_UNIVERSE_STAGE5`
   is about $48 a name. `math.floor(48 / price)` is 0 for every name
   priced above that, so those names were never bought.
2. **Names without a price kept their slice.** The cash was divided by
   the full symbol count, including names with no bar at the buy
   checkpoint (later IPOs such as GOOGL, V, META, TSLA on a 2000 start).
   Their slices stayed cash for the whole run.

A third issue appears once the first two are fixed: the default cost
model charges $1 per trade, so 203 buys cost $203, more than the 2%
(`COST_SAFETY_MARGIN`) reserve on $10k. The last orders would be
rejected for cash.

The post-ADR-0219 report `full-validation-20260927T091846Z.json` shows
the symptom: `buy_and_hold` median fold return about 0.0% and DSR 0.014.

## Decision

- `BuyAndHoldStrategy` gains `fractional=False` and
  `cost_safety_margin=None` keyword arguments. With `fractional=True`
  it buys fractional shares and splits the cash only across names that
  have a price at the buy checkpoint. The default stays whole shares,
  so no other caller changes (paper trading uses its own
  `run_buy_and_hold_paper_session` path, not this class).
- `backtest.strategy.buy_and_hold_baseline(security_ids,
  initial_capital, cost_model)` builds the research baseline:
  fractional, with margin `2% + n * fixed_per_trade / initial_capital`
  (about 4% for 203 names). The strategy still never sees the cost
  model; the factory owns that knowledge.
- Both validation scripts use `buy_and_hold_baseline`.

## Consequences

- `buy_and_hold` results before this ADR understate an equal-weight
  buy-and-hold of the universe. They are not comparable with results
  after it.
- Fractional shares are an idealisation for this baseline only. Alpaca
  supports them, so it is not unrealistic for the paper account size.
- The factor candidates keep whole shares. With `top_n=10` they size
  about $1,000 a name, so the same rounding loss is small, but a name
  priced above that (for example AMZN or GOOGL before their splits) is
  still skipped. Not changed here.
- Tests: `tests/backtest/test_buy_and_hold_fractional.py`.
