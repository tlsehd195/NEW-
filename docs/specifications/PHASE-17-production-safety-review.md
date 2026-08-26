# Phase 17: Production Safety Review

## 0. Purpose

Not a new development phase. A verification pass over Phase 0-16,
before any real capital could be used, to state precisely what is
confirmed, what is not, and what still needs a human decision --
"Automated tests PASS" is explicitly not treated as "Production Ready"
anywhere in this document. This phase built the minimum code needed to
close two genuine safety gaps it found (a Trade Journal data-loss bug,
a Toss 5xx mis-mapping) and to close one documented Phase 15 known
limitation (Monitoring/ACCOUNT wiring) -- everything else is
verification, documentation, and additional regression tests over
already-existing Phase 0-16 code. No real Toss API call was made; no
`LiveActivationApproval` was constructed for a real operational
purpose; `LIVE_TRADING_ENABLED` was never set to `true`.

## 1. Repository Integrity (verified via git, not assumed)

- Branch: `claude/phase-17-production-safety-review`, created from
  `claude/phase-16-live-trading` at commit `3302e6ac9f70a055629b967b2a1a8bb7b898f309`
  (parent `eae021270f409b30fb36791e5518545876fa1d48`).
- `origin/main` confirmed a non-diverged ancestor of HEAD
  (`git merge-base HEAD origin/main` == `git rev-parse origin/main`).
- Zero merge commits on this branch (`git log --merges --oneline`
  empty).
- Working tree clean before this phase's first edit.

## 2. Baseline Tests (actual, not assumed)

`python -m pytest tests/ -q` before any Phase 17 edit: **1264 passed, 0
failed, 0 skipped, 0 warnings** (run twice to confirm determinism).

## 3. Review Areas -- Verdicts

Each verdict is PASS / FAIL / BLOCKED / UNKNOWN / DECISION REQUIRED,
each backed by a file/test/line, never by narrative alone.

| # | Area | Verdict | Evidence |
|---|---|---|---|
| 1 | Toss API capability verification | **UNKNOWN (structurally blocking)** | `docs/operations/TOSS-API-GAP-ANALYSIS.md`; `tests/broker/live/test_live_safety_gate.py::TestRealTossCapabilitiesStructurallyBlockLiveTrading`; `tests/integration/test_live_trading_lineage.py::test_toss_real_capabilities_block_the_gate_end_to_end` |
| 2 | Live risk policy completeness | **INCOMPLETE** | `docs/operations/LIVE-RISK-POLICY.md` -- 1 DEFINED, 6 INHERITED, 3 UNDEFINED (DECISION REQUIRED written for each), 3 BLOCKING |
| 3 | Paper Trading readiness | **PARTIAL** | Order/Fill/Journal/Experience lineage: PASS (`tests/integration/test_paper_learning_readiness_lineage.py`, scenarios A-E). Performance evaluation beyond raw return: **FAIL/BLOCKED** -- no Paper-side equivalent of `backtest.metrics.PerformanceReport` exists (see section 7 below) |
| 4 | Paper -> Learning lineage / provenance safety | **PASS** | `tests/integration/test_paper_learning_readiness_lineage.py::TestPaperToLearningProvenanceSafety`; `learning.cleaning.DataCleaner.clean`'s pre-existing `provenance_mismatch` check (Phase 9) re-verified as a real, structural, defense-in-depth guarantee, not just a filter convention |
| 5 | Candidate model validation boundary | **PASS** | `tests/evolution/test_production_safety_candidate_boundary.py` -- repo-wide (whole `src/` tree) AST scan, not just `evolution.*`; zero references to `CandidateModelStatus.APPROVED`/`.DEPLOYED` anywhere outside the enum's own definition |
| 6 | Live activation safety | **PASS** | `broker.live.approval.LiveActivationApproval` re-confirmed to reject `approved_by` in `{AI, SYSTEM, CLAUDE}` (case-insensitive) and require the exact confirmation phrase; `evaluate_safety_gate`'s 11 independent conditions re-confirmed unchanged |
| 7 | Broker reconciliation | **PASS** | `tests/broker/live/test_production_safety_cross_cutting.py::TestReconciliationNeverBecomesMatchedOnceUnknownOrMismatched` -- UNKNOWN never becomes MATCHED, and a session that hits `RECONCILIATION_REQUIRED` blocks every further submission, re-verified end to end (not just per-function) |
| 8 | Monitoring / alerting / drift readiness | **PASS for wired components; one gap closed, one remains open** | See section 6 below. Phase 15's `paper_account_equity`/`paper_pnl`/`paper_drawdown` gap: **CLOSED this phase** (`monitoring.collectors.collect_account`, ADR-0023 decision 4). Paper-side Sharpe/Sortino/Calmar/volatility/turnover/benchmark-comparison: **NOT IMPLEMENTED**, documented as a gap, not built this phase |
| 9 | Kill switch / rollback readiness | **PASS (kill switch); DECISION REQUIRED (rollback/cancel-on-shutdown)** | Kill switch: `data_health` gap closed (ADR-0023 decision 3), AI-cannot-release re-confirmed. Rollback: no automatic order cancellation on shutdown remains a deliberate, documented (not accidental) Phase 16 choice (`docs/decisions/ADR-0022` decision 8) -- still requires a human decision before Live use, not re-litigated this phase |
| 10 | Operational Runbook | **PASS** | `docs/operations/LIVE-TRADING-RUNBOOK.md` re-read against actual code; `tests/broker/live/test_production_safety_cross_cutting.py::TestRunbookReferencesStillResolveInCode` mechanically verifies every `broker.*` symbol the runbook names still resolves |

