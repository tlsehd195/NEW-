# ADR-0201: External Audit P2 Findings — Batch J (Stage 10 Monitoring)

**Status:** Accepted
**Date:** 2026-09-25
**Deciders:** Claude Code session (continuing ADR-0195 through ADR-0200's audit pass), account owner
**Related documents:** `docs/decisions/ADR-0195-external-audit-p1-fixes-2026-09-24.md`
through `ADR-0200`, independent 13-stage audit report of commit `76ab684`

---

## Context

Continues the batch-by-batch processing of the audit's remaining scope.
This ADR covers Stage 10 (Monitoring), under the same discipline: every
finding independently reproduced against real code/tests before being
called a bug.

## Decision

- **ACCOUNT drawdown mis-displayed as HEALTHY when unconfigured (real
  bug, fixed):** `monitoring.health.evaluate_account_health`'s
  `max_drawdown is None` branch previously reported
  `ComponentHealthStatus.HEALTHY` (reason `"max_drawdown_not_
  configured"`) regardless of the real drawdown — a real account in a
  severe real drawdown, run with `run_paper_trading_cycle.py`'s own
  `--max-drawdown` CLI default (`None`), would show ACCOUNT as HEALTHY
  in monitoring. This directly contradicts this same module's own
  established "not configured means cannot evaluate, never a vacuous
  HEALTHY" philosophy (`evaluate_pipeline_health`'s "empty input is
  UNKNOWN, never assumed healthy" docstring;
  `evaluate_health_from_failure_rate`'s `sample_count=0` → `UNKNOWN`
  gate). Fixed to report `UNKNOWN` instead. Also discovered and fixed
  the underlying reason this branch was so easy to trigger in
  practice: `scripts/run_monitoring_sweep.py` never had a
  `--max-drawdown` CLI flag at all — `collect_account` was always
  called with `max_drawdown=None`. Added the flag, mirroring
  `run_paper_trading_cycle.py`'s own.
- **REGIME collector absent (real gap, fixed):**
  `MonitoringComponent.REGIME` was a declared enum member — and
  `evaluate_existence_health`'s own docstring already named "Prediction,
  Decision, Regime, Learning" as the four components it exists for —
  but no `collect_regime`/`compute_regime_metrics` ever existed. Added
  both, mirroring `collect_prediction`/`collect_decision` exactly
  (existence-based health, never a judgment on content), with
  `unknown_trend_rate`/`unknown_stress_rate` metrics mirroring
  `decision.agent.BaselineRuleDecisionAgent`'s own fail-closed
  treatment of exactly those two axes. Wired into
  `run_monitoring_sweep.py` (a real `regime_repository` was already
  being populated by `run_paper_trading_cycle.py`'s `run_cycle` call,
  just never read back by the sweep).
- **`--representative-security-id` hardcoded to `"AAPL"` in the daily
  production workflow (real bug, fixed):**
  `.github/workflows/paper_trading_cycle.yml`'s monitoring-sweep step
  hardcoded the literal string `"AAPL"`, disconnected from the
  `$UNIVERSE` env var that actually controls what the workflow trades —
  silently fragile against a future universe change or AAPL being
  removed from it. Fixed by resolving it dynamically from the SAME real
  universe via the already-tested `select_universe_shard.py`
  (`--shard-index 0 --shard-count 1000` deterministically isolates the
  alphabetically-first real symbol — today still `AAPL` for
  `RESEARCH_UNIVERSE`, but now derived, not hardcoded).
- **No human notification channel for CRITICAL alerts (not a new bug,
  already documented):** `monitoring.alerts`'s own module docstring
  already states explicitly that email/messenger providers are
  "explicitly deferred, matching the master plan's own '초기에는
  logging 중심으로 구현' phrasing" — a deliberate, disclosed
  early-phase scope decision from `PROJECT_MASTER_PLAN.md` itself, not
  an oversight.
- **OCI provisioning workflow: SSH ingress `0.0.0.0/0` and a
  private-key artifact upload (confirmed real, deliberately accepted
  trade-off, documented):** `provision_oci_colibri_runner.yml`'s
  security list allows SSH from anywhere. Verified this is a real,
  considered trade-off, not an oversight: the workflow runs unattended
  on a 15-minute schedule (the account owner's own capacity-retry
  request), so their own IP is not knowable in advance to restrict
  ingress to; authentication is SSH-key-only (a fresh ed25519 keypair
  per run, never a password) — a meaningfully smaller attack surface
  than an open password-auth port, though not equivalent to a
  CIDR-restricted one; and the instance is a research/non-production
  runner, not a trading system. The private key artifact already had
  `retention-days: 1` and an explicit "download once, then delete"
  instruction before this pass — already a conservative, minimized
  design, not force-fixed further. Added an explanatory comment at the
  ingress rule naming the trade-off and the operator's own manual
  hardening path (narrow the security list from the OCI console once
  their IP is known), rather than force a change that could lock the
  account owner out of their own unattended, scheduled provisioning
  workflow.

## Consequences

- A real Paper Trading account in a severe drawdown, monitored with the
  CLI's own default (no `--max-drawdown` configured), no longer shows a
  false HEALTHY status.
- The daily production monitoring sweep now also observes the REGIME
  layer — a real, previously-invisible gap in end-to-end pipeline
  coverage.
- The daily production workflow's monitoring step can no longer
  silently break if the traded universe changes or `AAPL` is removed
  from it.
- Two findings (no CRITICAL human channel, OCI SSH ingress/key
  artifact) were re-verified and found to already be correctly,
  deliberately documented/mitigated trade-offs — recorded here rather
  than force-fixed, per this session's established verification
  discipline.
- Regression tests added: 1 (ACCOUNT UNKNOWN-not-HEALTHY, both at the
  `evaluate_account_health` unit level and the full CLI level), 2
  (`compute_regime_metrics`), 2 (`collect_regime`), 1 (dynamic
  `--representative-security-id` resolution) — full suite (3746 tests)
  passes.
