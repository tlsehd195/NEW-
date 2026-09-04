# ADR-0068: `value_history`, persistence, and a real repeated-execution CLI for the Paper pipeline

**Status:** Accepted
**Session:** 36

## Context

ADR-0067 built the first real Regime->...->Order pipeline
(`orchestration.paper_runner.run_cycle`) but explicitly left three
things undone: (1) `value_history` was not sourced, so `max_drawdown`/
`max_portfolio_volatility` always REJECTed unless disabled, (2) nothing
persisted the five upstream stages' real output, (3) no script actually
looped `run_cycle` over more than one checkpoint. The user asked to
proceed on all three.

## Decision 1 -- `PaperRunnerState` makes `value_history` real

A new `PaperRunnerState` dataclass (`value_history: list[float]`) is
an optional `run_cycle` parameter. When supplied, `run_cycle` appends
the cycle's real `portfolio.portfolio_value` to it and passes the
running series to `risk_engine.assess` as `value_history` -- the same
"last element is the current checkpoint" shape `risk.engine`'s own
tests already establish. `state=None` (the default) preserves the
original behavior exactly (regression-tested). A caller resuming a
previous session should seed `value_history` from real, already-
persisted values -- this object never fabricates a gap.

## Decision 2 -- five optional repository parameters for real persistence

`run_cycle` gained `prediction_repository`/`regime_repository`/
`decision_repository`/`sizing_repository`/`risk_repository`, each
`Optional`, matching the exact repository classes/methods
`tests/integration/test_risk_lineage.py` already established
(`storage.prediction_repository.DuckDBPredictionRepository`, etc.) --
no new persistence code, only wiring an already-tested piece.
`PaperTradingSession.submit` already persists its own order/fill/status
records independently; these five cover exactly what that session does
not.

## Decision 3 -- `scripts/run_paper_trading_cycle.py`, a real repeated-execution CLI

Loops `run_cycle` once per trading-day checkpoint over `[--start,
--end]` against a real DuckDB market-data catalog
(`scripts/ingest_real_market_data.py`'s own output), carrying one
`PaperRunnerState` across the whole run and persisting every
checkpoint through all five new repository parameters plus
`storage.paper_repository`'s DuckDB order/fill repositories and
`storage.broker_repository.DuckDBOrderStatusEventRepository` for
`PaperTradingSession`'s own state. `sector_by_security` is read
directly from the chosen `UniverseDefinition`'s own public
`SymbolMetadata.sector` field (real data, ADR-0058/ADR-0059/ADR-0066)
-- never the module-private `_REAL_SEC_SECTOR_AND_EXCHANGE` dict.

**Still not "always-on."** This script runs once, over a fixed window,
then exits -- a real always-on process still needs an external
scheduler (cron or equivalent) invoking this script (or its successor)
repeatedly, which remains out of scope, matching `PHASE-15-paper-
trading.md` section 1.1's own framing restated in ADR-0067.

`--max-drawdown`/`--max-portfolio-volatility` default to `None`
(disabled): a fresh run has no prior portfolio-value history to seed
`PaperRunnerState` from, and this script does not fabricate one --
enabling either flag on a brand-new run means the first several
checkpoints (until `RiskConfig.min_history_for_volatility`, default 5,
is reached) will REJECT as `drawdown_unknown`/
`portfolio_volatility_unknown`, by design, not a bug.

## Tests

4 new in `tests/orchestration/test_paper_runner.py`
(`TestValueHistoryState`, `TestPersistence`): a real `max_drawdown`
rejects as unknown without `state`; `value_history` accumulates across
5 cycles and the drawdown check stops rejecting as `unknown` once
enough history exists; all five repositories receive exactly one
record when supplied; an omitted repository persists nothing. 4 new in
`tests/orchestration/test_run_paper_trading_cycle_cli.py`, run
end-to-end (no network dependency, unlike this project's SEC EDGAR
scripts) against a real seeded DuckDB catalog with a monkeypatched
one-symbol universe: a short real run persists real lineage and writes
a report; a sector-limit-configured run uses the universe's own real
sector data; a catalog with no bars fails cleanly (exit 1, not a
traceback). Full suite: 2314 passed (up from 2306).
