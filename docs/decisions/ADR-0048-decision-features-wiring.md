# ADR-0048: Wiring a Strategy's decision-time rationale (`features`) through to the Experience Dataset

**Status:** Accepted
**Session:** 36

## Context

The user asked directly (in chat, not as a written instruction section)
whether academic literature exists behind this project's "record a
trade's rationale, then retrain from it" design (ADR-0015's Learning
Engine). That question led to grounding the design in the reinforcement
learning / meta-labeling literature (ADR-0015's own "Related literature"
section, added earlier this session). The user then asked what it
would take to actually apply that literature, and specifically what
building "a real trainer" (replacing `learning.trainer.
MeanRewardBaselineTrainer`, which predicts a constant, never learns
from features) would mean.

Answering that question required tracing, end to end, where a
`DecisionSnapshot`'s `features` field actually comes from and where it
actually goes. That trace found **two separate, real bugs** -- not
hypothetical gaps, but silent no-ops in already-shipped code -- that
together meant `features` had never once reached a `LabeledSample` or
a training run, for any strategy this project has ever backtested.

## The two bugs found

### 1. No `Strategy` had any way to attach `features` to an order at all

`backtest.strategy.OrderIntent` (the only type any `Strategy.
generate_orders` implementation returns) had no `features` field.
`backtest.orders.Order` (what `OrderIntent` becomes after
`OrderSimulator.create` validates it) had none either. Even a
hypothetical future Strategy wanting to record "I bought this because
momentum_score=0.8" had no field to put that in -- the plumbing did
not exist.

### 2. Even with (1) fixed, `DecisionSnapshot.features` was silently dropped on the way into the Experience Dataset

`trade_journal.experience.build_experience_records` -- the function
that turns Trade Journal records into the `ExperienceRecord`s
`learning.dataset.build_training_dataset` actually reads -- builds
`ExperienceRecord.state` as:

```python
state={
    "market_state": decision.market_state if decision is not None else {},
    "portfolio_state": decision.portfolio_state if decision is not None else None,
},
```

`decision.features` is never referenced. This is the second half of
the same failure: even if bug (1) were fixed and a `DecisionSnapshot`
somehow had a populated `features` field, this function throws it away
before it ever reaches `state` -- the only thing `Labeler`/`Trainer`
ever see. No test in `tests/trade_journal/test_experience.py` asserts
on `state`'s exact shape, which is why this was never caught: there
was no negative-space test proving `features` (or anything else not
already in the dict) survives.

**Combined effect**: "record the rationale, then retrain from it" had
a rationale-recording field (`DecisionSnapshot.features`) that was
correctly typed, correctly documented, and completely unreachable from
either end -- no producer could set it (bug 1) and no consumer could
read it even if one did (bug 2). ADR-0015's own "Related literature"
section (added earlier this session) was therefore grounding a design
whose central data flow did not actually work yet.

## Decision

Fix both gaps, additively, with zero behavior change for any existing
Strategy (none of which set `OrderIntent.features` today, so every
existing test and every existing strategy's journal output is
byte-for-byte unchanged):

1. **`backtest.strategy.OrderIntent`**: add `features: Optional[dict]
   = None`.
2. **`backtest.orders.Order`**: add `features: Optional[dict] = None`;
   `OrderSimulator.create` copies `intent.features` through on every
   return path -- REJECTED (all three rejection reasons) and PROPOSED
   alike, so a rejected order still carries its rationale into the
   journal (useful for later analysis of why a signal didn't result in
   a trade, not just why one did).
3. **`trade_journal.backtest_adapter.ingest_backtest_result`**: pass
   `features=order.features` into `journal.record_decision(...)`.
4. **`trade_journal.experience.build_experience_records`**: add
   `"features": decision.features if decision is not None else None`
   to the `state` dict.
5. **`storage.serialization.order_to_dict`/`dict_to_order`**: also
   round-trip `features`, so `DecisionSnapshot.order.features` survives
   a DuckDB persist/reload identically to `DecisionSnapshot.features`
   itself (the two are separate copies of the same data by
   construction -- `order.features` is nested inside the persisted
   `DecisionSnapshot`, not derived from it on read).

No `Strategy` in this codebase (`BuyAndHoldStrategy`,
`SimpleMomentumStrategy`, `LongTermMomentumStrategy`,
`RiskControlledMomentumStrategy`, `TrendVolatilityStrategy`,
`LeverageStrategy`, `ml_strategy`'s ML-based strategies) was modified
to actually populate `OrderIntent.features` -- deciding what a
strategy's "rationale" should contain (e.g., which of the 17
literature-backed factor scores from `strategy_research.factor_scores`
to attach) is a real design decision that belongs with building an
actual `Trainer`, not bundled silently into a plumbing fix. This ADR
closes the pipe; it does not decide what flows through it.

## Why this is a plumbing fix, not a tuning decision (RULE 0.8)

RULE 0.8 forbids tuning or selecting a strategy/factor after seeing
its result. This change touches none of that: no factor's formula, no
strategy's order-generation logic, no walk-forward result, no IC
value. It makes a previously-dead data channel actually deliver data
end to end -- a correctness fix to infrastructure that predates any
real experience flowing through it (no live/paper trading has produced
real journaled decisions yet), not a response to an observed result.

## Tests

9 new tests, all additive/regression-shaped:

- `tests/trade_journal/test_backtest_integration.py::
  TestOrderFeaturesReachTheExperienceDataset` (2 tests): a
  feature-carrying `OrderIntent` survives into
  `DecisionSnapshot.features` after a real `BacktestEngine` run +
  `ingest_backtest_result`; and survives further into
  `ExperienceRecord.state["features"]` via
  `build_experience_records`.
- `tests/storage/test_trade_journal_persistence.py::
  TestPersistenceAndRestart::
  test_order_features_and_decision_features_both_survive_restart`:
  both copies (`DecisionSnapshot.features` and
  `DecisionSnapshot.order.features`) independently survive a DuckDB
  close/reopen round trip.

Full suite: 2174 passed (up from 2171).

## What this does NOT do

- Does not build a real `Trainer` -- `MeanRewardBaselineTrainer` is
  unchanged, still predicts a constant. This ADR only makes it
  possible for a future real trainer to have something to learn from;
  it does not build that trainer.
- Does not decide what any Strategy's `features` should contain, or
  modify any existing Strategy to populate it. That decision (e.g.
  "use the momentum/quality/value scores from `strategy_research.
  factor_scores`") is deliberately left open, matching RULE 0.8: no
  strategy has a VALIDATED result yet, so there is nothing to
  responsibly wire in as "the" rationale today.
- Does not implement meta-labeling, experience replay as an RL
  algorithm, or any of the other literature ADR-0015 now cites --
  those remain future work, this ADR only removes the specific
  structural blocker (a two-part silent no-op) that would have made
  any of them meaningless to build on top of as they stood.
- Does not change `learning/`'s own code at all -- the fix is entirely
  upstream of it, in `backtest`/`trade_journal`/`storage`.
