# ADR-0150: Durable, git-committed JSON backup of the Paper Trading store

**Status:** Accepted
**Date:** 2026-09-17
**Deciders:** Claude Code (session continued), account owner (chose the
backup mechanism directly, see Decision)
**Related documents:** `.github/workflows/paper_trading_cycle.yml`
(ADR-0082's own artifact round-trip design, which this ADR adds to
rather than replaces), `scripts/export_paper_store_backup.py`

---

## Context

The "Paper Trading 원리와 기능 성능 평가" (100-point evaluation) report
named the paper-trading-store's persistence as entirely dependent on a
GitHub Actions artifact with a 90-day retention window (ADR-0082): if
scheduled runs fail for 90+ consecutive days, the artifact expires and
the entire order/fill/trade/decision history is gone with nothing to
restore from. Recommendation #6 in that report: "장부 저장소를 artifact
→ 영속 백엔드(Git 저장/외부 DB 내보내기) 이중화."

Two real options exist: an external durable database (requires the
account owner's own credentials/infrastructure, which this session
cannot provision) or a git-committed backup (fully within this
session's own reach, no new account needed). Asked directly, the
account owner chose the git-committed option.

## Decision

New script `scripts/export_paper_store_backup.py`: opens a
`--paper-store` DuckDB catalog read-only, introspects its own table
list (`information_schema.tables`) rather than hardcoding repository
classes (so a future new table is backed up automatically), and dumps
every table's full current contents to one JSON file per table at
`--out-dir`. Each run OVERWRITES the previous snapshot — never
accumulates one folder per day — so the latest commit is always a
complete, standalone restore point, and a no-op run (nothing changed)
produces no diff to commit.

New step in `.github/workflows/paper_trading_cycle.yml`, "Export and
commit Paper Trading store backup," runs this script after the daily
cycle and `git commit`/`git push`es the result to
`backups/paper_trading_store/` on the SAME branch (`main`) — chosen
deliberately outside `data/` (which `.gitignore` excludes wholesale,
per this repo's own "never commit actual data content" policy for
vendor market data) since this is a different kind of content: a
derived backup of this project's OWN produced records, not raw vendor
data, and the account owner explicitly asked for it to be committed.
`permissions.contents` raised from `read` to `write` for this one
step's sake — the workflow's only write access, used only to push this
one directory.

`if: always()` on the export step, matching the two artifact-upload
steps immediately above it — even a failed cycle run leaves whatever
state existed before it worth backing up.

## Consequences

### Positive

- The paper trading ledger now has a durable, expiry-free backup that
  survives past any number of consecutive artifact-retention-window
  failures, restorable from git history alone.
- Generic table introspection means this backup automatically covers
  every table the store ever gains (Trade Journal, performance
  reports, decisions, etc.) without this script needing per-table
  updates.

### Negative / Trade-offs

- A daily commit to `main` from this workflow, whenever the ledger
  actually changed that day — a real, ongoing addition to this
  branch's commit history, accepted as the cost of the durability
  gained (and a no-op day commits nothing, so idle periods add
  nothing).
- This backup is NOT restore-automation — restoring from it after a
  real artifact-expiry incident would be a manual reconstruction
  (re-inserting the JSON rows into a fresh DuckDB catalog), not a
  one-command `--resume`. Building that restore path is left for if
  and when it is actually needed, rather than built speculatively now.
- `contents: write` is a real permission elevation for this scheduled
  workflow, scoped to this one step's `git push` — disclosed here
  rather than silently granted.

## Tests

`tests/scripts/test_export_paper_store_backup.py` (7 tests): every
populated table gets a JSON file with the real row count, a datetime
column round-trips as a real ISO-8601 string (never a Python `repr()`
or an epoch integer), re-running overwrites rather than accumulates, a
freshly-initialized store with zero rows backs up without crashing,
the CLI returns 0 and prints a summary, a missing `--paper-store`
fails loudly.

`tests/deploy/test_paper_trading_cycle_workflow.py::
test_workflow_grants_contents_write_for_the_backup_commit_step`
(replaces the prior `read`-only assertion): confirms the elevation is
real and that the step actually using it (a real `git push`) exists.

Full suite re-run clean: 3175 passed.

## Status of Implementation at Time of This ADR

Code, tests, and documentation complete and committed. Not yet
exercised against a real scheduled run (this workflow's own
`workflow_dispatch` re-run after this PR merges is the first real test,
matching every other workflow change in this repo's own precedent).
