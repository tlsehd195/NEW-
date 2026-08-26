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
- [ ] `TOSS_API_KEY`/`TOSS_API_SECRET`/`TOSS_ACCOUNT_ID` are set in the
      deployment environment, never in a file tracked by git.
- [ ] A specific `max_daily_loss` and, if desired, a
      `max_order_frequency_per_hour` have been decided by whoever is
      financially responsible for this account and set on
      `LiveTradingConfig` — this repository ships neither value
      (`PROJECT_MASTER_PLAN.md` §13.12 defers the capital-policy
      decision explicitly).
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

1. Compute `LiveTradingConfig.configuration_version()` and record it in
   the activation log (not this file) alongside the approval you are
   about to give.
2. Confirm the running code's git commit hash matches what was reviewed
   before this activation attempt.

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
3. This system does **not** automatically cancel open orders on
   shutdown (a deliberate choice, not an oversight — see ADR-0022 §8 of
   the spec's Known Limitations). Decide manually whether to cancel
   each open order, and do so explicitly if so.

## Emergency Halt / Kill Switch

- `broker.live.kill_switch.engage_kill_switch(...)` can be, and in
  several conditions automatically is, called by `LiveTradingSession`
  itself — this requires no human action to take effect.
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
