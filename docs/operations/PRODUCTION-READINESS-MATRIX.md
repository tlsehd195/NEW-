# Production Readiness Matrix

Phase 17 Production Safety Review. One row per area the review
instruction names. "Status" is one of PASS / FAIL / BLOCKED / UNKNOWN /
PARTIAL. "Blocking?" answers "does this alone prevent Live activation
today" independent of every other row. "Human Decision Required?"
names the specific decision, or "No" if none remains.

| Area | Requirement | Current State | Evidence | Status | Blocking? | Human Decision Required? | Next Action |
|---|---|---|---|---|---|---|---|
| Toss API (general) | Endpoints confirmed against official documentation before use | Only `/oauth2/token` and `POST /api/v1/orders` confirmed (Tier 2 evidence); 4 capabilities UNKNOWN | `docs/operations/TOSS-API-GAP-ANALYSIS.md` | **UNKNOWN** | **Yes** | No (a data/access problem, not a policy choice) | Obtain real network access to `openapi.tossinvest.com`/`developers.tossinvest.com`; read the official OpenAPI spec directly |
| Authentication | OAuth2 Client Credentials, credentials never logged/persisted | Implemented, confined to `broker/toss/auth.py` | `tests/broker/toss/test_toss_auth.py`; repo-wide scan `tests/broker/live/test_production_safety_cross_cutting.py::TestSecretAccessIsConfinedToOneFileAcrossTheWholeSrcTree` | **PASS** | No | No | None |
| Account (balance query) | `get_account` against a confirmed endpoint | Raises `BrokerCapabilityError`; endpoint unconfirmed | `src/broker/toss/adapter.py`; `docs/operations/TOSS-API-GAP-ANALYSIS.md` | **BLOCKED** | **Yes** | No | Same as Toss API row |
| Positions | `get_positions` against a confirmed endpoint | Raises `BrokerCapabilityError`; endpoint unconfirmed | same | **BLOCKED** | **Yes** | No | Same as Toss API row |
| Orders (creation) | Submit order against a confirmed endpoint, correctly mapped responses | Implemented and confirmed; 5xx handling fixed this phase | `tests/broker/toss/test_toss_production_safety_contract.py` | **PASS** | No | No | None |
| Cancellation | `cancel_order` against a confirmed endpoint | Raises `BrokerCapabilityError`; **no lead found at any evidence tier** | `docs/operations/TOSS-API-GAP-ANALYSIS.md` | **BLOCKED** | **Yes** | No | Same as Toss API row; also blocks Runbook's automated-cancellation step |
| Reconciliation | UNKNOWN/MISMATCH never MATCHED; blocks further submissions | Implemented, re-verified this phase | `tests/broker/live/test_production_safety_cross_cutting.py::TestReconciliationNeverBecomesMatchedOnceUnknownOrMismatched` | **PASS** | No | No | None |
| Risk (policy completeness) | Every named risk limit DEFINED or explicitly deferred with a human decision on file | 1 DEFINED, 6 INHERITED (never re-approved for real capital specifically), 3 UNDEFINED, 3 BLOCKING (no field exists) | `docs/operations/LIVE-RISK-POLICY.md` | **PARTIAL** | **Yes** (daily loss / order frequency limits unset) | **Yes** -- 3 `DECISION REQUIRED` entries in `LIVE-RISK-POLICY.md` | Human decides daily loss limit, turnover limit, order frequency limit |
| Kill Switch | Auto-engage on critical conditions; AI cannot release | Implemented; `data_health` trigger added this phase | `tests/broker/live/test_live_kill_switch.py` | **PASS** | No | No | None |
| Monitoring | Portfolio/broker/data/model health collected, persisted, alertable | Phase 15 equity/PnL/drawdown gap closed this phase; Paper performance-report (Sharpe/Sortino/etc.) not implemented | `docs/specifications/PHASE-17-production-safety-review.md` section 6-7 | **PARTIAL** | No (not independently blocking, but weakens readiness evidence) | No | Build a Paper-side performance report in a future phase |
| Drift | Feature/prediction drift detected and recorded | Implemented, unmodified this phase | `src/monitoring/drift.py`; Phase 14 tests | **PASS** | No | No | None |
| Paper Trading | Order->Fill->Journal->Experience traced with real code | Traced this phase, 5 scenarios (A-E); one real data-loss bug found and fixed | `tests/integration/test_paper_learning_readiness_lineage.py` | **PASS** (lineage); **FAIL** (performance evaluation, see Monitoring row) | No (lineage); performance gap is not independently blocking Live but is blocking a defensible "Paper proved ready" claim | No | Build the Paper-side performance report before claiming Paper-validated readiness |
| Learning | Experience -> Training Dataset provenance-safe; PAPER cannot become LIVE | Re-verified this phase, including a bypass-the-filter defense-in-depth test | `tests/integration/test_paper_learning_readiness_lineage.py::TestPaperToLearningProvenanceSafety` | **PASS** | No | No | None |
| Model Validation | No automatic Candidate->APPROVED/DEPLOYED path anywhere | Re-verified repo-wide (not just `evolution.*`) this phase | `tests/evolution/test_production_safety_candidate_boundary.py` | **PASS** | No | No | None |
| Rollback | Emergency halt and recovery procedure exists and matches code | Kill switch + Runbook exist; cancel-on-shutdown is a deliberate non-automatic choice | `docs/operations/LIVE-TRADING-RUNBOOK.md`; `docs/decisions/ADR-0022` decision 8 | **PASS** (as designed) | No | **Yes** -- whether to ever automate cancel-on-shutdown | Human decides if/when automated cancellation should be built |
| Audit | Every critical event leaves a persisted record | Confirmed for broker/data/reconciliation/kill-switch/model/provider failures | `docs/specifications/PHASE-17-production-safety-review.md` section 6 | **PASS** | No | No | None |
| Secrets | Credential access confined to one file, never persisted | Re-verified repo-wide this phase (broader than Phase 13's package-scoped check) | `tests/broker/live/test_production_safety_cross_cutting.py::TestSecretAccessIsConfinedToOneFileAcrossTheWholeSrcTree` | **PASS** | No | No | None |
| Runbook | Procedures match actual code; no secret values stored in it | Re-read and mechanically verified this phase | `tests/broker/live/test_production_safety_cross_cutting.py::TestRunbookReferencesStillResolveInCode` | **PASS** | No | No | None |
| Benchmark | S&P 500 Buy & Hold uses the same period/capital/cost assumptions as the run it's compared against | True for the historical Backtest engine (`backtest.benchmark.BenchmarkResult` shares `initial_capital`/cost model by construction); **no Paper-side benchmark comparison exists at all** | `src/backtest/benchmark.py`; section 7 above | **PASS (Backtest)** / **NOT IMPLEMENTED (Paper)** | No (not independently blocking) | No | Same as the Paper performance-report gap |
| Transaction Cost | Modeled and attributed | Implemented in both Backtest (`backtest.metrics`) and Paper (`Fill.commission`/`spread_cost`), per-fill | `src/broker/paper/journal.py`; `backtest/metrics.py` | **PASS** (per-fill); **NOT IMPLEMENTED** (aggregated into a Paper-level report) | No | No | Same as the Paper performance-report gap |
| Slippage | Modeled and attributed | Implemented per-fill in both Backtest and Paper (`Fill.slippage_cost`); **not computed at all for Live** (`broker.live.journal.build_fill_from_broker_response` sets `slippage_cost=0.0`, documented as an honest limitation, no independent quote to compare against) | `src/broker/live/journal.py`; `docs/decisions/ADR-0022` decision 9 | **PASS** (Backtest/Paper); **KNOWN LIMITATION** (Live) | No | No | Unchanged from Phase 16 -- would require an independently-sourced quote feed |
| OOS (Out-of-Sample) | Validation split distinct from training | `learning.config.SplitConfig` (train/validation/test), chronological | `src/learning/config.py`; `src/learning/dataset.py` | **PASS** (split exists) | No | No | None -- statistical robustness (PBO/overfitting) remains explicitly deferred, see next row |
| Walk Forward | Rolling-window re-validation / PBO / Deflated Sharpe | **Explicitly deferred since Phase 9**, re-confirmed unimplemented this phase | `docs/decisions/ADR-0017-model-evolution.md` decision 3, alternatives #2 | **NOT IMPLEMENTED** | No (not independently blocking Live, since it gates model *quality* confidence, not a hard safety boundary) | **Yes** -- whether Live activation should ever require this before deploying a non-trivial model | Human decides whether a future phase should build PBO/Deflated Sharpe/Walk-Forward validation before trusting any non-baseline candidate model |

## Overall

No row above claims `CapabilityStatus.ENABLED` for a capability this
review could not verify against official documentation, and no row
was marked PASS on the strength of an automated test alone without a
cited file. Four rows are independently **Blocking** (Toss API,
Account, Positions, Cancellation) -- Live activation is blocked by
Toss's own capability gaps regardless of how every other row scores,
per `docs/decisions/ADR-0022-live-trading.md` decision 2 and reconfirmed
structurally this phase.
