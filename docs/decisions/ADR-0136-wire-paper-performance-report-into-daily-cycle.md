# ADR-0136: Wire `compute_paper_performance_report` Into the Real Daily Cycle

**Status:** Accepted
**Date:** 2026-09-17
**Deciders:** Claude Code (session continued), pending project owner review
**Related documents:** `docs/decisions/ADR-0024-paper-performance-and-validation.md`
(Phase 18, the module this ADR wires up unmodified),
`docs/decisions/ADR-0096-...` (the identical "always populated" precedent
this ADR reuses for the accounting side), `docs/decisions/ADR-0146-...`
(the Discord notification this ADR's new report field now also reaches)

---

## Context

One of the account owner's own uploaded third-party evaluation reports
scored this project's real Paper Trading pipeline lowest on exactly this
gap: `broker.paper.performance.compute_paper_performance_report`
(Phase 18) is fully implemented and tested, but `scripts/run_paper_
trading_cycle.py` -- the real, scheduled production entrypoint -- never
calls it. Every daily report has shown raw cash/position counts only,
never Sharpe/Sortino/max drawdown/win rate.

Wiring it up surfaced a real, previously-undiscovered gap of its own:
`session.adapter.accounting` (the one `backtest.portfolio.
PortfolioAccounting` instance every real fill is applied to) had never
had `mark_to_market` called on it anywhere in the real pipeline --
confirmed by reading `orchestration.paper_runner.run_cycle` end to end,
not assumed. Its `value_series`/`turnover()` -- exactly what `compute_
paper_performance_report`'s own docstring says a caller should supply --
were consequently always empty/zero for any real caller, a second latent
gap the tests never exercised because no test previously drove `run_cycle`
and then read `session.adapter.accounting` back.

## Decision 1 -- `run_cycle` now always marks its own accounting to market, using prices it already computed

`orchestration/paper_runner.py::run_cycle` collects each security's own
`current_price` (already computed every cycle for Sizing/Risk) into a
`prices_by_security` dict as it iterates, then calls `session.adapter.
accounting.mark_to_market(prices_by_security, as_of_time)` once per
cycle, after the per-security loop. Unconditional, not opt-in (same
"always populated" treatment `trade_journal_repository` recording
already got under ADR-0096) -- it only appends internal valuation
history and changes no existing return value, so every existing caller
(`run_paper_trading_cycle.py`, `run_multi_strategy_paper_trading_cycle.py`,
every test in `tests/orchestration/test_paper_runner.py`) is unaffected
except for this now-populated side channel.

## Decision 2 -- `equity_history` comes from `risk_repository`, never from `accounting.value_series`, because only one of them survives `--resume`

Confirmed by reading `PaperTradingSession.restore()`: it replays every
persisted order and fill (correctly rebuilding cash/positions/realized_
pnl/`_trade_notionals`), but never replays a `mark_to_market` call --
`accounting._valuation_history` starts genuinely empty on every fresh
process, including a `--resume` invocation against a store with months
of real history. `scripts/run_paper_trading_cycle.py` therefore builds
`equity_history` the same way it already builds `PaperRunnerState.
value_history` (a real, already-proven-durable source): from
`RiskCheckedPosition.as_of_time`/`.risk_state.portfolio_value`, one real
snapshot per checkpoint, across every past invocation this `--paper-
store` has ever seen. A new `_equity_history()` helper returns the
timestamped pairs `compute_paper_performance_report` needs; the
existing `_reconstruct_value_history()` (used for seeding `PaperRunnerState.
value_history`) is now a thin wrapper over it, removing a duplicate query.

## Decision 3 -- `turnover` is deliberately left unsupplied, not computed wrong

`PortfolioAccounting.turnover()` divides `sum(_trade_notionals)` (durable
across `--resume`, since `apply_fill` runs during replay too) by the
average of `_valuation_history` (NOT durable, per Decision 2). Calling it
directly from the script would combine a full-history numerator with a
this-run-only denominator, silently overstating turnover on every
resumed run after the first. Rather than report a wrong number, the
script passes no `turnover` argument at all -- `compute_paper_performance_
report` already handles this honestly (`reasons["turnover"] =
"not_supplied"`), the exact behavior this project's own "never guess a
missing value" rule requires. Making `turnover` durable across restarts
would need `accounting`'s own valuation history to be persisted and
replayed, a real design change out of scope here -- left as a disclosed
gap, not silently worked around.

## Decision 4 -- persisted through the same repository the tests already use, one real report per invocation

`storage.paper_performance_repository.DuckDBPaperPerformanceReportRepository`
already existed (Phase 18) but had no real caller either. The script now
records one `PaperPerformanceReport` per invocation under a stable
`paper_session_id` (`f"paper-session-{universe.lower()}"`, one continuous
session per universe/`--paper-store`, matching how the store itself is
already scoped), with `report_id` allocated the same "past this store's
own real max" way every other ID in this script already is
(`_next_starting_id`, reused unchanged). A `--resume` invocation therefore
adds a new report to the session's history rather than overwriting the
last one -- `list_for_session` gives the account owner (or a future
tearsheet) the whole real time series of daily evaluations, not just the
latest.

## Decision 5 -- the JSON `--out` report and the Discord notification both gain a `performance` section, for free

`storage.serialization.paper_performance_report_to_payload` already
produces a JSON-safe dict (Phase 18's own DuckDB persistence uses it) --
reused directly as the new `report["performance"]` key rather than
writing a second serializer. `notifications.discord_webhook.format_
paper_trading_cycle_report` (ADR-0146, merged earlier this session) now
also renders Sharpe/Sortino/max drawdown/total return when present,
skipping each individually absent/`None` metric rather than fabricating
one -- an older report file with no `performance` key at all (written
before this ADR) is rendered exactly as before.

## Consequences

### Positive

- The real, scheduled daily cycle now computes and persists a genuine
  performance report every run -- closing the account owner's own
  evaluation report's top-scored gap.
- `run_cycle`'s accounting is now mark-to-market-current for the first
  time, benefiting any future caller (e.g. `run_multi_strategy_paper_
  trading_cycle.py`) that wants a real, single-process equity curve.
- Discord notifications (ADR-0146) now carry Sharpe/Sortino/drawdown/
  total return once available, with no separate wiring needed.

### Negative / Trade-offs

- `turnover` stays `None` in every real run until `PortfolioAccounting`'s
  own valuation history is made durable across restarts -- a real,
  disclosed gap, not fixed here.
- `accounting.value_series`/`turnover()` are still not restart-durable
  themselves (only the risk-repository-derived equity curve is) -- a
  caller reading `session.adapter.accounting` directly after a `--resume`
  run would see only that run's own new points, which is why the script
  deliberately reads from `risk_repository` instead.
- The early-exit `--resume` "nothing new to process" branch (already
  returning before this code runs) still does not compute a performance
  report -- left as a minor, disclosed scope boundary, not a silent gap
  in the main path this ADR covers.

## Tests

`tests/orchestration/test_paper_runner.py::TestMarkToMarketAccounting`
(3 new tests: one valuation point per cycle, correct reference price,
real turnover within one process).
`tests/orchestration/test_run_paper_trading_cycle_cli.py::
TestPerformanceReportWiring` (3 new tests: JSON report shape, real
DuckDB persistence, resumed runs accumulate rather than overwrite).
`tests/notifications/test_discord_webhook.py` (3 new tests: metrics
rendered, `None` metrics skipped, missing `performance` key skipped
entirely). Full suite re-run clean after these changes.

## Status of Implementation at Time of This ADR

Code, tests, and documentation complete and committed.
