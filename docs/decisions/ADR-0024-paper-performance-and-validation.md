# ADR-0024: Paper Trading Performance Report and Validation

## Context

`docs/operations/PRODUCTION-READINESS-MATRIX.md` (Phase 17) flagged
Paper Trading's most significant remaining gap: no performance
evaluation existed beyond raw PnL (`monitoring.collectors.
collect_account`, itself only added in Phase 17). "Paper return >
benchmark" was explicitly never treated as sufficient evidence of Live
readiness, but until this phase there was no code to compute anything
*else* to evaluate instead. Phase 18
(`docs/specifications/PHASE-18-paper-performance-and-validation.md`)
closes this gap.

## Decision

### 1. A new module, not a modification to `backtest.metrics`

`backtest.metrics`'s public functions (`sharpe_ratio`, `sortino_ratio`,
`cagr`, `calmar_ratio`, `compute_performance_report`) collapse every
insufficient-data or division-by-zero case to a fabricated `0.0`.
Phase 18's instruction explicitly forbids this ("필요한 값이 없으면
0을 임의로 넣지 않는다"). Modifying `backtest.metrics` itself to
change this contract was rejected: Phase 2/4's own tests may assert on
the exact current fallback behavior, and changing it would risk
silently altering historical Backtest reporting, which is outside this
phase's scope and against the "기존 Phase 0~17 정상 동작을 깨뜨리지
말 것" mandate. Instead, `broker.paper.performance` is a new, parallel
module with the same underlying formulas (mean-excess/std for Sharpe,
population downside deviation for Sortino, CAGR, max drawdown) but a
stricter contract: every metric is `Optional[float]`, paired with an
explicit reason string in `PaperPerformanceReport.reasons` whenever it
is `None`.

### 2. Reuse `backtest.portfolio.PortfolioAccounting` via one new
   read-only property, not a duplicate accounting system

