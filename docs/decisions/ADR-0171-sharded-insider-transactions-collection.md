# ADR-0171: Shard the full-universe SEC Form 4 insider-transaction collection across parallel GitHub Actions jobs

**Status:** Accepted
**Date:** 2026-09-19
**Deciders:** Claude Code (session continued), account owner (asked
to pick up an abandoned Session 37 Colab collection via GitHub
Actions, then confirmed a sharded/parallel design after asking whether
parallelism costs more -- it does not, for GitHub Actions compute; see
Consequences)
**Related documents:** `docs/decisions/ADR-0086-insider-trading-form4-pipeline.md`,
`docs/decisions/ADR-0132-insider-transactions-filing-list-switched-to-data-sec-gov.md`,
`docs/PROJECT_STATUS.md`'s Session 37 entry ("이어서 나머지 78종목... 재수집
재개" with no later completion ever recorded)

## Context

Session 37's own Google Colab collection of SEC Form 4 insider
transactions for 87 symbols was resumed after fixing a real overnight
failure (ADR-0132) but never confirmed complete in
`docs/PROJECT_STATUS.md` -- the account owner asked directly whether
this session had simply never considered running it via GitHub
Actions instead (this session's own `paper_trading_cycle.yml` already
calls several other real external APIs), and the honest answer was
yes: a real, usable pattern (`workflow_dispatch` reaching a host this
session's own egress cannot) had already been established earlier
this same session (`repair_ingestion_time_inversions.yml`,
`verify_alpaca_paper_broker.yml`) but not yet applied here.

A real single-symbol verification (`.github/workflows/
verify_insider_transactions_ingestion.yml`, JPM) confirmed the
pipeline works end to end, but also surfaced two real observability
gaps this session fixed along the way (both merged before this ADR:
progress logging for the filing-list pagination loop, then for the
per-filing detail-fetch loop) -- and, once visible, a real timing
fact: JPM's own 1863 real Form 4 filings took **~2 hours** end to end
against a single sequential job. JPM is an extreme outlier (one of the
most prolific SEC filers that exists), but even a handful of similarly
large symbols (AAPL, MSFT, AMZN, GOOGL, etc. are all in
`RESEARCH_UNIVERSE`) running sequentially could push a full 87-symbol
collection past what is practical to babysit in one job.

## Decision

**Shard the universe across 10 parallel `workflow_dispatch` matrix
jobs**, each handling roughly 8-9 symbols (`scripts/
select_universe_shard.py`, `sorted(universe)[shard_index::shard_count]`
-- deterministic, balanced within one symbol, order-independent).

Each shard job writes to its **own isolated `--db-path`**
(`./data/insider_shard_<N>`), never a shared one -- `StorageEngine`'s
own docstring already establishes that DuckDB allows only one
read/write connection to a given file at a time, and
`docs/PROJECT_STATUS.md`'s own Session 37 history already flagged
"여러 코랩 동시 실행은 DuckDB 동시쓰기 충돌... 위험 때문에 신중히
접근하기로(시도 안 함)" as a real concern for exactly this class of
parallelism. `fail-fast: false` on the matrix so one shard's failure
(e.g. a single symbol's CIK not resolving) does not cancel the other
nine.

A separate, sequential `merge` job (`needs: ingest`, `if: always()`)
downloads every shard's catalog artifact and combines them with new
`scripts/merge_insider_transaction_catalogs.py`. `insider_transactions`
is a native DuckDB table (unlike `price_bars`, which is Parquet-file-
based and can be combined by copying files into one directory) -- the
merge script uses DuckDB's own `ATTACH ... (READ_ONLY)` per shard, then
`INSERT ... SELECT ... ON CONFLICT (provenance_source_record_id) DO
NOTHING` -- the identical idempotent-insert natural key
`DuckDBInsiderRepository.add_insider_transaction` already uses for a
single writer, so re-running the merge (or feeding it overlapping
shards) never duplicates a row. The combined catalog is uploaded as a
single `insider-transactions-catalog` artifact.

`shard_count: 10` is fixed in the workflow, not a `workflow_dispatch`
input -- balances real wall-clock speedup against being a considerate,
identified caller of a real government service (this project's own
`--user-agent` carries a real, reachable contact per SEC's fair-access
policy, so 10 simultaneous identified callers is a deliberate,
moderate choice, not maximum parallelism for its own sake).

## Consequences

### Positive

- Real wall-clock time for the full 87-symbol collection drops
  roughly 10x versus one sequential job, without increasing total
  GitHub Actions compute-minutes consumed (confirmed with the account
  owner: parallel jobs split the SAME total work across concurrent
  runners -- billed minutes are the same either way, only elapsed time
  changes).
- Real, executable test coverage for both new scripts (`select_universe_shard.py`
  is pure symbol-list arithmetic; `merge_insider_transaction_catalogs.py`
  is tested against real, seeded local DuckDB catalogs, no network
  mocking needed for either).
- The abandoned Session 37 Colab task finally gets a real, repeatable,
  attributable completion path instead of depending on a manually
  managed local/Colab session with no automated resumption.

### Negative / Trade-offs

- Checking on 10 parallel jobs individually (rather than one
  sequential job) could itself cost more of this session's own review
  overhead (reading each job's logs) if done naively -- mitigated by
  checking the whole matrix's overall completion once via a single
  `list_workflow_jobs` call and only pulling detailed logs for shards
  that actually failed, not every shard unconditionally.
- The merge step is a real, additional sequential stage after the
  matrix completes -- if it fails, no combined catalog is produced
  even though every shard's own catalog artifact still exists
  individually and is not lost (each shard's `if: always()` upload
  happens regardless of the merge job's own outcome).
- `shard_count: 10` is a judgment call, not derived from a load test
  against SEC's real infrastructure -- a future run that finds this
  still too slow (or too aggressive) has a single, obvious constant to
  revisit.

## Tests

`tests/scripts/test_select_universe_shard.py` (8 tests): every symbol
covered across all shards exactly once, deterministic regardless of
input order, balanced shard sizes, invalid `shard_count`/`shard_index`
rejected, `main()`'s full ten-shard-of-`RESEARCH_UNIVERSE` output
matches the real universe with no overlap. `tests/scripts/
test_merge_insider_transaction_catalogs.py` (4 tests): merges disjoint
shards, idempotent on a second run, a missing shard catalog is skipped
not fatal, merging into an already-populated target preserves existing
rows -- all against real, seeded local DuckDB catalogs. `tests/deploy/
test_ingest_insider_transactions_full_workflow.py` (9 tests): workflow
structure (matrix shard list/`fail-fast`, per-shard isolated
`--db-path`, artifact upload safety, merge job dependency/`if: always()`,
download pattern, real script invocation). Full suite re-run: see
`docs/PROJECT_STATUS.md`'s session log for the exact count.

## Status of Implementation at Time of This ADR

Code, tests, and workflow complete and merged. The real full-universe
`workflow_dispatch` run itself (against real SEC EDGAR endpoints,
expected to take a meaningful fraction of an hour given JPM's own
~2-hour outlier result and 10-way parallelism) is the next, separate
step this ADR does not itself claim to have executed -- see this
session's own live reporting to the account owner for that real
outcome once triggered.
