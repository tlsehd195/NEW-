# ADR-0154: Paper Trading T+1 fill timing, and the delayed-fill Trade Journal join it requires

**Status:** Accepted
**Date:** 2026-09-17
**Deciders:** Claude Code (session continued)
**Related documents:** `docs/decisions/ADR-0113-decision-snapshot-join-for-paper-trading.md`
(the original "delayed fill is not yet mirrored into the Trade Journal"
disclosed limitation this ADR closes), `docs/decisions/ADR-0137-advance-simulation-wired-into-run-cycle.md`
(wired `session.advance()` into `run_cycle` for stuck-order retry --
this ADR's delayed-fill Trade Journal join extends that same call
site), `docs/specifications/PHASE-15-paper-trading.md` (Paper Trading's
own spec), `src/backtest/engine.py` / ADR-0006 (the T+1 execution
discipline this ADR brings Paper Trading in line with)

---

## Context

`backtest.engine.BacktestEngine` enforces T+1 execution structurally: a
`Strategy` decides at checkpoint `T` using data available `<= T`, and
any resulting order fills at `T+1` using data available as of that
LATER checkpoint (`backtest/engine.py`, ADR-0006). A decision and its
own fill can never share the same bar.

Paper Trading violated this. `orchestration.paper_runner.run_cycle`
computed its decision reference price via `_reference_price(view,
security_id, as_of_time)` (the latest bar `<= as_of_time`), then called
`session.submit(validation.validated_order, requested_at=as_of_time)`.
`PaperBrokerAdapter.submit_order` immediately called `self._attempt_fill
(order.client_order_id, as_of=requested_at)` at the end of the SAME
call, using `get_reference_bar(security_id, as_of=as_of_time)` — the
identical `as_of_time`, and therefore the identical latest-available
bar, the decision itself had just used. Paper Trading decided and
filled off the same bar/price — a same-bar leak, not T+1, unlike
backtest.

Closing this exposed a second, structural problem: `run_cycle`'s own
module docstring already disclosed (ADR-0113) that a delayed fill
`session.advance()` produces for an OLDER order was not mirrored into
the Trade Journal, because nothing could re-locate that order's
original `DecisionSnapshot` without a natural-key-safe lookup. That gap
was tolerable while it was a rare edge case (a partially-filled order
retried on a later day). Once fills are deferred, it stops being an
edge case: EVERY first fill becomes exactly this "delayed fill"
scenario. Fixing fill timing alone, without also closing this gap,
would have silently stopped Paper Trading from ever populating the
Trade Journal — breaking `learning.pipeline.run_learning_pipeline`'s
only real (non-backtest) experience source. The two fixes are one unit
of work: the second is a hard prerequisite the first exposes, not an
independent decision.

## Decision

### 1. Defer the fill (`broker/paper/adapter.py`)

`PaperBrokerAdapter.submit_order` no longer calls `self._attempt_fill`
at the end of submission. An order is always PENDING immediately after
`submit_order` returns. `_attempt_fill` is now called ONLY from
`advance_simulation`, which `orchestration.paper_runner.run_cycle`
already calls at the very top of every cycle (`session.advance
(as_of_time)`) BEFORE that cycle's own decisions are made. An order
submitted in cycle N therefore first attempts a fill in cycle N+1's
`advance()` call, against whatever bar is available as of that LATER
`as_of_time` — the direct Paper Trading analogue of backtest's
`next_checkpoint` fill.

Everything else inside `_attempt_fill` (participation cap, the
insufficient-cash rejection check, TTL cancellation in
`advance_simulation`) is unchanged — it just now only ever runs from
`advance_simulation`, never synchronously from `submit_order`. One
direct, structural consequence: a rejection that used to be visible on
`submit_order`'s own return value (e.g. `insufficient_cash`) is now only
visible after the next `advance_simulation`/`advance()` call, since the
cash check lives inside `_attempt_fill`.

### 2. A natural-key lookup for the Trade Journal

