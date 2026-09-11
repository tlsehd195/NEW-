# ADR-0007: Transaction Cost & Slippage Model for Phase 2

**Status:** Accepted
**Date:** 2026-08-24
**Deciders:** Claude Code (Phase 2 session), pending project owner review
**Related documents:** `PROJECT_MASTER_PLAN.md` §13.2, §17.1 (Almgren &
Chriss), `docs/specifications/PHASE-2-backtesting.md` §7

---

## Context

`PROJECT_MASTER_PLAN.md` §13.2 requires backtests to account for
commission, spread, slippage, and (structurally) market impact, and
warns against arbitrarily assuming optimistic cost values as
representative performance. Phase 2 needs a concrete, minimal cost model
now — but `PROJECT_MASTER_PLAN.md` §17.1's research foundation includes
Almgren & Chriss's optimal execution work specifically for this
purpose, and §17
of the Phase 2 initialization instruction requires applying only what is
"직접 필요한" (directly needed) from that foundation, not a full
implementation of it.

## Decision

1. **Commission**: `fixed_per_trade + per_share * quantity_filled`,
   both configurable, both defaulting to small non-zero values so a
   default-configuration backtest is never accidentally cost-free.
2. **Spread**: modeled as a configurable half-spread `spread_bps`
   applied against the reference execution price — buys pay
   `reference_price * (1 + spread_bps/2/10000)`, sells receive
   `reference_price * (1 - spread_bps/2/10000)`.
3. **Slippage**: a `SlippageModel` Protocol with two Phase 2
   implementations:
   - `FixedBpsSlippageModel(bps)` — a constant adverse adjustment.
   - `VolumeScaledSlippageModel(base_bps, impact_coefficient_bps)` — adds
     `impact_coefficient_bps * participation_rate` bps on top of
     `base_bps`, where `participation_rate = quantity_filled /
     bar_volume` (so `impact_coefficient_bps` is the extra cost, in bps,
     at 100% participation) — a larger order relative to that day's
     volume costs proportionally more. This is a deliberately simple
     linear proxy for market impact — **not** a calibrated
     implementation of Almgren & Chriss's optimal execution trajectory
     model (which solves for an optimal trade schedule under a
     temporary/permanent impact decomposition and a risk-aversion
     parameter). Phase 2 takes only the qualitative idea that impact
     should scale with participation rate (order size relative to
     available volume), which is enough to give the cost model the
     right *shape* for a future, more rigorous model to replace without
     changing the `SlippageModel` interface.
4. **Directionality invariant**: both spread and slippage only ever move
   the effective fill price against the trader (worse for buys means
   higher price paid; worse for sells means lower price received). No
   code path in `costs.py` can produce a price more favorable than the
   reference price.
5. **No zero-cost default**: `BacktestConfig`'s default
   `TransactionCostModel`/`SlippageModel` configuration is non-zero.
   Setting all costs to zero is supported (for isolating signal quality
   from execution cost during strategy development) but must be an
   explicit, visible override — recorded verbatim in
   `ExperimentRecord.transaction_cost_config`/`slippage_config` — never
   the default a casual run falls back to.

## Alternatives Considered

- **Implement a full Almgren & Chriss optimal execution solver now**:
  Rejected — Phase 2 has no need for an *optimal* execution trajectory
  (it is not choosing how to slice a large order over time; it fills
  once per order per §6.2 of the Phase 2 spec). Building the full model
  now would be exactly the kind of research-driven scope creep §17 of
  the initialization instruction warns against ("필요한 최소한의 연구만
  반영한다").
- **Zero-cost backtesting as the default, with cost as an opt-in
  feature**: Rejected — directly contradicts `PROJECT_MASTER_PLAN.md`
  §13.2's warning against arbitrarily assuming optimistic cost values
  ("임의로 낙관적인 값을 가정하지 않는다"); making it the default would
  make that the easy, likely-to-be-used path.
- **A single flat "all-in" cost percentage instead of separate
  commission/spread/slippage components**: Rejected — collapsing the
  components would make `PerformanceReport.total_transaction_cost`
  (Phase 2 spec §11) impossible to break down, and would make it harder
  to reason about which component dominates for a given strategy's
  trading pattern (e.g., a low-turnover strategy is commission-dominated;
  a large-order strategy is slippage-dominated) — this diagnostic value
  is worth the small extra bookkeeping.

## Consequences

### Positive

- The cost model is simple enough to unit test exactly (Phase 2 spec
  §16, tests 3-4: hand-computed expected commission/spread/slippage
  values), which matters for a component that directly determines
  whether a strategy's apparent edge survives realistic frictions.
- The `SlippageModel` Protocol means a future, more rigorous
  market-impact model (should the project later need one — e.g., once
  live order sizes are large enough relative to real market volume to
  matter) can be swapped in without touching `FillSimulator`,
  `BacktestBroker`, or anything upstream.

### Negative / Trade-offs

- `VolumeScaledSlippageModel`'s impact coefficient is not calibrated
  against any real market data (Phase 2 has no real data provider yet,
  per Phase 1 ADR-0005) — it exists to prove the interface, not to
  produce a trustworthy impact estimate. Any Phase 2 backtest using it
  should be read as illustrating the mechanism, not as a validated cost
  forecast, until real data and calibration exist.
- Average-cost-basis accounting (Phase 2 spec §8.1) combined with
  per-fill cost tracking means transaction costs are attributed to the
  trade that incurred them but not further decomposed into a
  lot-level cost basis; acceptable for Phase 2's strategy-comparison
  purpose (ADR-0003 already accepted the same trade-off at the data
  layer for a different reason).

## Status of Implementation at Time of This ADR

Implemented in `src/backtest/costs.py`
(`TransactionCostModel`, `SlippageModel`, `FixedBpsSlippageModel`,
`VolumeScaledSlippageModel`), exercised by `tests/backtest/test_costs.py`.
