# ADR-0153: Wire real per-security scores into `Strategy`'s own `OrderIntent.features`

**Status:** Accepted
**Date:** 2026-09-17
**Deciders:** Claude Code (session continued)
**Related documents:** `docs/decisions/ADR-0141-wire-decision-snapshot-features.md`
(the Paper Trading side of this same gap, closed earlier this session),
`docs/decisions/ADR-0048` (originally documented this gap for
`OrderIntent.features`)

---

## Context

ADR-0141 closed `DecisionSnapshot.features` for Paper Trading's own
`run_cycle` path, but explicitly disclosed the boundary it did not
cross: "Backtest's own `Strategy`/`OrderIntent.features` path (ADR-0048's
original context) remains unfixed — this ADR is Paper Trading's
`run_cycle` only, a different execution path." `backtest.strategy.
OrderIntent.features` (Session 36 plumbing, `Order.features` already
copies it straight through unconditionally to `BacktestResult.orders`,
and `trade_journal.backtest_adapter.ingest_backtest_result` already
reads `order.features` into `DecisionSnapshot.features`) was real
plumbing with a real consumer at both ends — but no `Strategy`
implementation in this codebase ever set it.

Every ranking-based Strategy already computes a real per-security
numeric score to decide `target` before generating orders; none of
them attached it to the `OrderIntent`s they then constructed.

## Decision — attach the real score already computed, omit for a security with none

Six `Strategy` implementations updated, all with the SAME discipline:
attach whatever real score(s) that security's ranking was already
computed from, as `OrderIntent.features`; omit entirely (never
fabricate) for a security whose own score was `None` and therefore
excluded from ranking in the first place:

- `backtest.strategy.SimpleMomentumStrategy` — `{"momentum_score": ...}`
- `strategy_research.leverage_strategy.LeverageStrategy` —
  `{"leverage_score": ...}`
- `strategy_research.long_term_momentum.LongTermMomentumStrategy` —
  `{"momentum_score": ...}`
- `strategy_research.risk_controlled_momentum.
  RiskControlledMomentumStrategy` — `{"momentum_score": ...,
  "inverse_vol_weight": ...}` (the latter only for BUY orders, where
  the inverse-volatility weight is actually computed)
- `strategy_research.ensemble_strategy.RankAverageEnsembleStrategy` —
  `{"leverage_score": ..., "net_margin_score": ...,
  "combined_rank_average": ...}`
- `strategy_research.factor_strategy.{Price,Fundamentals,Hybrid,
  Universe}FactorStrategy` (all four share `_orders_from_target`) —
  `{"factor_score": ...}`

`backtest.strategy.BuyAndHoldStrategy` is deliberately NOT touched: it
has no per-security score or signal at all (equal-weight buy of the
whole configured list), so there is nothing real to attach —
fabricating a feature for it would violate this project's own
never-fabricate discipline, the same reasoning ADR-0141 already applied
to a missing `PredictionOutput` field.

`strategy_research.trend_volatility.TrendVolatilityStrategy` is a
disclosed, deliberate exception: its `_passes_filter` internally
computes real numeric values (moving average, current price, realized
volatility) but only returns a boolean pass/fail — extracting those
into features would need a refactor of `_passes_filter`'s own return
shape, judged out of scope for a "wire up already-computed values" fix
and left for a future session.

## Consequences

### Positive

- `trade_journal.backtest_adapter.ingest_backtest_result` now produces
  real, non-`None` `DecisionSnapshot.features` for every ranking-based
  backtest Strategy in this codebase — the same Learning Engine
  benefit ADR-0141 already delivered for Paper Trading, now also
  available for backtest-sourced experience.
- No new computation anywhere — every attached value is a number the
  Strategy already computed to build `target`/`ranked` before this fix;
  the change is purely "stop discarding it."

### Negative / Trade-offs

- `TrendVolatilityStrategy` remains unwired — a real, disclosed
  residual gap, not silently left unaddressed.
- `BuyAndHoldStrategy` structurally has nothing to attach and stays
  that way permanently, not a gap to revisit.

## Tests

New `TestOrderIntentFeatures` classes (or equivalent) in
`tests/strategy_research/test_leverage_strategy.py`,
`test_long_term_momentum.py`, `test_risk_controlled_momentum.py`,
`test_ensemble_strategy.py`, `test_factor_strategy.py`, plus new
`tests/backtest/test_strategy_order_intent_features.py` for
`SimpleMomentumStrategy` — 6 new tests total, each asserting the real
score value on `BacktestResult.orders[i].features` directly (no
separate Trade Journal ingestion step needed, since `Order.features`
already carries it).

Full suite re-run clean: 3185 passed (up from 3179).

## Status of Implementation at Time of This ADR

Code, tests, and documentation complete and committed.
