# ADR-0197: External Audit P2 Findings — Batches D/E (Risk/Live, Trade Journal)

**Status:** Accepted
**Date:** 2026-09-24
**Deciders:** Claude Code session (continuing ADR-0195/ADR-0196's audit pass), account owner
**Related documents:** `docs/decisions/ADR-0195-external-audit-p1-fixes-2026-09-24.md`,
`docs/decisions/ADR-0196-external-audit-p2-batch-abc-2026-09-24.md`,
`docs/decisions/ADR-0177-p1-3-cycle-level-cumulative-risk-exposure.md`,
independent 13-stage audit report of commit `76ab684`

---

## Context

Continues ADR-0196's batch-by-batch processing of the audit's remaining
scope. This ADR covers Stage 4 (risk/live) and Stage 5 (trade journal),
under the same discipline: every finding independently reproduced before
being called a bug; a finding that is real but already safely mitigated,
or has zero current blast radius, is documented as such rather than
force-fixed.

## Decision — Batch D (Stage 4, `src/orchestration/live_runner.py`)

- **Same-cycle TOCTOU gap never backported to Live (real bug, fixed):**
  ADR-0177 fixed `paper_runner.run_cycle`'s single-stale-snapshot gap (a
  second security's risk check saw the same pre-cycle `PortfolioView` as
  the first, letting two individually-passing BUYs together breach
  `RiskConfig.max_gross_exposure`) — but never backported it to
  `live_runner.run_cycle`, where the exact same gap applies to real
  money. Fixed by applying the identical in-memory "as if already
  filled at `current_price`" ESTIMATE technique ADR-0177 already
  validated (never touches `session`'s real broker/accounting state,
  never claims a real fill happened) — applied uniformly whether the
  broker's own response was already FILLED/PARTIAL_FILLED or still
  PENDING, since an outstanding live order can still fill later and
  must count against the same cycle's own risk budget either way.
- **Live `turnover` never threaded to `risk_engine.assess` (real gap,
  deliberately deferred):** `paper_runner.py` already fixed this
  (`turnover=session.adapter.accounting.turnover()`), but
  `PortfolioAccounting.turnover()` is a Paper-broker-specific method —
  Live's `BrokerAdapter`/`MockBrokerAdapter` have no equivalent, since
  Live doesn't track its own in-process valuation history (it queries
  the real broker). A correct Live turnover would need to be computed
  from real trade history over a real trailing window — a genuine new
  design decision (data source, window), not a copy-paste backport.
  Currently zero blast radius: no live-trading production CLI exists in
  this repository yet (`scripts/run_live_trading_cycle.py` does not
  exist), so `RiskConfig.max_turnover` can never actually be configured
  for a real Live run today. Deferred until a real Live production
  entrypoint is built, at which point the correct turnover data source
  becomes an answerable question instead of a guess.
- **`liquidity_state`/`enforce_liquidity_limit` dead config (real gap,
  deliberately deferred):** Neither `paper_runner.py` nor
  `live_runner.py` ever passes a real `liquidity_state` to
  `risk_engine.assess` — the check is real and tested
  (`risk/engine.py`), but nothing in this codebase computes a real
  liquidity classification (e.g. from ADV/order-size ratio) to feed it.
  This is an entirely new module, not a threading fix — deferred rather
  than built speculatively under this pass's scope.
