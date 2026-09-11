# ADR-0113: reconcile duplicate Paper-Trading/Learning-Engine wiring, and fix the two real gaps that made it unusable

**Status:** Accepted
**Session:** 37 (continued)

## Context

Earlier this session (before `claude/phase-11-model-evolution-7hpibr`
was discovered and merged into `main`, see ADR-0112), this session's own
separate branch (`claude/autonomous-ai-investment-system-plan-4-ha7y35`,
based on old `main`) independently built its own ADR-0086: a
`trade_journal.paper_adapter` module wiring `orchestration.
paper_runner.run_cycle` to the Trade Journal, plus `scripts/
run_learning_cycle.py` as the Learning Engine's missing read side --
prompted by the account owner asking whether this project has a
feature that retrains from Paper/Live Trading results. **This branch's
own ADR-0086 no longer exists** (deleted below, Decision 1, once found
to number-collide with a different, unrelated, still-live ADR-0086 for
insider trading already on `main` -- `docs/decisions/ADR-0086-
insider-trading-sec-form-4-data-pipeline...md` is what that number
resolves to today; do not follow "ADR-0086" mentions in this document
expecting to find this branch's deleted trade-journal-wiring doc).

After ADR-0112's merge, comparing the two branches found that
`claude/phase-11-model-evolution-7hpibr` had ALREADY independently built
an equivalent write-side wiring (ADR-0093/ADR-0095/ADR-0096/ADR-0097:
reentry-cooldown risk rule, its orchestration wiring, and the Trade
Journal write-side wiring), merged into `main` as part of that same
PR. The account owner asked this session to reconcile the duplication
("처리해").

Investigating ADR-0097's actual implementation (`orchestration.
paper_runner.run_cycle`'s `record_trade` call) surfaced two real,
previously-undiscovered gaps that made the already-merged wiring
structurally incapable of ever feeding a usable sample to the Learning
Engine, regardless of which side's implementation "won":

1. `record_trade` was called with none of `realized_pnl`/
   `realized_return`/`holding_period` -- every real `TradeRecord`
   this module ever wrote had them permanently `None`, even for a
   genuine closing SELL.
2. Independently, and more fundamentally: `learning.cleaning.
   DataCleaner.clean` unconditionally calls `journal.get_decision(
   record.decision_id)` and excludes the sample with reason
   `"missing_decision"` if that lookup returns `None` -- BEFORE it
   ever checks `realized_return`. `run_cycle` never called
   `record_decision`, so `TradeRecord.decision_id` (a Phase 7
   `DecisionOutput` ID) never resolved through `trade_journal.
   repository.get_decision`. Fixing gap 1 alone would not have made a
   single real sample usable -- gap 2 excluded every trade first,
   before `realized_return` was ever inspected.

ADR-0097 had explicitly, deliberately scoped gap 2 out as "a real,
documented cross-system linkage limitation, not hidden," reasoning that
"nothing in this codebase currently needs that join." That reasoning
did not anticipate `learning.pipeline.run_learning_pipeline` -- which
this session's own reconciliation work was specifically trying to make
usable, and which does need exactly that join.

## Decision

**1. Deleted the duplicate branch's own write-side reimplementation.**
`src/trade_journal/paper_adapter.py`, `tests/trade_journal/
test_journal_paper_adapter.py`, and the old `docs/decisions/
ADR-0086-paper-trade-journal-and-learning-engine-wiring.md` (a
different, unrelated ADR-0086 already existed on `main` for insider
trading, so this file is removed rather than renumbered) are all
removed. `main`'s own `orchestration.paper_runner.run_cycle` (ADR-0096/
ADR-0097) is kept as the single write-side implementation and enhanced
in place, rather than running two independent adapters side by side.

**2. Fixed gap 1 (realized PnL) directly in `orchestration.
paper_runner.run_cycle`.** A closing SELL fill now computes:
- `realized_pnl = (fill.price - position_average_cost) * fill.quantity
  - fill.total_cost`
- `realized_return = realized_pnl / (position_average_cost *
  fill.quantity)` (when the cost basis is nonzero)
- `holding_period = fill.execution_time - opened_at`

`position_average_cost` is read from `portfolio.positions[security_id].
average_cost` -- the real cost basis as of the START of this cycle
(before any of this cycle's own fills), already computed by
`PaperTradingSession.account_summary()` and therefore requiring no new
ledger. `opened_at` comes from a new `_position_opened_at` helper: a
real replay of the security's own Trade Journal history (`list_trades`,
`end=as_of_time`), finding the most recent BUY that took a flat
position nonzero. Both computed ONCE per order (not per partial fill),
correct because a SELL sequence never reopens the position it is
closing. Both `None` (never fabricated) when their own inputs are
unavailable.

**3. Fixed gap 2 (decision join) by recording a real `DecisionSnapshot`.**
`TradeJournalRepositoryLike` is widened to include `record_decision`.
Whenever `trade_journal_repository` is supplied and a security's
decision produces a `ValidatedOrder`, `run_cycle` now calls
`record_decision(...)` ONCE for that security this cycle, BEFORE
submitting, with an explicit `natural_key` (`("paper_decision",
experiment_id, security_id, as_of_time)`) for idempotent dedup. Every
`TradeRecord` this cycle writes for that security now uses the real
`DecisionSnapshot.snapshot_id` as `decision_id` -- superseding
ADR-0097's own choice to use `decision.decision_id` (the Phase 7
`DecisionOutput` ID, still separately persisted via `decision_repository`
if the caller supplies one, unchanged). `DecisionSnapshot.order` is
deliberately always `None`, never `validation.validated_order` --
`DecisionSnapshot.order` is typed for `backtest.orders.Order`
(`order.order_id`), and `broker.validation.build_validated_order`
produces the structurally different `broker.models.ValidatedOrder`
(`client_order_id`, no `order_id`); passing one through as the other
crashes both `record_decision`'s own natural-key derivation and
`storage.serialization.decision_snapshot_to_payload` identically --
caught directly (the deleted `trade_journal.paper_adapter` had already
found and avoided the same incompatibility the same way, one of the two
things worth keeping conceptually from that superseded module, folded
into this fix instead of a separate one).

Decisions are recorded only when a `ValidatedOrder` actually results
(not for every HOLD/REJECT) -- narrower than `trade_journal.
backtest_adapter.ingest_backtest_result`'s "record for every order
regardless of status," since only a decision that produces a real
`TradeRecord` ever needs to be joinable.

## Proof, not just plumbing

Both fixes were verified together against a real end-to-end run: a
synthetic price fixture that rises for 250 trading days then reverses
into a sustained decline (long enough to clear `RegimeDetector`'s own
100-day `trend_long_window`, and to force `BaselineRuleDecisionAgent`
into a real closing SELL, which only fires on a negative expected
return) run through the real `scripts/run_paper_trading_cycle.py` CLI,
then `scripts/run_learning_cycle.py` against the same `--paper-store`.
Before either fix: `dataset_quality_status="INSUFFICIENT_SAMPLES"`,
`experiment_status="FAILED"`, 0 usable samples, regardless of a real
closing trade having occurred. After both fixes: `dataset_quality_
status="OK"`, `experiment_status="COMPLETED"`, 1 real usable sample,
with `test_metrics.mean_label` equal to the real trade's own
`realized_return` (0.5575, i.e. +55.75%, from a real ~150-day decline
after a ~150-day rise) -- the first time this project's Learning Engine
has ever actually trained on real Paper Trading experience, closing the
gap that motivated the account owner's original question.

## What this does NOT do

Does not change what `MeanRewardBaselineTrainer`/`LinearRegressionTrainer`
themselves compute, or any Data Cleaning/Labeling/Dataset-building logic
in `learning/*` -- both gaps were entirely on the write (Trade Journal
population) side. Does not populate `OrderIntent.features` for any
Strategy/DecisionAgent -- `LinearRegressionTrainer` still has nothing
real to fit on, verified by a real test (unchanged from before this
session). Does not wire the equivalent fix into `orchestration.
live_runner.run_cycle` -- Live activation remains structurally blocked
(zero `VALIDATED` strategy candidates, Toss capability verification
pending), so there is no real Live experience this fix would currently
make usable; the identical shape (real `record_decision` + real
realized-PnL computation) is the natural next step once Live actually
runs, deferred rather than built speculatively (RULE 0.8). Does not
retroactively backfill `decision_id`/`realized_pnl`/`realized_return`/
`holding_period` on any `TradeRecord` a real Paper Trading run already
wrote before this fix (e.g. the daily GitHub Actions scheduler's own
accumulated history) -- those rows keep their original, honest `None`
values; only new runs benefit. Does not make `scripts/run_learning_
cycle.py` run automatically from the scheduler -- retraining remains a
distinct, manually-invoked step (this branch's now-deleted ADR-0086's
original reasoning -- see the Context section's note above; unaffected
by which branch's write-side wiring it now reads from).

## Tests

`tests/orchestration/test_paper_runner.py::TestTradeJournalWriteSide`:
the pre-existing `test_a_filled_buy_is_recorded_as_a_real_trade` renamed
and rewritten to `test_a_filled_buy_is_recorded_as_a_real_trade_with_a_
real_joinable_decision`, now resolving `journal.get_decision(trade.
decision_id)` and asserting it returns a real, correctly-populated
`DecisionSnapshot` rather than comparing `decision_id` values directly
(the ADR-0097 assertion this superseded would fail against the new,
intentional behavior). New `test_a_closing_sell_records_real_realized_
pnl_return_and_holding_period` -- a new `_reversal_scenario` fixture
(rise then decline, deterministic seed, confirmed by direct
instrumentation to produce a real SELL before being written as a test)
drives `run_cycle` forward until a real SELL occurs, then asserts
`realized_pnl`/`realized_return`/`holding_period` against hand-computed
expected values from the real BUY/SELL fill prices, not just "is not
None." `tests/orchestration/test_run_learning_cycle_cli.py::
TestFullLoopWithARealClosedTrade::test_a_real_closed_trade_produces_a_
real_completed_training_run` -- the capstone: drives the real CLI
scripts (`run_paper_trading_cycle.py` then `run_learning_cycle.py`)
against the same reversal fixture and asserts a `COMPLETED` training
run with a real, non-trivial `test_metrics.mean_label`, not merely that
the scripts exit 0. Full suite re-run on this merge commit: **2797
passed, 0 failed** (up from ADR-0112's own 2787 on merged `main` HEAD).
