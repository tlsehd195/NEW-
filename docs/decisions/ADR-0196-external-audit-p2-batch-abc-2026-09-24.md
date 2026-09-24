# ADR-0196: External Audit P2 Findings — Batches A/B/C (Data, Backtest, Decision)

**Status:** Accepted
**Date:** 2026-09-24
**Deciders:** Claude Code session (continuing ADR-0195's P1 pass), account owner
**Related documents:** `docs/decisions/ADR-0195-external-audit-p1-fixes-2026-09-24.md`,
independent 13-stage audit report of commit `76ab684`

---

## Context

ADR-0195 fixed the audit report's 5 P1 findings. The account owner then asked
for the report's full remaining scope to be processed ("전부 처리"): ~20 P2
findings across 10 stages, many P3 findings, and 7 outstanding
doc-vs-code mismatches. This ADR documents the first three batches
(Stage 1 데이터/유니버스, Stage 2 백테스트, Stage 3 decision) under the same
discipline ADR-0195 established: every finding is independently reproduced
against real code/tests before being called a bug; only confirmed bugs are
fixed; findings that turn out to already be correctly, deliberately
documented are recorded as such rather than re-fixed or silently dropped.

## Decision — Batch A (Stage 1, `scripts/*market_data*.py`, `scripts/run_long_horizon_validation.py`)

- **F-1 (real bug, fixed):** `import_external_market_data.py` exited 0 even
  when every requested symbol produced zero bars (e.g. all header-only
  CSVs) — `missing_symbols` was computed and written to the manifest but
  never checked by the return statement. Fixed by failing the run (exit 1)
  when `missing_symbols` covers every requested symbol, mirroring the
  existing `unexplained_zero_bar_symbols` severity threshold.
- **F-2 (real bug, fixed):** `ingest_real_market_data.py`'s corporate-action
  collection loop already caught and recorded per-symbol failures into
  `corporate_action_results`, but nothing read that list back — a run where
  corporate-action collection failed for every symbol still exited 0,
  silently shipping price bars that were never split/dividend-adjusted.
  Fixed by adding `corporate_action_failed_symbols`/
  `corporate_actions_entirely_failed` (same "entire run got nothing"
  conservative threshold as F-1) to the manifest and the exit-code gate.
- **F-3 (not a bug, already documented):** `provider.py::bar_available_time`'s
  fixed 20:00 UTC offset (a real DST blind spot) is already explicitly
  documented in the constant's own docstring as a deliberate, matched
  convention shared with `backtest.clock.build_daily_checkpoints`, left
  for a future session that revisits both together.
- **F-4 (real gap, deliberately deferred):** `security_master`/
  `universe_membership` tables carry no `Provenance` columns, unlike
  `corporate_actions`/`benchmark_points`. Re-verified against ADR-0003,
  which explicitly scoped the shared `Provenance` value object to exactly
  those two types plus `PriceBar` — not an oversight, a decision. Adding it
  now would touch the schema, two dataclasses, 3 real writers, and ~10 test
  fixtures for a traceability improvement with no active correctness
  consequence (no test or code path currently produces a wrong decision
  from its absence). Deferred with this reasoning recorded, same as
  ADR-0195's P1-4 trainer-hyperparameter scoping decision — revisit if a
  future session needs to audit where a specific security's listing dates
  actually came from.
- **F-5 (not a bug, already documented):** No provider (`tiingo.py`) ever
  produces `MERGER`/`ACQUISITION`/`SPIN_OFF`/`TICKER_CHANGE`/`DELISTING`/
  `SPECIAL_DIVIDEND` corporate actions. Already explicitly documented as an
  accepted, out-of-scope limitation in ADR-0179 and PHASE-2 spec section 8.4.
- **F-6 (real bug, fixed):** `run_long_horizon_validation.py`'s
  `_KNOWN_REAL_PROVIDER_SOURCES` allowlist (`{"tiingo", "stooq"}`) was never
  updated when ADR-0164 replaced stooq with
  `FallbackDataProvider(tiingo, twelvedata, alphavantage)` — a real run
  using genuine ADR-0164-era Twelve Data/Alpha Vantage data would have
  been wrongly refused as "unexpected sources". Fixed by adding
  `"twelvedata"`/`"alphavantage"` (verified against each provider's own
  `Provenance.source` literal). The pre-existing regression test for this
  allowlist asserted the exact stale set and passed — rewritten to check
  every provider module in the package, not just the two the allowlist
  already had, so it would have caught this the first time.
- **F-7 (not a bug, already documented):** `universe.py::build_security_masters`
  using `security_id=s.symbol` (ticker as ID) is already explicitly
  explained in the function's own docstring.

## Decision — Batch B (Stage 2, `src/backtest/engine.py`)

- **Configuration-version hash gap (real bug, fixed):** `configuration_version`
  (a content hash meant to fingerprint a backtest run's full configuration)
  omitted `slippage_model`, `risk_free_rate`, and `periods_per_year` even
  though all three already feed real fills/performance computation in the
  same `run()` call. Two runs differing ONLY in slippage model or
  risk-free rate produced genuinely different results but hashed to the
  identical `configuration_version` — the same "content hash must include
  every field that is actually content" class of gap ADR-0195/P1-4 fixed
  for `learning.dataset.sample_fingerprint`. Fixed by adding all three
  fields to the hash input.
- **embargo=0 (not a bug, already documented):** Explicitly, deliberately
  documented in ADR-0008 as an accepted validation-protocol scope decision
  — matches the audit's own note that this is intentional.
- **Long-gap average-cost fallback → PASSED_WITH_WARNINGS (not a bug,
  already honestly disclosed):** `check_missing_data` reports a WARNING
  (not silently) whenever a held position is valued at average cost due to
  missing price data; the resulting `IntegrityStatus.PASSED_WITH_WARNINGS`
  is a real, inspectable field on every `IntegrityReport` — a caller can
  always tell. `check_delisted_position_marked_at_cost` (already added,
  see the module) separately upgrades this to ERROR specifically for a
  CONFIRMED delisting, where average-cost is never a plausible valuation.
  No further fix needed for the ordinary temporary-gap case.
- **PIT-unspecified default run's survivorship exposure:** folded into
  Batch K (doc-vs-code corrections) below, since this is the same claim as
  the Phase 1 spec's survivorship-bias-free wording.

## Decision — Batch C (Stage 3, `src/decision/agent.py`, `src/trade_journal/models.py`)

- **NaN uncertainty silently skips its own gate (real bug, fixed):**
  `uncertainty_exceeds_signal`'s guard used
  `abs(expected_return) <= uncertainty * ratio`; a NaN `uncertainty` makes
  every such comparison evaluate to `False` in Python, so the gate that
  exists specifically to block low-signal-to-noise trades was silently
  skipped instead of blocking one.
- **±inf expected_return produces a directional BUY/SELL (real bug,
  fixed):** `expected_return >= config.min_expected_return` is
  unconditionally satisfied by `+inf`, producing BUY from a value no real
  predictor should ever emit (NaN was already accidentally safe — every
  comparison against it is `False`, falling through to the final
  `NO_TRADE` — but relied on an accident, not a deliberate check).
  Both fixed together with one explicit `math.isfinite()` gate placed
  immediately after the existing `prediction_unavailable` check, fail-
  closed to `NO_TRADE` with reason `"non_finite_prediction_value"` —
  consistent with this function's own documented invariant ("no rule ever
  produces BUY/SELL by falling through an unhandled case").
- **`DecisionSnapshot` had no stored link back to the `DecisionOutput`/
  `PredictionOutput` that produced it (real gap, fixed):** ADR-0113
  (Session 37) made `DecisionSnapshot.snapshot_id` the real, joinable
  `TradeRecord.decision_id`, closing ADR-0097's original "not joinable"
  gap — but the snapshot itself still carried no `decision_output_id`/
  `prediction_id` fields, so the only way back to the authoritative
  Phase 7 records was a separate, unindexed lookup via
  `decision_repository`. Added both fields to `DecisionSnapshot`
  (`trade_journal/models.py`), wired through `storage/serialization.py`'s
  payload round-trip (no DuckDB schema migration needed — this dataclass
  persists as a single `payload_json` column), and populated at the one
  real production call site (`orchestration/paper_runner.py`'s
  `record_decision(...)` call) from `decision.decision_id`/
  `decision.prediction_id`. The two in-memory/DuckDB repository
  implementations needed no code change — both already forward `**fields`
  straight into `DecisionSnapshot(...)`.
- **`DecisionAction.EXIT` never produced (not a bug, already documented):**
  PHASE-7 spec section 6 explicitly states "`DecisionAction.EXIT` is
  reserved, never produced by this agent" — matches an existing pinned
  test (`test_exit_is_reserved_not_produced_by_the_baseline_agent`).

## Consequences

- Two previously-silent fail-open paths in the decision layer (NaN
  uncertainty, ±inf expected return) are now fail-closed, matching this
  project's own stated invariant.
- A real Paper Trading run using Twelve Data/Alpha Vantage as its primary
  real-data source will no longer be wrongly refused by
  `run_long_horizon_validation.py`'s REAL-provenance check.
- Two ingestion scripts that previously could exit 0 on a run that
  ingested nothing (or lost every corporate action) now fail loudly,
  matching the existing `unexplained_zero_bar_symbols` precedent.
- `configuration_version` is now a genuine content hash of everything that
  affects a backtest run's result, closing the same class of gap already
  fixed once this session for `learning.dataset`.
- `DecisionSnapshot` records written by real Paper Trading cycles are now
  traceable back to their originating `DecisionOutput`/`PredictionOutput`
  without a separate, natural-key-only lookup.
- Four findings (F-3, F-5, F-7, embargo=0, long-gap WARNING, EXIT) were
  independently re-verified and found to already be correctly, honestly
  documented — recorded here rather than silently dropped or redundantly
  re-fixed, per this session's established verification discipline.
- One finding (F-4, `SecurityMaster`/`UniverseMembership` provenance) is a
  real, legitimate gap but deliberately deferred — no active correctness
  bug depends on it, and ADR-0003 already scoped it out once with clear
  reasoning; revisit only if a future session needs to audit a security's
  own data lineage, not as a side effect of this pass.
- Regression tests added: 1 (F-1), 5 (F-2), 1 (F-6, rewritten to check
  every provider module), 2 (configuration_version hash), 4 (NaN/inf
  gates), 2 (`DecisionSnapshot` link) — full suite (3725 tests) passes.
