# ADR-0097: Trade Journal write side wired into Paper/Live orchestration and the Paper CLI

**Status:** Accepted
**Session:** 36 (continued)

## Context

While implementing ADR-0096's read-side reentry-cooldown wiring, a
deeper, previously-undiscovered gap surfaced: `orchestration.
paper_runner.run_cycle` and `orchestration.live_runner.run_cycle` had
never populated `trade_journal.models.TradeRecord` at all in their
production code paths. `session.submit()` already returns real fills
(`tuple[PaperFillRecord, ...]` for Paper, a `BrokerOrderResponse` for
Live) but `run_cycle` discarded them (`_fills` was an unused variable
in Paper; Live never attempted to reconstruct a `Fill` at all). The
bridge functions that convert a real fill into a `TradeRecord`
(`broker.paper.journal.build_trade_record`, `broker.live.journal.
build_fill_from_broker_response`) already existed but were called
nowhere in `src/` outside their own test files. This meant ADR-0096's
own read-side (`last_exit_time_by_security` via `list_trades`) would
always see an empty journal in any real run -- the reentry-cooldown
check could never actually fire, silently.

## Decision

**`orchestration.paper_runner.run_cycle`**: `trade_journal_repository`
(already added in ADR-0096 for the read side) is widened to a full
read+write Protocol (`TradeJournalRepositoryLike`, adding `record_trade`
alongside `list_trades`). After `session.submit()`, every real
`PaperFillRecord` returned is persisted via `trade_journal_repository.
record_trade(decision_id=decision.decision_id, fill=fill_record.fill,
position_after=<cumulative running quantity>, provenance=PAPER_TRADING)`.
`position_after` is derived arithmetically (starting `current_quantity`
plus each fill's signed quantity in order) rather than re-queried from
the broker -- correct for a partial-fill sequence without an extra
session call.

**`orchestration.live_runner.run_cycle`**: identical shape, its own
copy of the widened Protocol (no cross-import, per this module's
existing discipline). When `session.submit()` reports a real
FILLED/PARTIAL_FILLED `BrokerOrderResponse`, `broker.live.journal.
build_fill_from_broker_response` reconstructs a `Fill` and `record_
trade` persists it the same way, `provenance=LIVE_TRADING`.

**A real, documented cross-system linkage limitation, stated rather
than hidden**: `TradeRecord.decision_id` is set to `decision.
decision_id` -- a `decision.models.DecisionOutput`'s own ID (Phase 7),
already persisted separately via `decision_repository` when supplied.
It is NOT a row in the Trade Journal's own `decisions` table (Phase 3's
`DecisionSnapshot`), since neither module calls `record_decision` on
`trade_journal_repository`. The link is real and factual ("which
decision produced this trade") but not joinable back through
`trade_journal.repository.get_decision`. Building that second bridge
was judged out of scope here -- nothing in this codebase currently
needs that join, and fabricating a placeholder `DecisionSnapshot` to
paper over the gap would be worse than documenting it plainly.

**`scripts/run_paper_trading_cycle.py`** (the one real CLI entry point
that drives `paper_runner.run_cycle` in production): now always
constructs and passes a real `storage.trade_journal_repository.
DuckDBTradeJournalRepository(store_engine)` -- unconditional, unlike
`--reentry-cooldown-days` below, since the Trade Journal itself has no
"off" switch, only the risk limit that reads it does. No ID-seeding
logic was needed for it (unlike `next_prediction_id`/`next_decision_id`/
etc.'s own Python-counter seeding) -- `DuckDBTradeJournalRepository`
allocates `trade_id`/`decision_id` sequences via DuckDB's own
`nextval('trade_id_seq')`, which persists correctly across separate
process invocations against the same `--paper-store` file without any
extra bookkeeping. A new `--reentry-cooldown-days` flag (default
`None`, matching every other ratified-but-not-defaulted risk limit)
sets `RiskConfig.reentry_cooldown_days`, now included in both the
report and the reproducibility checksum (mirroring `--max-sector-weight`'s
own precedent -- a run's risk config is a real determinant of its
outcome).

## What this does NOT do

Does not build the second bridge closing the Phase 3/Phase 7 decision-ID
linkage gap described above. Does not add an equivalent CLI flag/wiring
to any Live-trading entry point -- no such CLI script exists yet in this
codebase (Live activation remains gated by the Toss capability gap,
`TOSS-API-GAP-ANALYSIS.md`). Does not decide which `exit_reason` values
should count toward the cooldown -- unchanged from ADR-0093/ADR-0096,
this wiring counts any full exit. Does not run the shadow-evaluation
harness (ADR-0094) against this now-real wiring.

## Tests

`tests/orchestration/test_paper_runner.py::TestTradeJournalWriteSide`
(3 tests) and `tests/orchestration/test_live_runner.py::
TestTradeJournalWriteSide` (3 tests): a filled BUY is recorded as a
real `TradeRecord` with the correct side/quantity/decision_id/
position_after/provenance; a rejected order writes nothing; omitting
`trade_journal_repository` changes no behavior. `tests/orchestration/
test_run_paper_trading_cycle_cli.py` gains two tests: a real end-to-end
run populates the Trade Journal with exactly as many `TradeRecord`s as
the report's own `total_orders_with_a_fill` count, and `--reentry-
cooldown-days` is reflected in the report while defaulting to
disabled. The new CLI test needed a longer synthetic catalog
(`_seed_long_catalog`, through 2024-07-31 rather than the pre-existing
`_seed_catalog`'s 2024-04-30) and a later `--start` -- confirmed by
directly instrumenting `run_cycle` that `_seed_catalog`'s own ~85
trading days never produces a single real BUY at any window, because
`RegimeDetector`'s default `RegimeConfig.trend_long_window=100` keeps
TREND permanently `UNKNOWN` until more than 100 real trading days
precede the requested `--start` -- a real, pre-existing property of
every test in that file (none of which had ever asserted a fill
happens before this ADR). Full suite re-run, 2535 tests pass.