`PaperBrokerAdapter` already constructs and maintains a
`PortfolioAccounting` instance internally (Phase 2, unmodified) but
never exposed it and never called `mark_to_market` (so `value_series`
stayed empty). Rather than build a second, parallel accounting system
fed by the same fills (which the instruction explicitly forbids: "새로운
중복 accounting system을 만들지 않는다"), `PaperBrokerAdapter.accounting`
(new, a one-line read-only property) exposes the existing instance. A
caller who wants a real equity curve must call `adapter.accounting.
mark_to_market(prices, as_of)` themselves at each valuation point --
this is an explicit, additive capability with zero behavior change for
any caller that never uses it (confirmed: the full pre-existing Paper
Trading test suite passes unchanged).

### 3. Trade-level economics come from the Trade Journal, not
   `PortfolioAccounting.closed_trades`

`PortfolioAccounting` independently tracks its own `closed_trades`/
`realized_pnl`/`transaction_costs` (a Phase 2 bookkeeping convenience,
combining commission+spread+slippage into one `transaction_costs`
figure with no per-component breakdown). `trade_journal.models.
TradeRecord` (Phase 3) already carries `slippage`/`transaction_cost`
as separate fields and is the one authoritative, persisted,
provenance-tagged trade record every other phase already treats as
canonical. `compute_paper_performance_report` therefore takes
`trades: Sequence[TradeRecord]` (typically from `TradeJournalRepository.
list_trades(provenance=PAPER_TRADING, ...)`) for `num_trades`/
`win_rate`/`avg_trade_return`/`realized_pnl`/`total_transaction_cost`/
`total_slippage`, and `PortfolioAccounting.value_series`/`turnover()`
only for the equity-curve-based ratios and turnover -- two data
sources with two distinct, non-overlapping responsibilities, not two
competing trade lists.

### 4. Benchmark comparison reuses `backtest.benchmark.BenchmarkEngine`
   unchanged; no S&P 500 data was fabricated

No real S&P 500 (or any benchmark) price data exists anywhere in this
repository (confirmed by search -- no ingestion/seed script, no
`benchmark_points` rows, ADR-0005's external-data-provider decision
remains deferred). `BenchmarkEngine.compute(...)` already returns
`None` when fewer than two benchmark points are found for the
requested window -- exactly the `BENCHMARK_UNAVAILABLE` case this phase
needed, achieved with zero code changes to `backtest.benchmark`.
`broker.paper.performance.BenchmarkComparison.status` is `"AVAILABLE"`
or `"BENCHMARK_UNAVAILABLE"`, and the dataclass's own `__post_init__`
structurally forbids `BENCHMARK_UNAVAILABLE` from carrying a benchmark
return value -- a report computed without real benchmark data cannot
be silently read as "beat the S&P 500."

### 5. Persistence mirrors `storage.live_repository`'s existing pattern
   exactly

`storage.paper_performance_repository.DuckDBPaperPerformanceReportRepository`
uses the same natural-key idempotency (on `report_id`), `payload_json`
blob, and append-only sequence-numbered table
(`paper_performance_reports`) every other Phase 14/16 store already
uses. Purely additive to `storage/schema.py` -- `git diff` shows only
new lines.

### 6. No new fields added to `SafetyGateContext`/`KillSwitchTriggerContext`
   for the "nine dimensions" review (instruction section 11)

Investigation found `evaluate_safety_gate` has exactly two production
call sites (`broker.live.session.run_startup_checks` and
`LiveTradingSession.submit`), and both already independently enforce
reconciliation state (via `reconciliation_results`/the session's own
`RECONCILIATION_REQUIRED` operational state) without needing it as a
`SafetyGateContext` field. `data_health`/`monitoring_pipeline_health`
already funnel through `evaluate_kill_switch_triggers` (Phase 17) into
`kill_switch_engaged`, which *is* a direct gate field. Adding
redundant fields for reconciliation/data-health/monitoring-health
directly into `SafetyGateContext` would create two parallel places to
wire the same signals, risking future drift between them --
`tests/broker/live/test_live_safety_gate_nine_dimensions.py` instead
proves each of the nine dimensions blocks through its actual,
already-existing enforcement path.

## Alternatives Considered

1. **Modify `backtest.metrics` in place to stop fabricating zeros.**
   Rejected -- see decision 1; risks changing Phase 2/4 behavior
   outside this phase's scope.
2. **Build a second `PortfolioAccounting`-like class fed by Paper's
   fills independently.** Rejected -- see decision 2; explicitly a
   "duplicate accounting system," which the instruction forbids.
3. **Source trade-level stats from `PortfolioAccounting.closed_trades`
   instead of the Trade Journal.** Rejected -- see decision 3; would
   make the Trade Journal a second-class, non-authoritative source for
   exactly the kind of data it exists to be authoritative about.
4. **Fabricate placeholder S&P 500 data so a benchmark comparison
   always has a number.** Rejected outright -- explicitly forbidden by
   instruction section 3 ("Benchmark 데이터가 없으면... 명시적으로
   기록한다").
5. **Add `reconciliation_required`/`data_health`/`monitoring_health`
   fields directly to `SafetyGateContext`.** Rejected -- see decision
   6; the existing structure already guarantees each, and duplicating
   would violate the "코드를 중복해서 만들지 말고" instruction.
6. **Treat `max_daily_loss`/`max_turnover`/`max_order_frequency_per_hour
   = None` as "LIVE BLOCKED" instead of "not enforced."** Considered
   (instruction section 12 raises this as an example) but **not
   adopted** -- it would silently change Phase 16's own documented
   design (`LiveTradingConfig`'s own comment: "operator must set these
   explicitly for them to have any effect") into a strictly more
   restrictive one, which is a financial-policy decision this ADR is
   not authorized to make unilaterally. Reported as `DECISION REQUIRED`
   instead (see the Phase 18 completion report).

## Consequences

### Positive

- Paper Trading now has a real, honestly-computed performance
  evaluation (`total_return`/`CAGR`/`volatility`/`Sharpe`/`Sortino`/
  `Calmar`/`max_drawdown`/`turnover`/`transaction_cost`/`slippage`/
  `num_trades`/`win_rate`/`avg_trade_return`/`realized_pnl`/benchmark
  comparison), closing Phase 17's most significant documented gap.
- Zero modifications to Phase 0-17 source files' *behavior* --
  `PaperBrokerAdapter.accounting` is additive, `backtest.metrics`/
  `backtest.benchmark`/`backtest.portfolio` are unchanged, and the full
  pre-existing test suite passes unchanged.
- Every insufficient-data/zero-denominator case is a named, explicit
  reason string, never a fabricated number.
- A methodology-adoption question (Walk-Forward/PBO/Deflated Sharpe)
  was researched with real citations
  (`docs/research/walk-forward-pbo-deflated-sharpe.md`) rather than
  either implemented hastily or ignored.

### Negative / Trade-offs

- Two ratio conventions now coexist in this codebase:
  `backtest.metrics`'s zero-fallback Sharpe/Sortino/Calmar (Phase 2,
  used by the historical Backtest engine) and `broker.paper.
  performance`'s Optional/reasoned versions (Phase 18, used by Paper
  Trading). A future reader must know which one a given report came
  from. This asymmetry is a deliberate, documented consequence of
  decision 1, not an oversight.
- The equity curve for a `PaperPerformanceReport` is only as good as
  the caller's own `mark_to_market` discipline -- if a caller never
  calls it, `value_series` stays empty and every equity-based metric
  is honestly `insufficient_data`, which is correct but requires
  callers to understand this is opt-in, not automatic.
- Real Walk-Forward/PBO/Deflated Sharpe validation remains
  unimplemented; a `DECISION REQUIRED` is carried forward, not
  resolved, per the research document's own conclusion.

## Safety Impact

Purely additive/read-only: no change to `LIVE_TRADING_ENABLED`, no
change to any risk limit, no change to `evaluate_safety_gate`'s
condition set, no new path toward `CandidateModelStatus.APPROVED`/
`.DEPLOYED` (verified: `tests/broker/paper/test_paper_performance_boundary.py`).
The module computes a report about what already happened; it decides
nothing and blocks nothing on its own.

## Testing

See `docs/specifications/PHASE-18-paper-performance-and-validation.md`
Test Strategy section for the full list. Full regression:
`python -m pytest tests/ -q`.
