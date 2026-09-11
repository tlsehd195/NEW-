# ADR-0023: Production Safety Review Findings

**Status:** Accepted

## Context

`PROJECT_MASTER_PLAN.md`'s Go-Live discipline requires a Production
Safety Review before any real capital is used, distinct from (and
never satisfied merely by) automated tests passing. This phase
(`docs/specifications/PHASE-17-production-safety-review.md`)
re-verified, by reading and exercising actual code rather than
assuming import existence, the ten areas the review instruction names:
Toss API capability verification, Live risk policy completeness, Paper
Trading readiness, Paper->Learning lineage, Candidate model validation
boundary, Live activation safety, Broker reconciliation,
Monitoring/alerting/drift readiness, Kill switch/rollback readiness,
and the Operational Runbook.

Most of the ten areas held up exactly as Phase 13-16 documented them.
Four genuine gaps were found by tracing actual code paths rather than
trusting prior documentation, and are recorded here because each
required a real (if small) code change, not just a finding written to
a document.

## Decision

### 1. Trade Journal `record_trade` natural key now includes `fill.execution_time`

**The most significant finding of this review.** `fill.order_id` is
the client_order_id, identical across every partial fill of one order
(`backtest.fills.Fill.order_id = order.order_id` in both
`broker.paper.adapter` and `backtest.fills.simulate_fill`). Both
`trade_journal.repository.InMemoryTradeJournalRepository.record_trade`
and `storage.trade_journal_repository.DuckDBTradeJournalRepository.
record_trade` deduplicated on `(experiment_id, fill.order_id)` alone --
so the **second and every later partial fill of any order was silently
discarded** as an apparent duplicate of the first, in both Paper and
Live Trading (the same repository code serves both). A real order
filling in three pieces produced exactly one `TradeRecord`, one
`ExperienceRecord`, and permanently lost two real fills from the Trade
Journal and everything downstream of it (Post Trade Analysis,
Experience Dataset, Learning Engine).

This was never caught before because no existing test exercised a
partial-fill order all the way through `record_trade` -- Phase 15's
own adapter-level partial-fill test
(`tests/broker/paper/test_paper_adapter.py`) stops at the
`BrokerOrderResponse`/fill level, and every existing `record_trade`
idempotency test (`tests/trade_journal/test_idempotency.py`,
`tests/storage/test_trade_journal_persistence.py`) only ever passed
the *same* `Fill` object twice, never two genuinely different fills of
the same order.

**Fix:** the natural key is now `(experiment_id, fill.order_id,
fill.execution_time)` in both repositories. A true retry of the exact
same fill (identical `execution_time`) still deduplicates exactly as
before -- every pre-existing idempotency test continues to pass
unchanged. Two distinct fills of the same order at two different
times, the normal partial-fill case, are now both recorded. See
`tests/integration/test_paper_learning_readiness_lineage.py::
TestScenarioB_PartialThenFullFillJournalExperience` (the test that
originally caught this) and the added regression tests in
`tests/trade_journal/test_idempotency.py` and
`tests/storage/test_trade_journal_persistence.py`.

This bug predates this phase (present since Phase 3) and affects
`HISTORICAL_SIMULATION`/`PAPER_TRADING`/`LIVE_TRADING` provenance
alike; fixing it here rather than only documenting it was necessary
because leaving it in place would mean Live Trading's own Trade
Journal -- the record this whole safety architecture depends on being
trustworthy -- silently drops data for the single most common order
outcome (a multi-fill execution).

### 2. A 5xx Toss response is now `BrokerProviderError`, never mapped to `REJECTED`

`broker.toss.mapping.parse_order_response` mapped any HTTP status
`>= 400`, including `5xx`, to `BrokerOrderStatus.REJECTED`. A `5xx` is
the broker's own infrastructure failing -- it establishes nothing about
whether the order was accepted, and treating it as `REJECTED` would
tell `LiveTradingSession` "safe to consider this order done" when the
true state is unknown, exactly the false-confidence failure mode this
project's fail-closed discipline exists to prevent. `BrokerProviderError`
(new, `src/broker/errors.py`) is raised the same way
`BrokerAuthError`/`BrokerRateLimitError` already are for 401/429;
`LiveTradingSession.submit`'s existing `except BrokerError` handler
already routes any such exception to `BrokerOrderStatus.UNKNOWN` +
`OperationalState.RECONCILIATION_REQUIRED` with zero changes needed to
`session.py` itself. See
`tests/broker/toss/test_toss_production_safety_contract.py::
TestProviderErrorIsNeverConfusedWithADefinitiveRejection`.

