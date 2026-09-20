# ADR-0183: Install the Monitoring package on the factory floor (audit Batch F)

**Status:** Accepted
**Date:** 2026-09-20
**Deciders:** Claude Code (session continued), account owner (asked to
process every remaining P2/P3 finding from the independent audit
report, in batches; account owner explicitly chose "지금 전체 구축" --
build the full DuckDB repository layer + sweep script + workflow step
now, not a scoped-down version or a deferral -- when asked how to scope
this batch)

## Context

The independent audit's Step 10 (`src/monitoring/`) found: "모니터링/
경보 코드 자체는 결정론적, fail-closed, PIT-클린, 잘 테스트됨 -- 실험실
계기가 공장에 설치된 적이 없는 것." Confirmed real, directly:
`monitoring.collectors`/`monitoring.pipeline`/`monitoring.health`/
`monitoring.alerts`/`monitoring.drift` are fully built and covered by
their own tests (Phase 14), and both the `monitoring_events`/
`component_health_states`/`drift_results`/`alerts` DuckDB tables
(`storage.schema`, lines 635-680) AND their real repository
implementations (`storage.monitoring_repository`'s four `DuckDB*`
classes) already existed, also since Phase 14 -- correcting an earlier,
inaccurate draft of this ADR and of this session's own work-in-progress
docstrings, which claimed the repository layer itself was missing. The
real, confirmed gap is narrower and exactly matches the audit's own
"실험실 계기가 공장에 설치된 적이 없는 것" framing: a repo-wide grep
found zero production callers of any collector function, and zero
callers of any of the four `DuckDB*` Monitoring repositories, outside
their own test files. Every real prediction/decision/sizing/risk/
account observation `scripts/run_paper_trading_cycle.py` has ever
produced was therefore computed by nothing and persisted by nothing --
the instrument existed and worked, but nothing on the factory floor was
ever plugged into it.

While tracing this gap, a real, independent bug was also found in the
already-existing repository: `DuckDBComponentHealthRepository`/
`DuckDBDriftResultRepository`'s `get_latest`/`get_history`/`list_all`
ordered by insertion `seq` alone, not by the record's own `as_of_time`.
Correct only when every record happens to be inserted in chronological
order -- a sweep that processes several days in one run (as the new
script below does) can insert out of order, so `get_latest` could
silently return a stale record rather than the chronologically latest
one.

## Decision

`storage/monitoring_repository.py`'s existing four DuckDB repository
classes (`DuckDBMonitoringEventRepository`, `DuckDBComponentHealth
Repository`, `DuckDBDriftResultRepository`, `DuckDBAlertRepository`)
gained a real ordering fix: `get_latest`/`get_history`/`list_all` on
the health and drift repositories now order by `as_of_time, seq`
instead of `seq` alone, so a record inserted out of chronological order
no longer masks a chronologically later one. No schema or serialization
change was needed -- both already existed and already worked correctly.

A new script, `scripts/run_monitoring_sweep.py`, is the real caller
these repositories never had: given an already-populated `--paper-
store` (the same one `run_paper_trading_cycle.py` already produces
daily) and a `[--start, --end]` window, it reads real, already-
persisted prediction/decision/sizing/risk records plus a real
reconstructed equity history (`equity_history_from_risk_repository`,
the same function `--resume` already uses for the identical purpose per
ADR-0136), runs them through the real `monitoring.collectors`/
`monitoring.pipeline`, and persists every resulting event/health/alert
via the four existing repositories. It seeds its own id counters from
whatever the store already has, matching `run_paper_trading_cycle.py`'s
own `_next_starting_id`
convention exactly, so repeated runs never collide.

`paper_trading_cycle.yml` gained a new "Run monitoring sweep (last 7
days)" step (`if: always()`, `continue-on-error: true`, matching the
tearsheet step's own established philosophy immediately below it) that
invokes this script over the trailing 7 real days, followed by an
"Upload monitoring sweep report" step (`actions/upload-artifact@v4`,
90-day retention, `if-no-files-found: ignore`). A 7-day window was
chosen deliberately over the full `$START_DATE`-to-today range: a
health/failure-rate signal diluted by years of past history would
barely move day to day, the same "wasteful, noisy" full-history-rescan
problem ADR-0144 already identified and rejected for data quality.

### Scope, deliberately bounded and disclosed, not silently narrowed