Added `get_decision_by_natural_key(natural_key: tuple) ->
Optional[DecisionSnapshot]` to `trade_journal.repository.
TradeJournalRepository` (Protocol) and `InMemoryTradeJournalRepository`,
to `storage.trade_journal_repository.DuckDBTradeJournalRepository`, and
to `orchestration.paper_runner.TradeJournalRepositoryLike`. Each
implementation reuses the exact key-stringification (or, for the
in-memory case, the exact tuple-keyed dict) `record_decision` already
indexes decisions by, so a lookup by the same natural key `run_cycle`
recorded the decision under always resolves to the same
`DecisionSnapshot` — or `None`, never fabricated, when nothing was ever
recorded under that key.

### 3. Wire delayed fills into the Trade Journal (`orchestration/paper_runner.py`)

Before calling `session.advance(as_of_time)`, `run_cycle` now captures
`pre_advance_account = session.account_summary(as_of=as_of_time)` —
state from BEFORE this cycle's delayed fills land, giving the correct
pre-fill `average_cost`/`quantity` for realized-PnL math (mirroring
exactly what the same-cycle path already does by reading `account.
positions` captured before that cycle's OWN fills).

`session.advance(as_of_time)` now returns `(advance_updates,
advance_fills)`, and `advance_fills` (real `PaperFillRecord`s) are
handed to a new private helper, `_record_delayed_advance_fills`, when
`trade_journal_repository` is supplied. For each fill, it looks up the
originating order via `session.adapter.get_order_record
(fill_record.client_order_id)` to get `record.requested_at`, `record.
validated_order.security_id`, `record.validated_order.experiment_id`,
reconstructs the SAME natural_key tuple the original decision was
recorded under (`("paper_decision", experiment_id, security_id,
requested_at)`), and resolves it via `get_decision_by_natural_key`. A
`None` result (the decision was never recorded — e.g.
`trade_journal_repository` was absent during the original submission)
means the fill is skipped silently: no crash, no fabricated link,
matching this codebase's "never fabricate" convention rather than a
"raise" one. Fills are grouped by `client_order_id` (preserving
`advance()`'s own ordering) and further by `security_id`, so several
orders/fills for the same security in one `advance()` call still share
one running quantity/average-cost/opened-at, exactly like the
same-cycle path already does across fills of a single order.

The realized_pnl/realized_return/holding_period arithmetic itself was
extracted into one shared private helper, `_record_fills_to_journal`,
used by BOTH the pre-existing same-cycle path and the new delayed-fill
path — this is a refactor, not a behavior change, for the same-cycle
path (verified unchanged by the existing passing tests).

### 4. Second-order production-code fixes this exposed

Removing the synchronous fill changed the behavior of two callers that
had, until now, quietly relied on it:

- `broker.paper.us_longterm_runner.run_buy_and_hold_paper_session`
  computed each symbol's equal-weight cash split by re-reading
  `session.adapter.get_account(...).cash` inside its own per-symbol
  loop — correct only because each earlier symbol's order had already
  synchronously debited real cash by the time the next symbol's split
  was computed. With deferred fills, that re-read would return the
  SAME undiminished cash for every symbol, over-allocating by the time
  fills eventually land. Fixed with a local `available_cash` tracker
  that reserves each submitted order's estimated notional
  (`quantity * reference_price`, the same reference price already used
  to size that order — never a new fabricated figure) as it submits
  each symbol, restoring the original equal-weight allocation intent
  exactly.
- `scripts/run_multi_strategy_paper_trading_cycle.py`'s `PaperStrategyKind.
  BUY_AND_HOLD` path called `run_buy_and_hold_paper_session` once on the
  first checkpoint, then only ever called the read-only `compute_
  portfolio_snapshot` per checkpoint — nothing in that path ever called
  `session.advance()`. Before this fix that was harmless (the buy filled
  synchronously); after it, the Buy & Hold order would have stayed
  PENDING for the entire run, and `final_cash` would never move. Fixed
  by calling `session.advance(checkpoint)` at the top of that
  per-checkpoint loop, mirroring what `run_cycle` already does
  internally for the `RUN_CYCLE` strategy path.
- `scripts/run_paper_trading_cycle.py`'s own per-cycle reporting counted
  `total_filled` from `outcome.submission.filled_quantity` — a field
  that is now PERMANENTLY `None` on the same-cycle `BrokerOrderResponse`
  `run_cycle` returns, since a fill (when it lands) can never appear on
  the same-cycle response any more. This silently made the script's own
  "filled so far" count structurally stuck at 0 regardless of how many
  orders actually filled. Fixed to re-derive "filled so far" from each
  submitted order's real, current status (`session.adapter.
  get_order_status`) rather than that now-static field.

## Consequences

### Positive

- Paper Trading now enforces the same T+1 discipline backtest already
  enforces structurally — a decision and its own fill can never share
  the same bar/price, closing a real look-ahead-adjacent leak that made
  Paper Trading's own simulated performance more optimistic than a real
  broker's next-tick execution would be.
- The Trade Journal now correctly receives a real, joinable
  `TradeRecord` for every real fill Paper Trading produces, including
  every delayed one — closing ADR-0113's own disclosed gap rather than
  letting the T+1 fix silently regress it to "no Trade Journal
  population at all."
- Two real second-order bugs in production code (`us_longterm_runner`'s
  equal-weight cash split, and the multi-strategy script's missing
  `advance()` call for Buy & Hold) were found and fixed as a direct
  consequence of reasoning through this change, not left as
  latent regressions.

### Negative / Trade-offs

- A rejection whose cause lives inside `_attempt_fill` (e.g.
  `insufficient_cash`) is no longer visible on `submit_order`'s own
  immediate return value — a caller must call `advance_simulation`/
  `session.advance()` and then check `get_order_status` to observe it.
  This is a real, disclosed latency change to every existing caller's
  contract, not a hidden one.
- A decision made on the very LAST checkpoint of a bounded run (e.g. a
  script's own `--start`/`--end` range) never gets a chance to fill
  within that run, since its first fill attempt needs a NEXT
  checkpoint's `advance()` call that does not exist. This mirrors
  backtest's own equivalent boundary condition (a decision on the last
  checkpoint never reaches `next_checkpoint`), so it is not a new kind
  of gap, but it is a real behavior change for any caller that assumed
  every submission within a finite range eventually fills within that
  same range.

## Tests

- `tests/broker/paper/test_paper_adapter.py`,
  `test_paper_accounting_invariants.py`, `test_paper_session.py`,
  `test_us_longterm_runner.py`, and
  `tests/broker/live/test_production_safety_cross_cutting.py` updated:
  every test that previously asserted an immediate fill from
  `submit_order` now asserts PENDING immediately after submission, and
  FILLED/PARTIAL_FILLED/REJECTED only after an explicit
  `advance_simulation`/`session.advance()` call.
- `tests/orchestration/test_paper_runner.py`: every fill-timing-sensitive
  test rewritten to span two cycles (submit in cycle N, observe the real
  fill after cycle N+1's own `advance()`); a new `TestDeferredFillDecisionJournalLink`
  class adds dedicated coverage for (a) a fresh order staying PENDING
  through its own cycle with no premature `TradeRecord`, (b) the same
  order's next-cycle fill correctly joining its original
  `DecisionSnapshot`, (c) `get_decision_by_natural_key` returning `None`
  gracefully (and `run_cycle` not crashing) for a decision that was
  never recorded, and (d) realized_pnl/holding_period on a delayed-fill
  closing SELL computed correctly.
- `tests/integration/test_paper_learning_readiness_lineage.py`,
  `test_paper_performance_scenarios.py`, `test_paper_trading_lineage.py`,
  `test_paper_trading_real_market_data.py`,
  `test_us_longterm_paper_trading_lineage.py`,
  `tests/storage/test_paper_repository.py` updated the same way, each
  adding an explicit `advance()`/`advance_simulation()` call where a
  fill used to be implicit.
- `tests/orchestration/test_run_paper_trading_cycle_cli.py`: the real
  end-to-end Trade-Journal-population test now runs a slightly wider
  `--end` range so the real BUY it produces has a NEXT checkpoint to
  fill against within the run.
- `tests/orchestration/test_run_multi_strategy_paper_trading_cycle_cli.py`:
  covered by the `_run_buy_and_hold_strategy` production fix above —
  no test changes were needed once the script itself called `advance()`.

Full suite re-run clean: 3190 passed (up from 3185).

## Status of Implementation at Time of This ADR

Code, tests, and documentation complete and committed.
