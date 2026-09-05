# ADR-0082: GitHub Actions replaces the Oracle Cloud VM as the active scheduler host

**Status:** Accepted
**Session:** 36 (continued)

## Context

ADR-0081 chose an Oracle Cloud Always Free VM over GitHub Actions,
specifically because a persistent VM disk trivially solves the
DuckDB state-persistence problem that GitHub Actions' ephemeral
runners do not solve on their own. The account owner then found the
manual VM setup (account verification, instance provisioning, SSH,
OS administration) too much operational friction in practice and
asked to use GitHub Actions instead, now that the repo already lives
on GitHub.

This ADR does not reverse ADR-0081's technical analysis -- a real VM's
persistent disk genuinely is the structurally simpler fit. It records
that, given the actual operational cost the account owner is willing
to carry, GitHub Actions is the better choice for this project *once
its state-persistence gap is actually designed*, which this ADR does.

## Decision

Use `.github/workflows/paper_trading_cycle.yml`, a scheduled (`cron:
"0 22 * * 1-5"`, i.e. weekdays) GitHub Actions workflow, as the active
Paper Trading scheduler. It runs the same `scripts/
run_paper_trading_cycle.py --resume` invocation ADR-0075 already
documents, with `--max-sector-weight 0.25 --max-order-notional 1000`
(the ratified #5/#10 values, ADR-0080).

**State persistence design** (the gap ADR-0081/the prior conversation
left explicitly unresolved for this option): both DuckDB-backed
directories -- `--db-path` (market-data catalog) and `--paper-store`
(the paper trading ledger) -- are round-tripped as GitHub Actions
artifacts, never committed into git:
1. At the start of each run, a step queries `GET /repos/{owner}/{repo}/
   actions/artifacts` (via `gh api`, using the workflow's own
   `GITHUB_TOKEN`) for the most recent non-expired artifact by name
   and restores it, if one exists (first run: none exists, both
   directories start empty, matching what a fresh `--db-path`/
   `--paper-store` already means to both scripts).
2. Ingestion and the cycle script run as normal against the restored
   directories.
3. Both directories (plus the run's own report) are re-uploaded as new
   artifacts unconditionally (`if: always()`), so a mid-run failure
   still preserves whatever state was durably written before the
   failure, rather than losing it.

This deliberately avoids committing `*.duckdb`/`*.parquet` files into
git, which `.gitignore` already documents as a considered decision
(Phase 22 instruction section 26: "this repo holds schema, metadata,
checksums, ingestion code, config, and docs -- never actual vendor
data or a populated database file"). Artifacts are GitHub's own
storage, entirely outside git history, so that policy is unaffected.

**Idempotent re-ingestion**: each run re-invokes
`ingest_real_market_data.py` with the *same* fixed `--start` and
`--end="$(date -u +%F)"` against the restored (not empty) catalog,
rather than trying to compute "only the new day(s)". This is safe
because `DuckDBDataRepository.append_bars` already deduplicates by
`(security_id, timestamp, provenance.source, provenance.data_version)`
before writing (`src/storage/data_repository.py`, pre-existing,
unmodified) -- already-ingested bars are silently skipped, only
genuinely new bars get written. The real cost is re-fetching the whole
historical range from the provider over the network every run, which
is redundant but not incorrect; acceptable at this project's current
universe size (`RESEARCH_UNIVERSE`, documented free-tier limits,
ADR-0030), worth re-examining if the universe or history window grows
substantially.

## What this does NOT do

Does not retire ADR-0081 or its tooling -- `docs/operations/
ORACLE-CLOUD-DEPLOYMENT.md` and `scripts/deploy/oracle_vm_bootstrap.sh`
remain in the repo as a documented alternative, unused for now. Does
not change `run_paper_trading_cycle.py`, `ingest_real_market_data.py`,
or any risk-policy value -- only where the existing, unmodified
scripts run. Does not activate Live trading (still blocked by item B,
independent of this decision).

## Disclosed limitations (not hidden, not solved by this ADR)

- **Artifact retention**: GitHub's own hard cap is 90 days. If the
  workflow does not run successfully for longer than that (e.g.
  manually disabled for an extended period), the restore step would
  find nothing and the paper trading history would silently restart
  from empty rather than erroring loudly -- unlike an Oracle VM's
  persistent disk, which has no such expiry. Checking in on the
  workflow's run history periodically is a real, manual burden this
  design still carries.
- **60-day repo-inactivity auto-disable**: a GitHub platform behavior
  for scheduled workflows in general, unrelated to this specific
  design; any commit to the repo resets it.
- **Cron timing**: GitHub Actions schedules are not guaranteed to fire
  at the exact minute, and cron is UTC-only. ADR-0075's original
  "21:30" example never specified a timezone; this workflow uses
  22:00 UTC deliberately -- safely after the latest possible US market
  close (21:00 UTC in EST) year-round -- rather than asserting false
  precision about DST.
- **`MARKET_DATA_API_KEY`**: must be added by the account owner as a
  GitHub Actions repository secret (Settings -> Secrets and variables
  -> Actions). This session cannot do this on the account owner's
  behalf -- doing so would require them to paste a live credential
  into this conversation, which they should never do.

## Tests

`tests/deploy/test_paper_trading_cycle_workflow.py` (new) statically
parses the workflow YAML and asserts: the schedule/permissions/env are
present as designed; the ingestion and cycle-script invocations carry
the flags this ADR and ADR-0080 specify; the artifact restore/upload
steps reference the same two artifact names consistently; no secret
value is ever hardcoded (only `${{ secrets.MARKET_DATA_API_KEY }}`
references). The workflow's own execution against a real network and a
real API key cannot be verified from this session (matching
`ingest_real_market_data.py`'s own long-standing "never executed by
this repository's own automated test suite" caveat) -- the account
owner verifies it fires correctly once the secret is added and the
first scheduled (or manually dispatched) run completes.
