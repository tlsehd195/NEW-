# Live Trading Runbook

This document is a manual operational procedure for a human operator.
No part of it is executable by this repository's own code, and nothing
in `src/` reads this file. It exists because `broker.live.
safety_gate.evaluate_safety_gate` requires several inputs
(`LiveActivationApproval`, `SafetyGateContext`) that this repository's
own code deliberately never assembles on its own behalf — assembling
them is this document's job.

**No secret value belongs in this document. Ever.** Where a step says
"verify credential availability," it means confirm the referenced
environment variable resolves successfully through `broker.toss.auth`
(the only file in this codebase permitted to read it) — never paste,
log, or record the value itself here or anywhere else.

## Prerequisites

- [ ] `PROJECT_MASTER_PLAN.md` §13.11's Go-Live Gate items are all
      independently confirmed PASS (Data validation, Backtest, OOS,
      Risk tests, Leakage tests, Paper trading, Broker tests, Kill
      switch, Rollback, Monitoring).
- [ ] Toss Securities' `cancel_order`/`get_order_status`/`get_account`/
      `get_positions` endpoints have been confirmed against the
      official `/openapi-docs/latest/openapi.json` and
      `TossBrokerAdapter.get_capabilities()` updated to report
      `ENABLED` for whichever are confirmed
      (`docs/decisions/ADR-0022-live-trading.md` §"Known Limitations" —
      until this is done, `evaluate_safety_gate` will refuse to
      authorize any submission needing those capabilities, by design).
      **Phase 21 status**: the official OpenAPI spec for all four
      endpoints/schemas is documented (Tier 1 evidence,
      `docs/operations/TOSS-API-GAP-ANALYSIS.md` Phase 21 addendum) and
      `TossBrokerAdapter` now implements all four against it
      (`docs/decisions/ADR-0027-toss-broker-adapter-completion.md`,
      63 new tests, all against a stub transport). **No real
      credentials have ever been used against them, and
      `get_capabilities()` still reports all four `UNKNOWN`.** This
      checkbox stays unchecked until a human operator independently
      verifies each call against a real account and only then promotes
      the corresponding `CapabilityStatus` to `ENABLED` in code —
      implemented and tested is not the same as operationally verified.
- [ ] `TOSS_API_KEY`/`TOSS_API_SECRET`/`TOSS_ACCOUNT_ID` are set in the
      deployment environment, never in a file tracked by git.