## 4. Toss API Verification

See `docs/operations/TOSS-API-GAP-ANALYSIS.md` in full. Summary: no
real network access to `openapi.tossinvest.com`/
`developers.tossinvest.com` this session (re-confirmed
`EGRESS_BLOCKED`, not assumed from Phase 13 notes); one new Tier-2
(community, not official) lead found (`BEOKS/tossinvest-skill`'s
`references/openapi.json`, listing candidate `GET /api/v1/accounts`/
`GET /api/v1/holdings`/`GET /api/v1/orders` endpoints, with **no
cancellation endpoint found at any evidence tier**); no capability was
promoted to `ENABLED` on that evidence alone. `ACCOUNT_BALANCE`/
`POSITIONS`/`ORDER_STATUS`/`CANCEL_ORDER` remain
`CapabilityStatus.UNKNOWN` in `TossBrokerAdapter.get_capabilities()`,
unchanged from Phase 13.

**A code-level fix was made in this area regardless**: `parse_order_response`
mapped a Toss `5xx` response to `BrokerOrderStatus.REJECTED`, falsely
asserting the broker had definitively declined the order. It now raises
`BrokerProviderError`, treated as UNKNOWN/RECONCILIATION_REQUIRED by
`LiveTradingSession` (ADR-0023 decision 2).

## 5. Live Risk Policy Completeness

See `docs/operations/LIVE-RISK-POLICY.md` in full for the 13-item
classification table and three `DECISION REQUIRED` entries (daily loss
limit, turnover limit, order frequency limit). No policy number was
invented; every `TBD` is marked literally as such.

## 6. Monitoring Readiness (per-metric)

| Metric | Collected | Persisted | Alertable | Notes |
|---|---|---|---|---|
| Portfolio value / equity | Yes (Phase 17) | Yes (Phase 17) | Yes (Phase 17) | `monitoring.collectors.collect_account` |
| Cash | Yes (`account_summary()`) | No | No | Available as a raw snapshot value; not yet a distinct Monitoring metric |
| Positions | Yes (`get_positions()`) | Yes (`paper_orders`/`paper_fills`, order-level) | No (as a portfolio-level signal) | No position-level drift/health metric exists |
| Exposure (weight/gross) | Computed internally by `risk.engine.PortfolioRiskEngine` for its own checks | No | No | Not surfaced to Monitoring as its own metric |
| PnL | Yes (Phase 17) | Yes (Phase 17) | Yes (Phase 17) | `monitoring.collectors.collect_account` |
| Drawdown | Yes (Phase 17) | Yes (Phase 17) | Yes (Phase 17), opt-in via caller-supplied `max_drawdown` | `evaluate_account_health` -- `None` threshold = not enforced, by design |
| Orders / Fills | Yes | Yes (`broker_requests`/`broker_responses`/`paper_fills`) | Yes | `monitoring.collectors.collect_broker` (Phase 14, unmodified) |
| Broker health | Yes | Yes | Yes | `collect_broker` (Phase 14) |
| Data health | Yes | Yes | Yes; now also feeds the kill switch (Phase 17) | `collect_data_quality` (Phase 14) + `KillSwitchTriggerContext.data_health` (Phase 17) |
| Model health | Yes (existence-based) | Yes | Yes | `collect_learning`/`collect_model_evolution` (Phase 14) |
| Feature drift / Prediction drift | Yes | Yes | Yes | `monitoring.drift`/`DriftResult` (Phase 14, unmodified) |
| Performance (Sharpe/Sortino/Calmar/volatility/turnover/benchmark) | **No, for Paper Trading** | N/A | N/A | `backtest.metrics.PerformanceReport` exists and is used by the historical Backtest engine only; nothing in `broker.paper.*` computes an equivalent from real Paper results. Documented gap, not built this phase (ADR-0023 alternative 5) |

Critical-event audit trail (all pre-existing except where noted):
broker failure -> `BrokerResponseRecord(status="ERROR")` (Phase 13) +
`KillSwitchEvent` if configured; data failure -> `ComponentHealth`
UNAVAILABLE/DEGRADED (Phase 14), now also a kill-switch trigger (Phase
17); reconciliation mismatch/unknown position/unknown order ->
`ReconciliationResult` (Phase 16, append-only); excessive drawdown ->
`ComponentHealth` UNAVAILABLE (Phase 17, opt-in); kill switch ->
`KillSwitchEvent` (Phase 16, append-only); model failure ->
`LearningExperimentRecord(status="FAILED")` (Phase 9); provider failure
-> `AIResponse(status=ERROR)` (Phase 12). No real Slack/email delivery
is required or built this phase, per instruction.

