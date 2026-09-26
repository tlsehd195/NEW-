# ADR-0211: Additive DuckDB schema migration for existing on-disk stores

**Status:** Accepted
**Date:** 2026-09-26
**Deciders:** account owner ("너가 추천하는 방법으로 진행"), Claude Code session

**Related documents:** `docs/decisions/ADR-0203` (added the six
`provenance_*` columns to `security_master`/`universe_membership`),
`docs/decisions/ADR-0010` (DuckDB storage layout, idempotent DDL).

## Context

`paper_trading_cycle.yml` run 36204894921 (2026-09-26) failed in
"Ingest latest market data" before any provider request:

```
_duckdb.BinderException: Binder Error: Table "security_master" does not
have a column with name "provenance_source"
```

The workflow restores the previous run's DuckDB store and reopens it.
`src/storage/schema.py` only runs `CREATE TABLE IF NOT EXISTS`, which
never alters a table that already exists, so a store created before
ADR-0203 kept its old `security_master` shape, and
`DuckDBDataRepository.add_security` (which now names the provenance
columns) failed on every run. The API-key secrets were confirmed present
in the same log (`MARKET_DATA_API_KEY`/`TWELVEDATA_API_KEY`/
`ALPHAVANTAGE_API_KEY` all injected); they were not the cause.

## Decision

`init_schema` now follows the DDL with an additive migration
(`_add_missing_columns`):

- The expected columns per table are read from a scratch in-memory
  DuckDB built from the same `DDL_STATEMENTS` (cached once per process),
  so the DDL stays the single source of truth; no hand-maintained
  migration list.
- For each existing table, a missing **nullable** column is added with
  `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`. Existing rows read `NULL`,
  the same honest "unknown" a new row omitting it would get (ADR-0203
  already treats `provenance=None` as the disclosed default).
- A missing **NOT NULL** column raises `RuntimeError` instead: there is
  no honest backfill value, so the store must be migrated explicitly.

Tests: `tests/storage/test_schema_migration.py` builds a store with the
exact pre-ADR-0203 tables, reproduces the Binder Error without the fix,
and checks writes, idempotent reopen, and the NOT NULL refusal.

## Consequences

- Future nullable column additions no longer break restored stores.
- Column type changes, renames and dropped columns are still not
  migrated; they need an explicit migration when they happen.

## Other findings from the same investigation (not changed here)

- 2026-09-25 runs failed for other reasons: run 36077212315 on the
  corporate-action FATAL that PR #132 already removed; run 36126208497
  on `PARTIAL_SUCCESS` (AVB failed on every provider after Tiingo's
  48-request hourly cap was exhausted).
- Every recent run reports 87 `ingestion_precedes_availability` ERRORs
  (one per symbol), including the successful 2026-09-24 run. They do not
  gate the exit code, and the root cause was not pinned down here
  because the market-data catalog artifact could not be downloaded from
  this session.