The sweep covers `prediction`/`decision`/`sizing`/`risk`/`account` --
the five components with real, already-populated repositories in
`--paper-store` today. It does NOT cover, and the script's own module
docstring says so explicitly:
- `data_quality`: needs real `PriceBar` history from the separate
  market-data catalog (`--db-path`, not `--paper-store`) -- a real,
  addressable gap left for a follow-up that also accepts a `--db-path`
  argument.
- `broker`: needs `BrokerRequestRecord`/`BrokerResponseRecord`, the
  generic `broker.pipeline.submit_validated_order` audit trail (Phase
  13) -- `PaperTradingSession.submit()` calls `PaperBrokerAdapter.
  submit_order` directly and never goes through that pipeline, so no
  real data for this component exists in `--paper-store` today.
- `ai_gateway`/`learning`/`model_evolution`: `ai_gateway` has zero real
  production callers (independently confirmed elsewhere this session);
  `learning`/`model_evolution` run on a separate weekly cron
  (`learning_cycle.yml`) against a different repository shape.
- Drift detection (`monitoring.drift`): needs a real baseline-vs-current
  comparison window this script does not yet construct -- `drift_
  results` and drift-derived alerts are always empty this pass, never
  fabricated as "no drift detected."

## Consequences

### Positive
- Closes the exact "lab instrument never installed on the factory
  floor" gap the audit named: real health/failure-rate/alert data now
  exists in durable storage for the five components with real inputs
  today, queryable by any future dashboard or on-call tooling.
- Verified end-to-end against a REAL paper store produced by actually
  running `run_paper_trading_cycle.py`, not synthetic fixtures --
  confirms the sweep script's assumptions about `--paper-store`'s real
  shape hold.
- Zero risk to the core trading cycle: the new workflow step is
  `continue-on-error`, and a fresh store with no records in the window
  produces an honest report rather than crashing.

### Negative / Trade-offs
- `data_quality`/`broker`/`ai_gateway`/`learning`/`model_evolution`/
  drift detection remain unwired, for the concrete reasons stated
  above, not silently -- each is a distinct, addressable follow-up.
- The workflow step is best-effort (`continue-on-error: true`): a
  failure in the sweep is visible only via the uploaded report/job log,
  never blocks or alerts on its own. No paging/dashboard consumes the
  persisted alerts yet -- this ADR installs the instrument and turns it
  on, it does not build the alarm panel.
- `equity_history_from_risk_repository` requires a
  `--representative-security-id` the caller must already know has real
  risk assessments in the store; an empty/wrong id silently produces an
  empty equity history rather than erroring (existing behavior of that
  function, unchanged by this ADR).

## Tests

`tests/storage/test_monitoring_repository.py`: all of Phase 14/17's
existing coverage kept unchanged (round-trip including a nested-
datetime metric, idempotent double-record, the ACCOUNT-component
`collect_account` integration test, drift result history scoped by
metric name, restart survival), plus a new
`TestLatestIsOrderedByAsOfTimeNotInsertionOrder` class (2 tests) that
records component-health and drift results out of chronological order
and confirms `get_latest` still returns the record with the latest
`as_of_time` -- the real regression guard for this ADR's ordering fix.
Verified as a real regression guard by reverting the `ORDER BY` change
in `storage/monitoring_repository.py` and confirming both new tests
fail first (each returned the last-inserted, not the chronologically
latest, record) before restoring the fix.

`tests/scripts/test_run_monitoring_sweep.py` (4 tests, new): syntactic
validity; a real end-to-end sweep against a paper store populated by
actually running `run_paper_trading_cycle.py` persists all 5 events, 6
component healths (5 + pipeline), and writes a correct report; a
second identical run does not crash and adds a fresh set of rows rather
than duplicating or corrupting the first run's; a healthy short run
raises no alerts.

`tests/deploy/test_paper_trading_cycle_workflow.py`'s new
`test_monitoring_sweep_step_runs_and_never_fails_the_job`: confirms the
new step exists, runs unconditionally with `continue-on-error`, and its
report-upload step is present with `if-no-files-found: ignore`.

Targeted run (`test_paper_trading_cycle_workflow.py` +
`test_monitoring_repository.py` + `test_run_monitoring_sweep.py`): 35
passed. Full suite: 3507 passed, 0 failed (baseline 3504 + net new
tests this batch).

## Status of Implementation at Time of This ADR

Code and tests complete. This is Batch F of a larger, explicitly-
requested pass through every remaining P2/P3 finding in the independent
audit report; Batch G (workflow hygiene: concurrency groups + timeouts
across all 10 GitHub Actions workflows) is next.
