# ADR-0200: External Audit P2 Findings — Batch I (Stage 9 Live Trading)

**Status:** Accepted
**Date:** 2026-09-25
**Deciders:** Claude Code session (continuing ADR-0195 through ADR-0199's audit pass), account owner
**Related documents:** `docs/decisions/ADR-0195-external-audit-p1-fixes-2026-09-24.md`
through `ADR-0199`, `docs/operations/LIVE-RISK-POLICY.md`,
independent 13-stage audit report of commit `76ab684`

---

## Context

Continues the batch-by-batch processing of the audit's remaining scope.
This ADR covers Stage 9 (Live Trading), under the same discipline: every
finding independently reproduced against real code/tests before being
called a bug.

## Decision

- **F1 — `required_capabilities=()` vacuously passing the broker-
  capability gate:** identical finding to Batch G's own F1 (Stage 7).
  Already re-verified there against `LIVE-RISK-POLICY.md`'s own prior
  correction — not re-litigated here.
- **F2 — `broker.pipeline.submit_validated_order` has no safety gate
  (real gap, documented, not code-changed):** it calls
  `adapter.submit_order(...)` directly and unconditionally — no kill
  switch, no `LiveActivationApproval`, no `evaluate_safety_gate` call
  at all. Verified this is deliberate: the module is adapter-agnostic
  infrastructure with no way to know whether its caller already gated,
  and its one real production caller today
  (`broker.paper.us_longterm_runner.run_buy_and_hold_paper_session`,
  `execution_mode="PAPER"`) needs no gate — Paper Trading has no kill
  switch/approval concept. `LiveTradingSession.submit` (the real, gated
  Live path) calls `adapter.submit_order` directly itself, never
  through this function, so there is currently no live caller of the
  gate-less path. Added a loud docstring warning naming the risk
  explicitly, so a future caller wiring a real Live production
  entrypoint cannot reach for this function (the only one currently
  producing the `broker_requests`/`broker_responses` audit trail
  monitoring depends on) without being told, in the one place they'd
  look, that it provides no protection on its own.
- **F3 — a genuine reconciliation MISMATCH never blocked new
  submissions while ACTIVE (real bug, fixed):**
  `LiveTradingSession.reconcile_order` only ever reacted to
  `ReconciliationStatus.MATCHED` — a confirmed disagreement between
  this session's own internal order status and the broker's real
  reported one (`MISMATCH`, distinct from `UNKNOWN`, which is what
  happens when either side's state is simply unavailable) did nothing
  to `_operational_state` at all. Reproduced directly: a session left
  ACTIVE after a real submission, with its own internal record then
  drifted from the broker's real (synchronously-filled, in the mock)
  status, continued accepting new submissions after `reconcile_order`
  confirmed the mismatch. Fixed by forcing `OperationalState.
  RECONCILIATION_REQUIRED` unconditionally on a MISMATCH result — never
  gated behind a failure-count threshold, since a single confirmed
  mismatch is already a real, not merely suspected, inconsistency,
  matching the fail-closed treatment `submit`'s own consecutive-
  failure/UNKNOWN-response paths already give a broker-reported
  ambiguity.
- **F4 — zero automatic callers of `reconcile_order`/reconciliation
  (real gap, deliberately deferred):** confirmed via a repo-wide search
  — only `broker/live/session.py` itself defines the method; no
  orchestration or monitoring script ever calls it. Building a periodic
  reconciliation driver is a genuine new feature (what triggers it, how
  often, what it does with a MISMATCH beyond the F3 fix above) and, like
  every other Live-trading gap this session's audit passes have found,
  currently has zero blast radius: no Live production CLI entrypoint
  exists in this repository yet. Deferred to whenever one is built.
- **F5 — an unavailable individual position was silently treated as a
  zero position, while `position_state_known` stayed hardcoded `True`
  (real bug, fixed):** `orchestration.live_runner._live_portfolio_view`
  already raises when the broker cannot report ACCOUNT-level cash
  (`live_account_unavailable`), but a per-security `BrokerPosition`
  with `available=False` was silently `continue`d out of the resulting
  `positions` dict — indistinguishable from a genuine zero position.
  `run_cycle` then hardcodes `position_state_known=True` on every
  `gate_context` regardless, relying on `_live_portfolio_view`'s own
  "raise, never fabricate" docstring claim to make that hardcoding
  safe — a claim this one path did not actually keep. Reproduced
  directly via a test adapter injecting one `available=False` position
  alongside real ones. Fixed by raising the identical class of error
  (`live_position_unavailable`) for a per-position read failure, exactly
  mirroring the existing account-level behavior.
- **F9 — ADR-0022 Toss Live claim (documentation issue):** deferred to
  the Batch K (문서 vs 코드 불일치) pass, not a code defect.

## Consequences

- A real Live session whose own bookkeeping has confirmably drifted
  from the broker's real reported order state can no longer keep
  accepting new submissions — it now halts, exactly like an UNKNOWN
  broker response already does.
- A real Live cycle can no longer silently treat "the broker could not
  confirm this position" as "you hold zero shares" — it now fails
  loudly instead, keeping the `position_state_known=True` hardcoding
  this project already relies on actually true.
- `broker.pipeline.submit_validated_order`'s gate-less nature is now
  loudly documented in the one place a future caller would look before
  reaching for it.
- Two findings (`required_capabilities=()`, zero reconciliation
  callers) are real but either already documented elsewhere (F1) or
  have zero current blast radius pending a real Live production
  entrypoint that does not exist yet (F4) — recorded, not force-fixed.
- Regression tests added: 1 (F3, MISMATCH-while-ACTIVE blocking), 1 (F5,
  per-position unavailability raising) — full suite (3739 tests) passes.