### 3. `KillSwitchTriggerContext` gains an optional `data_health` field

`monitoring.collectors.collect_data_quality` (Phase 14) already
computes market-data pipeline health, but nothing fed it into kill
switch evaluation -- `broker.live.kill_switch.
evaluate_kill_switch_triggers` checked `broker_health`/`risk_health`/
`monitoring_pipeline_health` but had no `data_health` input at all. A
real data outage (stale or invalid bars) could go undetected by the
kill switch even with every other signal healthy. Added
`data_health: Optional[ComponentHealthStatus] = None` (additive,
default preserves every existing caller unchanged) and one more
`_CRITICAL_STATUSES` check, mirroring the three pre-existing health
checks exactly. See `docs/operations/LIVE-RISK-POLICY.md` item #13 and
`tests/broker/live/test_live_kill_switch.py::TestEachTriggerIndependently::
test_data_health_unavailable_triggers`.

### 4. `MonitoringComponent.ACCOUNT` and `monitoring.collectors.collect_account`

Closes the Phase 15/ADR-0021 known limitation: `paper_account_equity`/
`paper_pnl`/`paper_drawdown` were computable
(`PaperTradingSession.account_summary()`) but never wired into a
`MonitoringEvent`. ADR-0021 explicitly left open which of two designs
to use ("extending `MonitoringComponent`" vs. "folding into existing
broker metrics"); this phase chooses the former, since equity/PnL/
drawdown are portfolio-level facts, not broker-request-level ones, and
folding them into `BROKER`'s failure-rate metrics would conflate two
different kinds of health. New: `monitoring.metrics.
compute_account_metrics`, `monitoring.health.evaluate_account_health`,
`monitoring.collectors.collect_account` -- all follow the exact
existing three-layer collector pattern. `max_drawdown` is an optional,
caller-supplied threshold (`None` = not enforced), never a new invented
default number; a caller who wants alerting can pass
`risk.config.RiskConfig.max_drawdown` or a value chosen specifically
for alerting. No schema change was needed (`monitoring_events.component`
is a plain `TEXT` column with no `CHECK` constraint). See
`tests/monitoring/test_monitoring_account.py` and
`tests/storage/test_monitoring_repository.py::TestMonitoringEventPersistence::
test_account_component_event_from_collect_account_persists_and_survives_restart`.

This closes only the *wiring* gap. It does not address the larger,
separately-identified gap that Paper Trading has no
`backtest.metrics.PerformanceReport`-equivalent computation of its own
at all (Sharpe/Sortino/Calmar/volatility/turnover/benchmark comparison)
-- that remains a documented, unimplemented gap (see
`docs/operations/PRODUCTION-READINESS-MATRIX.md`), deliberately not
built in this phase because it is a substantial new capability, not a
minimal fix.

## Alternatives Considered

1. **Leave the `record_trade` natural-key bug as a documented Known
   Issue rather than fixing it.** Rejected -- the bug directly
   undermines the Trade Journal's trustworthiness for the single most
   common real-world order outcome (a multi-fill execution), and the
   fix is minimal, backward-compatible (verified by every pre-existing
   idempotency test still passing unchanged), and squarely inside this
   review's purpose of finding what must be true before real capital
   is used.
2. **Map a Toss 5xx to `BrokerOrderStatus.UNKNOWN` as a returned value
   rather than raising `BrokerProviderError`.** Rejected for
   consistency -- 401/429 already raise for the identical reason ("this
   response is about the transport/provider, not a judgment on the
   order"); a third, differently-shaped path for 5xx would be an
   inconsistent design for no added benefit, since
   `LiveTradingSession.submit`'s exception handler already produces the
   same `UNKNOWN` + `RECONCILIATION_REQUIRED` outcome either way.
3. **Fold `data_health` into `monitoring_pipeline_health`'s existing
   value instead of a new field.** Rejected -- `monitoring_pipeline_health`
   is documented (Phase 14) as the end-to-end pipeline verdict
   (`evaluate_pipeline_health`'s "worst status among every observed
   component"), a different, coarser signal than the DATA component's
   own health specifically; conflating them would lose the ability to
   attribute a kill-switch trigger to its actual cause.
4. **Fold ACCOUNT metrics into BROKER's existing metrics dict.**
   Rejected -- see decision 4 above; a real design choice ADR-0021 left
   open, resolved here in favor of a new component for a clean
   separation between "is the broker connection healthy" and "is the
   portfolio's own state healthy."
5. **Build a full Paper Trading performance-report module this
   phase.** Rejected -- a substantial new capability (computing a
   returns series from Paper fills and threading it through
   `backtest.metrics.compute_performance`'s Sharpe/Sortino/Calmar
   machinery), not a minimal additive fix; recorded as a gap for a
   future phase rather than improvised here under review-phase scope
   discipline.

## Consequences

### Positive

- A real, previously-undetected data-loss bug affecting every
  multi-fill order in Paper *and* Live Trading is fixed with a minimal,
  backward-compatible change and a regression test in both the
  in-memory and DuckDB-backed repositories.
- A previously-mischaracterized failure mode (5xx treated as a
  definitive rejection) is corrected with zero changes needed to the
  Live session orchestration that already handles ambiguous failures
  correctly.
- The kill switch can now react to a real market-data outage, closing
  a gap that existed since Phase 14's data-health signal was first
  computed.
- The Phase 15/ADR-0021 monitoring gap is closed additively, with a
  persistence-level regression test proving it, not just a unit test.

### Negative / Trade-offs

- The `record_trade` fix changes `TradeRecord` counts for any code that
  (incorrectly, per the pre-fix bug) relied on multiple partial fills
  collapsing into one record -- no such reliance was found anywhere in
  this codebase's own source or tests, but a downstream consumer this
  review did not examine could theoretically have depended on the
  buggy count.
- `evaluate_account_health`'s `max_drawdown` threshold is optional and
  unset by default -- a caller must explicitly wire it (e.g. from
  `RiskConfig.max_drawdown`) for drawdown-based alerting to actually
  fire; this phase does not do that wiring for Paper Trading itself,
  since choosing which pre-trade risk threshold should also become a
  monitoring-alert threshold is a policy question, not this ADR's to
  decide unilaterally.
- The Paper Trading performance-report gap (Sharpe/Sortino/Calmar/
  volatility/turnover/benchmark comparison from actual Paper results)
  remains open; `docs/operations/PRODUCTION-READINESS-MATRIX.md` marks
  it accordingly rather than treating equity/PnL/drawdown alone as a
  complete performance evaluation.

## Safety Impact

All four changes are additive or narrowly corrective; none weakens an
existing fail-closed guarantee, and none touches
`LIVE_TRADING_ENABLED`, `LiveActivationApproval`, or any
capability-reporting code in `broker.toss.adapter`. The `record_trade`
fix strictly increases the number of real fills captured (never
fabricates one); the `BrokerProviderError` change strictly narrows
which responses are treated as a definitive `REJECTED` (never widens
it); the `data_health` and `ACCOUNT` additions are both purely
additive optional inputs with safe (`None`/not-enforced) defaults.

## Testing

37 new tests across this phase's own six new/updated test files
(`tests/trade_journal/test_idempotency.py`,
`tests/storage/test_trade_journal_persistence.py`,
`tests/broker/toss/test_toss_production_safety_contract.py`,
`tests/broker/live/test_live_kill_switch.py`,
`tests/monitoring/test_monitoring_account.py`,
`tests/storage/test_monitoring_repository.py`) plus the broader
integration/boundary/cross-cutting suites described in
`docs/specifications/PHASE-17-production-safety-review.md`. Full
regression: `python -m pytest tests/ -q` -- see the Phase 17 completion
report for exact before/after counts.