- **Reentry cooldown (`last_exit_time_by_security`):** re-verified — this
  is already fully wired for Live (`live_runner._last_exit_time_by_security`,
  documented as the "Live-side equivalent of `paper_runner.
  _last_exit_time_by_security`"). Not a gap.

## Decision — Batch E (Stage 5, `src/orchestration/paper_runner.py`, `src/trade_journal/experience.py`)

- **`predict.experience.attach_prediction_context`/
  `regime.experience.attach_regime_context` have zero production
  callers (real gap, deliberately deferred):** Verified via a repo-wide
  search — only tests exercise either function. Re-verified the field
  they populate (`ExperienceRecord.expected_outcome`) is itself never
  read by anything in `learning/*` (write-only, dead data downstream).
  Wiring the enrichers into `scripts/run_learning_cycle.py` now would
  populate a field nothing consumes — speculative until a real consumer
  exists, same "adopt now, wire in later" precedent as the Grounding
  Gate deferral already recorded in this repository's `CLAUDE.md`.
- **A delayed (T+1) fill whose decision can't be re-located was skipped
  entirely silently (real bug, fixed):** `_record_delayed_advance_fills`
  correctly, deliberately never fabricates a `TradeRecord`/
  `DecisionSnapshot` link when the originating decision can't be
  re-located (e.g. `trade_journal_repository` was absent during the
  original submission) — but the skip itself had no counter, no log,
  nothing a caller could ever notice. A real trade's economic outcome
  could permanently drop out of the Trade Journal with zero signal.
  Fixed by adding `PaperRunnerState.skipped_delayed_fills` (same
  "recorded here, one entry per cycle where the list was non-empty, so
  a caller can surface it" pattern `mark_to_market_missing`/
  `corporate_action_warnings` already established), surfaced in both
  `scripts/run_paper_trading_cycle.py` and
  `scripts/run_multi_strategy_paper_trading_cycle.py`'s stdout warnings
  and report JSON.
- **No human-approval CLI tool for `LiveActivationApproval` (real gap,
  deliberately deferred, audit's own note: 안전 방향/fail-safe
  direction):** `SafetyGateContext`'s own gate fails closed
  (`activation_approval_missing_or_invalid`) whenever `approval` is
  `None` or invalid — the absence of a tool to grant it means every
  live order is blocked by default, never the reverse. Zero current
  blast radius (same reason as the Live turnover gap above: no Live
  production CLI entrypoint exists yet). Building a real approval
  workflow tool is a new feature, not a bug fix — deferred to whenever
  Live trading gets a real production entrypoint.
- **`ExperienceRecord.decision_id` can point to a non-existent decision
  (real, confirmed structural fact, not an active correctness bug):**
  `trade_journal.experience.build_experience_records` copies
  `trade.decision_id` onto `ExperienceRecord.decision_id`
  unconditionally, even when `journal.get_decision(trade.decision_id)`
  itself just returned `None` (every other `decision.*`-derived field
  already correctly falls back via `if decision is not None else ...`
  guards — this one field does not, and `decision_id: str` is
  non-Optional, so it cannot simply be nulled out without a type/schema
  change). Verified the actual training consumer,
  `learning.cleaning.DataCleaner.clean`, independently re-queries
  `journal.get_decision(record.decision_id)` itself and excludes any
  sample where that returns `None` (`SampleStatus.UNKNOWN`, reason
  `"missing_decision"`) — so a dangling `decision_id` is already
  guaranteed to be excluded from training, never silently used as if
  valid. Documented rather than fixed: the persisted row can carry an
  unresolvable pointer, but nothing downstream trusts it without
  re-verifying.

## Consequences

- A real Live cycle submitting multiple BUYs in one call now correctly
  enforces cumulative gross exposure across all of them, closing a
  real-money version of the gap ADR-0177 already closed for Paper
  Trading.
- A Paper Trading run that silently lost a delayed fill's Trade Journal
  record now surfaces it (stdout warning + report JSON field), matching
  the existing `mark_to_market_missing`/`corporate_action_warnings`
  pattern exactly.
- Three findings (Live `turnover`, `liquidity_state`, human-approval
  tool) are real, legitimate gaps but deliberately deferred — each
  either requires a genuine new design decision beyond this pass's scope
  or currently has zero blast radius because no Live production
  entrypoint exists yet in this repository. Revisit each when a real
  Live production CLI is built, not as a side effect of this pass.
- One finding (experience/regime enrichers) is deferred for the same
  "nothing consumes the output yet" reason already established for the
  Grounding Gate.
- One finding (`ExperienceRecord.decision_id` dangling lineage) is
  confirmed real but already safe — documented, not fixed, since the
  actual training consumer already re-validates independently.
- Regression tests added: 2 (Live TOCTOU backport, mirroring ADR-0177's
  own paper-side test class), 1 (`skipped_delayed_fills` surfacing) —
  full suite (3728 tests) passes.
