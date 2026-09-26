# ADR-0208: healthchecks.io dead-man's-switch ping + FRED macro-data adapter

**Status:** Accepted
**Date:** 2026-09-26
**Deciders:** Claude Code session, account owner (explicit confirmation that the `HEALTHCHECKS_PING_URL`/`FRED_API_KEY` GitHub secrets were registered)

**Related documents:** `CLAUDE.md` "사용자 액션 대기 항목" ("10차 권고
리포트 기반 추가 항목"), `docs/decisions/ADR-0151` (original "adopt now,
wire in later" precedent this ADR follows for FRED), `docs/decisions/
ADR-0206` (the identical pattern for `GeminiProviderAdapter`: a real,
tested, network-capable adapter with zero production call sites),
`src/counterfactual/counterfactual.py` (the existing, disclosed
"no risk-free-rate data source" gap this ADR does NOT close).

## Context

Two independent, unrelated small items from the same "10th advisory
report" batch, bundled into one PR per this project's own token/cost-
saving rule ("작은 항목들은 가능하면 하나의 ADR/PR로 묶어서 처리한다").
Both became actionable only after the account owner registered the
relevant external account/key and confirmed it (see the pending-items
history in CLAUDE.md).

## Decision 1: healthchecks.io dead-man's-switch ping for `paper_trading_cycle.yml`

A GitHub Actions `schedule:` trigger can silently stop firing (repo
inactivity auto-disable, a GitHub-side scheduling incident, an accidental
future edit to the cron/branch) with no job ever running to report a
failure -- the existing Discord-on-completion notification
(`send_discord_notification.py`) cannot catch this class of failure,
because it only runs as part of a job that would have to exist first.

`paper_trading_cycle.yml` now pings a healthchecks.io check (URL kept in
the `HEALTHCHECKS_PING_URL` repository secret, resolved to a workflow-
level `env:` for the same `secrets`-context-not-valid-in-step-`if:`
reason `DISCORD_WEBHOOK_URL` already documents) at two points:

- **Start**: the very first step of `run-cycle`, before checkout --
  `curl .../start`, so a run that hangs or crashes early still leaves a
  "started" signal.
- **Finish**: the last step of `commit-backup` (`needs: run-cycle`,
  `if: always()`, so it is the true last step of every scheduled run
  regardless of outcome) -- pings the bare check URL on `needs.run-
  cycle.result == 'success'`, `/fail` otherwise.

Both ping steps are `if: ... && env.HEALTHCHECKS_PING_URL != ''` and
`continue-on-error: true` -- absent the secret, or on a healthchecks.io-
side network hiccup, this never blocks or fails the real trading cycle
it only observes. The healthchecks.io check itself (schedule `0 22 * *
1-5` matching this workflow's own cron exactly, in UTC; 3-hour grace
time to comfortably cover this workflow's worst-case ~75-minute runtime
plus GitHub's own scheduled-workflow start jitter) and its Discord
alert-channel integration are configured entirely on healthchecks.io's
own site by the account owner -- nothing about that lives in this repo.

## Decision 2: `FredMacroProvider` -- a real, tested FRED adapter, with wiring explicitly deferred

`src/data_infra/providers/fred{,_auth,_config,_transport}.py` (new
files, mirroring `tiingo{,_auth,_config,_transport}.py`'s exact config/
auth/transport split) add a real (not mock), tested adapter for FRED
(Federal Reserve Economic Data) -- the standard public source for a US
risk-free rate (e.g. `DGS3MO`) or other macro series.

**What this explicitly does NOT do**: change any of this project's
existing `risk_free_rate: float = 0.0` defaults
(`backtest.metrics.sharpe_ratio`/`sortino_ratio`, `backtest.engine.
BacktestConfig`, `broker.paper.performance.PaperPerformanceConfig`,
`counterfactual.counterfactual`/`evolution.counterfactual`). Those are
an existing, disclosed limitation
(`src/counterfactual/counterfactual.py`: "This system has no risk-free-
rate data source anywhere"), not a bug this ADR silently fixes. Actually
wiring a real FRED-sourced rate into those call sites would change every
future Sharpe/Sortino/DSR/counterfactual-cash-baseline number this
project reports from that point on -- exactly the kind of consequential,
cross-cutting change this project's own discipline (ADR-0151's "adopt
now, wire in later," the Grounding Gate wiring deferral in CLAUDE.md)
requires deciding deliberately, not as a side effect of adding a data
source. `FredMacroProvider` is therefore adopted now (real, tested,
verifiable) and left unwired, following ADR-0151's own precedent exactly
-- re-opened only when a specific decision is made to replace one of the
`0.0` defaults above, at which point the two open questions are: (1)
which series is the actual risk-free proxy (`DGS3MO` vs. a different
maturity/series), and (2) how a fetch failure/missing-data day
(`FredObservation.value is None`) should degrade -- fall back to
`0.0`, to the last known value, or fail the caller.

Not a `data_infra.provider.DataProvider` -- that Protocol's shape
(per-`security_id` `PriceBar` rows from `fetch`/`validate`/`normalize`)
is OHLCV-specific and does not fit a macro series keyed by `series_id`
alone. `FredMacroProvider.fetch_series(series_id, start, end) ->
list[FredObservation]` is its own, smaller contract instead.

**Evidence tier**: built from FRED's own published API documentation
(`series_observations`/`errors` pages) -- the same "Tier 2, documentation
only" level this project's other market-data providers were originally
built against. `scripts/verify_fred_adapter.py` +
`.github/workflows/verify_fred_adapter.yml` (`workflow_dispatch` only,
mirroring `verify_gemini_adapter.yml`) is the real, account-owner-run
verification step against the real API (fetches `DGS3MO` over a 14-day
window) that upgrades this to Tier 1 evidence once run -- update
`fred_transport.py`'s own docstring if it reveals either documented fact
(the `"."` missing-value marker, or HTTP 400 -- not 401/403 -- for a bad/
unregistered `api_key`) to be wrong.

## Testing

- `tests/data_infra/test_fred_auth.py`, `test_fred_transport.py` (mocked
  `urllib.request.urlopen`, real network never reached, mirroring
  `test_tiingo_transport.py`'s own discipline), `test_fred_provider.py`
  (date/value parsing, the `"."` missing-value convention, credential
  isolation).
- `tests/data_infra/test_tiingo_auth.py`'s repo-scoped `os.environ`
  isolation scan, and `tests/broker/live/
  test_production_safety_cross_cutting.py`'s repo-wide equivalent, both
  updated to allow `fred_auth.py` as the one file permitted to touch
  `os.environ` for this integration.
- `tests/deploy/test_paper_trading_cycle_workflow.py` gained a new test
  asserting both ping steps exist, are correctly gated/positioned, and
  never hardcode the ping URL.
- Full suite run before merge (branch-merge rule).