## 7. Paper Trading Performance Evaluation -- Explicit Non-Sufficiency of Return Alone

This review explicitly does not, and did not, treat "Paper return >
benchmark" as evidence of Live readiness. In practice there is
currently **no Paper-side computation of return at all** beyond raw
PnL (`monitoring.collectors.collect_account`, Phase 17) -- volatility,
drawdown-adjusted return (Sharpe/Sortino/Calmar), turnover,
transaction-cost/slippage attribution, consistency across runs, and a
benchmark comparison matched to the same period/capital/cost
assumptions are all computed today **only** for the historical Backtest
engine (`backtest.metrics.PerformanceReport`, `backtest.benchmark.
BenchmarkResult` -- the latter is already correctly designed to share
`initial_capital`/cost-model with the run it's compared against,
Phase 4). Building the Paper-side equivalent is real, non-trivial work
(computing a returns series from Paper fills/journal history and
threading it through the same metrics functions) and was not attempted
this phase, consistent with the "minimal additive changes only"
discipline. **Verdict: FAIL/BLOCKED** for this specific sub-area of
Paper Trading readiness -- this alone is sufficient reason Paper
Trading has not "earned" Live eligibility on performance grounds, apart
from and in addition to Toss's own capability gaps.

## 8. Test Strategy (Phase 17 additions)

| Category | File |
|---|---|
| Toss contract (5xx, CANCELED/PARTIAL_FILLED via full response path, UNKNOWN != SUCCESS structural proof, idempotency-is-not-broker-dependent) | `tests/broker/toss/test_toss_production_safety_contract.py` |
| Live risk policy completeness | `tests/broker/live/test_live_risk_policy_completeness.py` |
| Paper->Journal->Experience->Learning lineage (scenarios A-E) + provenance safety | `tests/integration/test_paper_learning_readiness_lineage.py` |
| Repo-wide Candidate approval/deployment boundary | `tests/evolution/test_production_safety_candidate_boundary.py` |
| Kill switch `data_health` regression | `tests/broker/live/test_live_kill_switch.py` (additions) |
| Monitoring ACCOUNT component (metrics/health/collector) | `tests/monitoring/test_monitoring_account.py` |
| Monitoring ACCOUNT persistence | `tests/storage/test_monitoring_repository.py` (addition) |
| Cross-cutting: secret-safety (repo-wide), environment-guard symmetry, idempotency comparison, failure-recovery matrix, reconciliation regression, runbook-consistency | `tests/broker/live/test_production_safety_cross_cutting.py` |
| Trade Journal partial-fill regression (in-memory / DuckDB) | `tests/trade_journal/test_idempotency.py`, `tests/storage/test_trade_journal_persistence.py` (additions) |

## 9. Known Limitations (Phase 17-specific, additive to Phase 0-16's own lists)

- Paper Trading has no performance-report computation of its own
  (section 7).
- `MockBrokerAdapter`'s `"account_unavailable"` failure mode returns an
  empty tuple `()` from `get_positions`, indistinguishable from "flat,
  no positions held" -- a real ambiguity, not fixed this phase (see
  `tests/broker/live/test_production_safety_cross_cutting.py::
  TestFailureRecoveryMatrixDefaultsToNoTrade::
  test_position_unavailable_returns_an_explicit_empty_result_not_a_fabricated_position`).
- `evaluate_account_health`'s `max_drawdown` is not wired to any
  specific caller by default -- an operator must explicitly pass one
  (e.g. `RiskConfig.max_drawdown`) for drawdown alerting to fire.
- Cancel-on-shutdown remains a deliberate, unresolved policy question
  (`docs/decisions/ADR-0022` decision 8) -- unchanged this phase.

## 10. Phase Boundary

This phase changed: `src/trade_journal/repository.py`,
`src/storage/trade_journal_repository.py` (natural-key fix);
`src/broker/errors.py`, `src/broker/toss/mapping.py` (5xx handling);
`src/broker/live/kill_switch.py` (`data_health`); `src/monitoring/enums.py`,
`src/monitoring/metrics.py`, `src/monitoring/health.py`,
`src/monitoring/collectors.py` (ACCOUNT component). It did **not**
change `src/broker/toss/adapter.py`'s capability report, `src/broker/live/approval.py`,
`src/broker/live/safety_gate.py`'s condition set, or any Phase 0-16
test's assertions (only additions).

## 11. Definition of Done

- [x] All 10 review areas judged with evidence, not narrative.
- [x] Toss capabilities re-verified UNKNOWN, not guessed to ENABLED.
- [x] Risk policy audited; no number invented; DECISION REQUIRED written.
- [x] Paper->Learning lineage traced with real code, 5 scenarios (A-E).
- [x] Candidate approval boundary re-verified repo-wide.
- [x] Monitoring gap (Phase 15) closed additively, with an ADR.
- [x] Kill switch/reconciliation/idempotency/failure-recovery/
      environment-isolation/secret-safety cross-cutting regression
      tests added.
- [x] Runbook verified against actual code, mechanically.
- [x] No existing Phase 0-16 test deleted or weakened.
- [x] Final Production Status declared honestly (see completion report).
