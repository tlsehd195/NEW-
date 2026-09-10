# ADR-0114: third-party full-repository review — 3 confirmed HIGH-severity fixes

**Status:** Accepted
**Session:** 37 (continued)

## Context

The account owner commissioned a second, independent full-repository
review (16 parallel agents reading all 727 tracked files, plus direct
re-verification of HIGH candidates by the report's own author) against
`main` @ `145ea95` (post-ADR-0113). The report reconfirmed all 8
previously-fixed HIGH issues (ADR-0111/ADR-0112) and found **3 new
HIGH-severity issues**, all independently re-verified against the real
source in this session before any fix was made. This ADR records the 3
confirmed fixes. The report's MEDIUM/LOW findings (~40/~90) and test/doc
findings are out of scope for this pass — see `PROJECT_STATUS.md`'s
own session entry for the account owner's disposition on those.

## Decision

### H-1: `scripts/run_learning_cycle.py` discarded every `repo.record()` return value

`storage.learning_repository`'s `record()` methods reassign an id from
a persistent DB sequence whenever a natural-key lookup finds no
existing row (`DuckDBCandidateModelRepository.record`, etc.) — the
in-process id (`learning.trainer._IdAllocator`, restarting at 1 every
fresh invocation of the script) and the real, persisted id only agree
by coincidence on the very first run against an empty store. The
script called `record()` on `result.dataset_result.dataset`/
`result.candidate`/`result.evaluation`/`result.experiment` and then
discarded every return value, building its JSON report and each
downstream record's own cross-references (`EvaluationResult.
candidate_id`/`dataset_id`, `LearningExperimentRecord.dataset_id`/
`candidate_id`/`evaluation_id`) from the stale in-process ids. A second
invocation against the SAME store with genuinely new experience (a
different `dataset_version`, so `record()` does NOT take its
natural-key early-return path) silently persisted a real row under a
NEW real id while every downstream reference kept pointing at the
FIRST run's id — a real, undetected database consistency corruption,
invisible in the report's own output (which itself used the stale ids)
and untested by the pre-existing "same data twice" idempotency test
(identical content always takes the early-return path, so the
reassignment code was never exercised by it).

**Fix**: every `record()` call's return value is now captured and used
for everything downstream — the report, the print statements, and each
subsequent `dataclasses.replace(...)` that threads the real `dataset_
id`/`dataset_version`/`candidate_id`/`evaluation_id` into the next
record before it is itself persisted.

### H-2: realized PnL double-counted spread/slippage cost

`Fill.price` is documented as "the effective per-share price actually
paid/received" — already net of spread and slippage (`broker.paper.
execution.py` builds it via `apply_spread` then `adjust` for
slippage). `backtest.portfolio.PortfolioAccounting.apply_fill`'s SELL
branch computed `realized = (fill.price - pos.average_cost) *
fill.quantity - fill.total_cost`, where `fill.total_cost = commission +
spread_cost + slippage_cost` — subtracting spread/slippage a SECOND
time on top of prices that already reflected them, systematically
understating every realized gain (or overstating every realized loss)
by `spread_cost + slippage_cost`. Cash accounting itself was never
wrong (`cash -= fill.notional + fill.commission` on BUY, `cash +=
fill.notional - fill.commission` on SELL — commission only, correctly,
since `fill.notional = fill.price * fill.quantity` already carries the
spread/slippage effect) — only the separately-reported `realized_pnl`
(and everything downstream of it: `ClosedTradeRecord.realized_pnl`,
`trade_journal.backtest_adapter`'s `TradeRecord.realized_pnl`/
`realized_return` via `portfolio.closed_trades[-1]`, and — the reason
this was caught now rather than staying a purely historical backtest
bug — ADR-0113's own new `orchestration.paper_runner.run_cycle`
realized-PnL computation, which copied the same formula believing it
matched `trade_journal.backtest_adapter`'s already-established
convention, not knowing that convention was itself wrong).

**Impact**: every backtest's realized-PnL, win-rate, and drawdown-of-
closed-trades figure this project has ever computed was biased toward
looking worse than it actually was. More acutely for this session:
ADR-0113's own capstone proof (a real Paper Trading closing SELL
feeding a real Learning Engine training run) used the biased number as
its training label.

**Fix**: both production sites (`backtest.portfolio.PortfolioAccounting.
apply_fill`, `orchestration.paper_runner.run_cycle`) now compute
`realized = (fill.price - avg_cost) * fill.quantity - fill.commission`
— commission only. `trade_journal.backtest_adapter` needed no separate
change (it reads `portfolio.closed_trades[-1].realized_pnl`, already
fixed at the source).

### H-3: reentry cooldown compared calendar days against a trading-day-ratified policy

`LIVE-RISK-POLICY.md` #16 explicitly ratified `RiskConfig.
reentry_cooldown_days = 5` as **"5 trading days"** (ADR-0093/ADR-0095).
`risk.engine.DeterministicPortfolioRiskEngine.assess`'s reentry-cooldown
check computed `days_since_exit = (as_of_time - last_exit_time).
total_seconds() / 86400.0` — a raw calendar-day count — and compared it
directly against the trading-day-denominated threshold. A real weekend
inside the elapsed window let the cooldown clear with fewer actual
trading days elapsed than ratified (e.g. a Friday exit "clears" a
5-trading-day cooldown by the following Wednesday in calendar days —
only 3 real trading days), a silent weakening of a ratified Live risk
limit.

**Fix**: new `risk.engine._trading_days_elapsed(start, end)` counts
Monday-Friday calendar days strictly after `start`'s date through
`end`'s date — weekends excluded, US market holidays NOT accounted for
(this module has no market-calendar dependency, and `LIVE-RISK-
POLICY.md` #16's own "5 trading days (roughly one calendar week)"
framing already treats the number as an approximate whipsaw guard, not
a precisely-calibrated one — a full `data_infra.calendar.
TradingCalendar` dependency was judged disproportionate to close the
remaining, much smaller holiday-only gap). The reentry-cooldown check
now compares this trading-day count against `config.
reentry_cooldown_days` instead of the raw calendar-day fraction.

## What this does NOT do

Does not address the review's ~40 MEDIUM or ~90 LOW findings (restart-
recovery ID-collision class, `ai_gateway.QuotaManager` natural-exhaustion
lockout, `PositionView.market_value` round-trip serialization gap,
corporate-action/fill sequencing at checkpoint boundaries, and the
rest) — out of scope for this pass, left for the account owner to
prioritize separately. Does not add a real market-calendar dependency
to `risk.engine` (H-3's own scope note above) — US market holidays can
still, rarely, let the cooldown clear up to ~1-2 trading days early in
a given year; documented, not fixed, as a deliberately accepted
residual imprecision. Does not retroactively correct any `realized_pnl`
already persisted by a real run before this fix (the daily GitHub
Actions Paper Trading scheduler's own accumulated history, and any
already-published backtest report) — only new runs benefit; existing
rows and reports keep their original, now-known-biased values. Does not
change `Fill.total_cost`'s own definition or `TradeRecord.
transaction_cost` (still `commission + spread_cost + slippage_cost`,
correctly, as a real aggregate friction metric independent of
`realized_pnl` — only `realized_pnl`'s own formula was wrong).

## Tests

`tests/orchestration/test_run_learning_cycle_cli.py::
test_a_second_run_against_new_experience_persists_real_resolvable_ids`
(H-1): drives two real runs of the CLI against a genuinely growing
Trade Journal (a reversal price fixture, second run's window includes
a real closing SELL the first did not) and verifies the SECOND run's
reported ids resolve to real, mutually-consistent rows via independent
DB lookups (`repo.get(...)`), not by trusting the report's own internal
consistency — confirmed to fail without the fix (manually reverted and
re-run) and pass with it. `tests/trade_journal/test_backtest_
integration.py::test_round_trip_realized_pnl_matches_hand_computation`
and `tests/orchestration/test_paper_runner.py::TestTradeJournalWriteSide::
test_a_closing_sell_records_real_realized_pnl_return_and_holding_period`
(H-2): both pre-existing hand-computation assertions updated from
`- fill.total_cost`/`- sell.transaction_cost` to `- fill.commission`/
`- sell.fill.commission`, matching the corrected formula (`tests/
trade_journal/test_trade_record.py`'s own realized-PnL fixture needed
no change — its `spread_cost=0, slippage_cost=0` inputs happen to make
the old and new formulas numerically identical, so it was never
actually pinning the bug despite the review flagging it). `tests/
risk/test_engine.py::TestReentryCooldown` (H-3): the pre-existing
boundary test's exit/evaluation dates rewritten to real trading-day
arithmetic (was: an exit "exactly 5 calendar days" before evaluation
incorrectly asserted PASS; now: an exit exactly 5 TRADING days before
evaluation asserts PASS, one trading day short asserts REJECT), plus a
new `test_a_weekend_gap_alone_never_satisfies_the_cooldown` pinning the
exact bug the review found (a Friday exit evaluated the following
Wednesday: 5 calendar days but only 3 trading days — must REJECT, and
did not before this fix). Full suite re-run: **2799 passed, 0
failed** (up from ADR-0113's own 2797 on merged `main` HEAD).
