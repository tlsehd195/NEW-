# ADR-0155: Corporate action handling for Paper Trading (restart-safe, chronologically-ordered replay)

**Status:** Accepted
**Date:** 2026-09-18
**Deciders:** Claude Code (session continued)
**Related documents:** `docs/decisions/ADR-0154-paper-trading-t-plus-one-fill.md`
(the T+1 fix this task's `run_cycle` insertion point had to be read
against and verified compatible with), `backtest/corporate_actions.py`
/ Phase 2 spec section 8.4 (the SPLIT/DIVIDEND dispatch/parsing logic
reused verbatim, not reimplemented, here), `backtest/engine.py`
(`BacktestEngine.run()`'s own per-checkpoint corporate-action block and
400-day lookback, mirrored exactly), `docs/specifications/
PHASE-15-paper-trading.md` (Paper Trading's own spec)

---

## Context

`backtest/corporate_actions.py`'s `CorporateActionApplier` applies
SPLIT/REVERSE_SPLIT/DIVIDEND/SPECIAL_DIVIDEND corporate actions to a
`backtest.portfolio.PortfolioAccounting` instance and is wired into
`backtest.engine.BacktestEngine.run()`'s per-checkpoint loop. Its own
`_applied: set[str]` (keyed by `action.provenance.source_record_id`)
makes it idempotent WITHIN one process — safe for backtest, which runs
as one long-lived process per run.

Paper Trading (`broker/paper/adapter.py`, `broker/paper/session.py`,
`orchestration/paper_runner.py`) had ZERO corporate-action handling —
confirmed by grep, no reference anywhere in `broker/paper/` or
`orchestration/paper_runner.py`. A real stock split or dividend on any
Paper Trading position would have silently corrupted `PortfolioAccounting`'s
`quantity`/`average_cost` for that position forever (never adjusted),
with mark-to-market/realized-PnL math downstream wrong from that point
on, with no error or warning.

This was not a small gap to close mechanically. Two real hazards had to
be designed around, not just coded past:

### Hazard 1: restart safety

Paper Trading is NOT one long-lived process. `scripts/run_paper_trading_cycle.py`
runs once per day via a scheduled cron invocation, and
`PaperTradingSession.restore()` rebuilds a FRESH `PaperBrokerAdapter`
from scratch every invocation. A fresh `CorporateActionApplier()`
instantiated inside that fresh adapter has an EMPTY `_applied` set every
time — so naively calling `.apply()` each cycle on every corporate
action a real 400-day lookback window returns would re-apply the SAME
split/dividend every single day, forever, silently corrupting the
account on the second and every subsequent cycle that still sees it in
its lookback window.

### Hazard 2: replay order matters — a naive "batch apply all history first" is wrong

`PortfolioAccounting.apply_split`/`apply_dividend` is a silent no-op
against a position that does not exist yet, or that is currently flat
(`if pos is None or pos.quantity == 0: return`). If a restart replayed
every persisted corporate action first, in one batch, before any fill,
a split that occurred while the replay had not yet reached the fill
that actually established the position (chronologically LATER in real
history, even though both are replayed in the same `restore()` call)
would silently no-op and never get retroactively applied — the
position would end up un-split-adjusted, wrong, with no error. Fills
and corporate actions must be replayed in ONE true chronological
sequence, interleaved by their own real timestamps, not as two separate
batches.

## Decision

### 1. A persisted, cross-restart idempotency ledger (`broker/paper/models.py`, `repository.py`, `storage/paper_repository.py`, `storage/schema.py`)

`PaperAppliedCorporateActionRecord` wraps the original `CorporateAction`
directly (same reasoning `PaperFillRecord` already documents for
wrapping `Fill` directly rather than re-deriving an equivalent shape),
plus the real `applied_at: datetime` timestamp it was actually applied
at during a live cycle. `source_record_id` (== `action.provenance.
source_record_id`) is the dedup key — the SAME field
`CorporateActionApplier` already uses for its own in-process set, kept
consistent at the persisted-ledger level.

`PaperCorporateActionRepository` (Protocol) + `InMemoryPaperCorporateActionRepository`
mirror `PaperOrderRepository`/`InMemoryPaperOrderRepository` exactly:
`record()` idempotent on `source_record_id`, `get()`, `list_all()`
sorted by `applied_at`. `DuckDBPaperCorporateActionRepository`
(`storage/paper_repository.py`) mirrors `DuckDBPaperOrderRepository`
the same way, backed by a new `paper_applied_corporate_actions` table
(`storage/schema.py`) with `source_record_id TEXT PRIMARY KEY` — a
direct primary-key dedup, not an append-only sequence like
`paper_fills`, since a corporate action, unlike a fill, must never be
recorded twice at all.

### 2. `PaperBrokerAdapter.apply_corporate_actions` — reuse, not reimplementation

```python
def apply_corporate_actions(self, actions, as_of_time) -> list[str]:
    return self._corporate_action_applier.apply(actions, self._accounting, as_of_time)
```

A thin wrapper around the existing `CorporateActionApplier`, applied to
this adapter's own `self._accounting`. No new SPLIT/DIVIDEND dispatch
or ratio-parsing logic was written — `backtest.engine.BacktestEngine.run()`'s
own logic is reused verbatim. This one method serves BOTH the live
per-cycle call and a restart's replay identically — unlike
`restore_order`/`restore_fill`, it needs no "restore_*"-prefixed twin,
because there is no failure_mode/cash-check logic for a corporate
action to skip re-running.

### 3. `PaperTradingSession.apply_corporate_actions` — the real restart-safety layer

```python
def apply_corporate_actions(self, actions, as_of_time) -> list[str]:
    remaining = [a for a in actions if self._corporate_action_repository.get(a.provenance.source_record_id) is None]
    warnings = self.adapter.apply_corporate_actions(remaining, as_of_time)
    for action in remaining:
        self._corporate_action_repository.record(PaperAppliedCorporateActionRecord(action=action, applied_at=as_of_time))
    return warnings
```

Filters down to actions NOT already in the persisted repository (a real
cross-restart check, not the adapter's in-process set), applies only
those, then persists EVERY one of them regardless of whether `apply()`
returned a warning for it — mirroring `CorporateActionApplier.apply()`'s
own existing contract of adding a key to its `_applied` set even on a
warning/unhandled-type path (e.g. MERGER). This closes Hazard 1: a
second process seeing the same action in its own lookback window is a
guaranteed no-op.

### 4. `PaperTradingSession.restore()` — one merged chronological replay

`restore()` now takes a required `corporate_action_repository`
parameter (like the other three repositories it already takes). After
replaying orders, it merge-sorts `fill_repository.list_all()` (keyed by
`fill.execution_time`) together with `corporate_action_repository.list_all()`
(keyed by `applied_at`) into ONE chronologically-ordered sequence, then
walks it dispatching each item to `adapter.restore_fill(...)` or
`adapter.apply_corporate_actions([action], as_of_time=record.applied_at)`
as appropriate. This closes Hazard 2: a split replayed between the BUY
that established the position and the SELL that closed it lands at
exactly the right moment, because it IS replayed at that moment, not
batched separately. Each corporate action is replayed with its OWN real
`applied_at`, never a collapsed restore-time batch timestamp — so a
replayed dividend's `CashFlowRecord.as_of_time` stays the real
historical moment.

### 5. `orchestration/paper_runner.py::run_cycle` — always applied, every cycle

Inserted right after `session.advance(as_of_time)` and its associated
delayed-fill Trade Journal linking (ADR-0154), but BEFORE this cycle's
own `account`/`portfolio` snapshot — verified against the CURRENT
(already-merged) T+1 sequence, not a stale mental model, per this task's
own instruction to check that explicitly. This ordering means a real
split/dividend that just became available is already reflected in the
very same portfolio state the Prediction/Decision/Sizing/Risk chain
evaluates this cycle, not one cycle late.

`_tracked_security_ids(security_ids, session)` mirrors `BacktestEngine.run()`'s
own `tracked_ids = universe_today | set(portfolio.positions.keys())`
exactly — a corporate action on a security still HELD but no longer
actively traded must still be applied. The lookback window
(`as_of_time - timedelta(days=400)` to `as_of_time`) is the SAME 400
days `BacktestEngine.run()` uses, not a separately invented number.

`PaperRunnerState.corporate_action_warnings: list[tuple[datetime,
tuple[str, ...]]]` mirrors `mark_to_market_missing`'s existing surfacing
contract exactly — appended to only when `session.apply_corporate_actions`
returns a non-empty warning list, read by `scripts/run_paper_trading_cycle.py`
and `scripts/run_multi_strategy_paper_trading_cycle.py` (stdout warning +
report JSON field), the same pattern those scripts already use for
`mark_to_market_missing`.

### 6. CLI wiring

Both `scripts/run_paper_trading_cycle.py` and
`scripts/run_multi_strategy_paper_trading_cycle.py` construct a
`DuckDBPaperCorporateActionRepository` alongside the existing three
repositories and pass it to `PaperTradingSession.restore(...)`.
`src/broker/paper/us_longterm_runner.py` was checked directly (per this
task's own instruction to check it carefully) and needs NO changes: it
never constructs or restores a `PaperTradingSession` itself — it only
receives one as a parameter from its caller
(`run_multi_strategy_paper_trading_cycle.py`, already wired above).

## Consequences

### Positive

- A real stock split or dividend on any Paper Trading position is now
  applied exactly once, ever, regardless of how many daily cycle
  processes see it in their lookback window — closing a real, silent
  corruption bug that had zero test coverage and zero production
  handling before this.
- The exact SPLIT/DIVIDEND dispatch/parsing logic `BacktestEngine.run()`
  already uses is reused, not duplicated — Backtest and Paper Trading
  can never drift apart on how a corporate action is interpreted.
- The replay-ordering fix (`restore()`'s merge-sort) is general: it
  correctly handles a split/dividend occurring before, between, or after
  any number of fills, not just the specific buy-split-sell scenario
  this task's tests exercise directly.

### Negative / Trade-offs

- `PaperTradingSession.restore()`'s signature gained a required
  parameter (`corporate_action_repository`), a breaking change for any
  caller — all in-repo callers were updated as part of this change, but
  an external caller of `restore()` (if any existed outside this repo)
  would need to add it too.
- `scripts/run_multi_strategy_paper_trading_cycle.py`'s `PaperStrategyKind.BUY_AND_HOLD`
  path never calls `run_cycle` at all (it only calls
  `run_buy_and_hold_paper_session` once and then a read-only
  `compute_portfolio_snapshot` per checkpoint) — so a BUY_AND_HOLD
  strategy run through that script still has NO corporate-action
  handling. This is a real, disclosed scope gap, not silently smoothed
  over: the task instructions scoped this change to `run_cycle`
  specifically, and `BUY_AND_HOLD` does not go through it. A future
  session extending corporate-action handling to `BUY_AND_HOLD` would
  need its own explicit step, mirroring `run_cycle`'s new one.
- `CorporateActionApplier.apply()`'s existing "never fabricate a
  fallback ratio/amount" discipline is preserved unchanged (an
  unparseable split ratio or missing dividend amount still produces a
  warning and skips the mutation) — this ADR does not change that
  behavior, only where its warnings are surfaced from from Paper
  Trading's own per-cycle loop.

## Tests

- `tests/broker/paper/test_paper_adapter.py`: new `TestApplyCorporateActions`
  class — a real SPLIT adjusts an existing position correctly, an
  unhandled type (MERGER) produces a warning without crashing, and a
  same-process double-call does not double-apply (the pre-existing
  in-process guarantee, distinct from restart idempotency).
- `tests/storage/test_paper_repository.py`: new `TestPaperCorporateActionPersistence`
  (mirrors `TestPaperOrderPersistence`/`TestPaperFillPersistence` for
  the new DuckDB-backed repository: round-trip, idempotent double-record,
  survives restart, `list_all()` sorted by `applied_at`) and new
  `TestCorporateActionReplayOrdering` covering exactly the three
  scenarios this task centers on: (a) buy → split → sell, replayed via
  `PaperTradingSession.restore()` from a persisted DuckDB store, ends
  with the position correctly fully sold out (not a negative residual
  quantity, which is what the wrong replay order would silently
  produce); (b) a split for a security that never receives any fill —
  no crash, no spurious position created; (c) the same action applied
  from two SEPARATE fresh `PaperBrokerAdapter`/`PaperTradingSession`
  instances backed by the SAME persisted repository (simulating two
  daily cycle processes) — applied exactly once, not doubled.
- `tests/orchestration/test_paper_runner.py`: new
  `TestCorporateActionsAppliedEachCycle` — an unhandled action type
  (MERGER) surfaces a warning via `run_cycle`'s new
  `state.corporate_action_warnings` path without crashing, and a real
  split on a held position is applied before that cycle's own decision
  (quantity doubles at the split's own checkpoint).
- `tests/broker/paper/test_paper_session.py`,
  `tests/storage/test_paper_repository.py`: every pre-existing
  `PaperTradingSession.restore(...)` call site updated to pass the new
  required `corporate_action_repository` parameter.

Full suite re-run clean: see `docs/PROJECT_STATUS.md`'s own session log
for the exact before/after counts.

## Status of Implementation at Time of This ADR

Code, tests, and documentation complete and committed.