- [ ] A specific `max_daily_loss`, `max_turnover`, and, if desired, a
      `max_order_frequency_per_hour` have been decided by whoever is
      financially responsible for this account and set on
      `LiveTradingConfig`/`RiskConfig` — this repository ships none of
      these values by default (`PROJECT_MASTER_PLAN.md` §13.12 defers
      the capital-policy decision explicitly). Phase 20 added *proposed*
      starting values with rationale (2% of initial capital / 3.0 /
      30 — `docs/operations/LIVE-RISK-POLICY.md` "Phase 20 -- Proposed
      initial values") for review, but they are not ratified and take
      no effect until explicitly set here.
- [ ] The capital amount to be exposed has been decided separately, per
      §13.12's "Paper → Small Capital → Controlled Expansion" principle
      — never the full account balance on a first activation.

## Environment Setup

1. Confirm the deployment's `environment` value is exactly `"live"` —
   `LiveTradingConfig.environment` will refuse construction with any
   other value.
2. Confirm no other process on this account is concurrently trading
   (manual check — this codebase does not coordinate with external
   actors on the same account, §30).
3. Confirm `BrokerConfig.execution_mode == LIVE` and
   `BrokerConfig.live_opt_in == True` are both set explicitly (Phase 13
   — neither alone is sufficient).

## Configuration Validation

1. Compute `LiveTradingConfig.configuration_version()` using
   `python3 scripts/print_live_configuration_version.py` (ADR-0078)
   with the exact same flags the real config will be constructed with
   -- this computes the hash with the identical code
   `orchestration.live_runner.run_cycle`'s `configuration_integrity_valid`
   check will later compare against, rather than one computed by hand.
   Record BOTH the printed hash AND the full field dump the script
   prints alongside it in the activation log (not this file, per the
   existing convention) -- a bare hash with no record of which fields
   produced it cannot be verified later. That recorded hash is what
   gets passed as `run_cycle`'s `pinned_configuration_version` going
   forward.
2. Confirm the running code's git commit hash matches what was reviewed
   before this activation attempt.
3. Rotating the pin (after any reviewed config change) means
   deliberately re-running step 1 and recording a NEW activation-log
   entry -- never silently, and never by editing the previous entry in
   place (the activation log is append-only, matching this project's
   own audit-trail discipline everywhere else).

## Safety Checks (before every activation, not just the first)

Assemble a `broker.live.safety_gate.SafetyGateContext` from live,
current data and confirm `evaluate_safety_gate(...).passed is True`. If
it is `False`, read `failed_conditions` — each one names exactly which
prerequisite is unmet. Do not proceed until every condition is
satisfied on its own; there is no override.

## Startup

1. Construct a `broker.toss.adapter.TossBrokerAdapter` with the real,
   resolved credentials (via `broker.toss.auth`, never inline).
2. Call `broker.live.session.run_startup_checks(...)` with the
   assembled context plus any known reconciliation results. Confirm
   `ready is True`.
3. If not ready, resolve every `blocking_reasons` entry before
   proceeding — do not skip any of them.

## Reconciliation (before every resume, including after any restart)

1. Fetch the broker's own `get_account()`/`get_positions()`/
   `get_order_status()` for every open order.
2. Run `compare_account`/`compare_positions`/`compare_order_status`
   against this system's own last-known internal state.
3. Any `MISMATCH` or `UNKNOWN` result means: **do not submit any new
   order**. Investigate the discrepancy manually first. Never assume
   either side is correct without confirming independently (e.g.
   directly in the Toss app/website).

## Human Confirmation and Activation

1. Complete the checklist above.
2. Construct a `broker.live.approval.LiveActivationApproval` with your
   own real identity, the current timestamp, the exact required
   confirmation phrase (`broker.live.approval.
   REQUIRED_CONFIRMATION_TOKEN`), and `checklist_completed=True`.
3. Only once this object exists and the safety gate independently
   passes does `LiveTradingConfig.live_trading_enabled=True` have any
   effect — set it, and only then, as the final step.
4. Submit a single, small, deliberately conservative first order and
   verify its full lifecycle (submission → fill/reject →
   reconciliation → Trade Journal record → Monitoring event) before
   any further activity.

## Restricted First Execution

- Trade the smallest meaningful quantity the account/security allows.
- Manually verify the fill against the Toss app/website independently
  of this system's own reported state, before trusting the system's
  state for any further order.

## Shutdown

1. Set `live_trading_enabled=False` (or otherwise stop calling
   `LiveTradingSession.submit`) — no new orders will be accepted going
   forward.
2. Call `broker.live.session.run_shutdown_checks(...)` and record the
   returned open-order list.
3. This general, planned shutdown path (end of day, maintenance) still
   does **not** automatically cancel open orders — that remains a
   manual decision for this path specifically. Decide manually whether
   to cancel each open order, and do so explicitly if so. **This is
   distinct from an emergency kill-switch engagement, which now DOES
   auto-cancel — see below.**

## Emergency Halt / Kill Switch

- `broker.live.kill_switch.engage_kill_switch(...)` can be, and in
  several conditions automatically is, called by `LiveTradingSession`
  itself — this requires no human action to take effect.
- **Session 36 (ADR-0045): `LiveTradingSession.engage_kill_switch(...)`
  now automatically attempts to cancel every order this session does
  not already know to be closed** (`LiveTradingConfig.
  auto_cancel_on_kill_switch`, `True` by default) — a runaway order
  loop or any other kill-switch trigger no longer leaves working orders
  unmanaged while waiting for a human to act. The call now returns a
  `KillSwitchEngagementResult` (`event` plus `cancellation_outcomes`,
  one `OrderCancellationOutcome` per order the auto-cancel pass
  attempted) instead of the bare `KillSwitchEvent` it used to. **Still
  run the full Reconciliation section after any engagement regardless**
  — a cancel attempt can itself fail or return `UNKNOWN`
  (`cancellation_outcomes[i].cancelled=False`), and even a successful
  cancellation does not confirm the broker's own book matches this
  session's — only reconciliation does that.
- Releasing it requires constructing a `LiveActivationApproval` exactly
  as in the Activation section above, then calling
  `LiveTradingSession.release_kill_switch(approval, ...)`. There is no
  other way to clear an engaged kill switch anywhere in this codebase.
- After any kill-switch engagement, run the full Reconciliation section
  again before releasing it — an engagement is itself evidence
  something needs independent verification.

## Broker Outage

If `TossBrokerAdapter` raises `BrokerTransportError`/
`BrokerTimeoutError` repeatedly: do not retry submissions blindly.
Every submission failure leaves the affected order `UNKNOWN` and blocks
further submissions system-wide until reconciled (§9 of the spec) —
this is intentional. Wait for connectivity to recover, then run the
Reconciliation section before resuming.

## Unknown Order State

An order in `BrokerOrderStatus.UNKNOWN` (either from a submission
exception, or because `TossBrokerAdapter`'s `get_order_status`/
`cancel_order` capabilities remain unconfirmed, see Prerequisites) must
be resolved by directly checking the Toss app/website for that specific
order before this system is trusted to act on that security again.

## Account Mismatch

A `MISMATCH` reconciliation result on the account or any position means
this system's internal ledger and the broker's authoritative state
disagree. Do not resume trading until you understand *why* — a manual
order placed outside this system, a missed fill, or a genuine bug are
all possible causes with very different correct responses.

## Recovery

After resolving any of the above, re-run the full Safety Checks and
Reconciliation sections from the top before resuming — do not assume a
partial fix means the system is fully consistent again.

## Audit Review

Every session should end with a review of:

- `kill_switch_events` (any engagement and its resolution)
- `reconciliation_events` (any mismatch and how it was resolved)
- `broker_requests`/`broker_responses`/`order_status_events` for the
  session's own activity
- `trades` for the resulting `TradeRecord`s, confirming
  `provenance == LIVE_TRADING` throughout

No secret value should ever appear in any of these tables — confirm
this periodically, not just once.
