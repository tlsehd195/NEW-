# ADR-0002: Data Storage Technology for Phase 1

**Status:** Accepted
**Date:** 2026-08-24
**Deciders:** Claude Code (Phase 1 session), pending project owner review
**Related documents:** `PROJECT_MASTER_PLAN.md` §18, `docs/specifications/PHASE-1-data-infrastructure.md`

---

## Context

Phase 1 needs to choose a storage technology for the Raw/Clean/Derived
data layers (`PROJECT_MASTER_PLAN.md` §7, §18). The choice must serve
this and future phases: Backtesting (Phase 2), ML training (Phase 9),
Decision Replay, Trade Journal, and eventually Live Trading — without
requiring a rewrite later, per `PROJECT_MASTER_PLAN.md` §1.2 (complexity is the lowest priority, added only when needed).

Candidates evaluated, per the criteria required by the initialization
instruction (development convenience, analysis speed, data size,
transaction needs, reproducibility, backtest/ML pipeline fit, future
extensibility):

| Option | Dev convenience | Analytical (columnar scan) speed | Transactional writes | Fits time-series/backtest workload | Extensibility |
|---|---|---|---|---|---|
| SQLite | High (stdlib, zero setup) | Poor for large columnar scans | Good (ACID, single-writer) | Weak — row-store, slow for large OHLCV range scans | Limited — not built for analytical workloads |
| PostgreSQL | Medium (needs a running server) | Medium | Excellent (full ACID, concurrent writers) | Reasonable, but heavier than needed for a single-developer research phase | High, but operational overhead now is premature for Phase 1 |
| Raw Parquet files | High (no server) | Excellent (columnar, compresses well) | None (no native transactional guarantees) | Excellent for backtest/ML bulk reads | Good, but no query engine on its own |
| DuckDB | High (embedded, zero setup, single file or in-memory) | Excellent (columnar OLAP engine) | Adequate for single-process, append-heavy workloads | Excellent — designed for exactly this analytical/time-series access pattern, and reads Parquet natively | High — SQL interface, easy to later point at partitioned Parquet or migrate to Postgres if concurrent multi-writer access is ever needed |
| Object storage (e.g. S3-style) | Low for local dev (needs infra or emulation) | Good if paired with Parquet | None natively | Good for scale, premature now | High, but premature |

## Decision

**Phase 1 adopts DuckDB as the query/storage engine, with Parquet as the
on-disk file format for the Raw and Clean layers**, accessed exclusively
through the `DataRepository` interface (`PROJECT_MASTER_PLAN.md` §19;
Phase 1 spec §12). Concretely:

- Raw layer: append-only Parquet files (or an append-only DuckDB table
  backed by Parquet), partitioned by ingestion run / date, never
  rewritten in place (Phase 1 spec §17).
- Clean layer: DuckDB tables (or Parquet queried through DuckDB) keyed
  by `security_id`, versioned via `data_version`.
- Derived layer: reserved, not populated in Phase 1.
- **Phase 1's actual reference implementation is in-memory
  (`InMemoryDataRepository`, pure Python data structures)**, not yet
  wired to DuckDB/Parquet. This ADR fixes the *target* storage
  technology and the *interface contract* (`DataRepository`) so that a
  DuckDB/Parquet-backed implementation can be swapped in later without
  changing any consumer code — but building that concrete backend is
  deferred to Phase 2 (Backtesting) or an explicit Phase 1 follow-up,
  once real data volume/query patterns are known. Building it now
  against only mock data would be premature optimization
  (`PROJECT_MASTER_PLAN.md` §1.3 — "복잡성을 위해 복잡한 시스템을 만들지
  않는다").

## Reasoning

- DuckDB matches the actual workload shape of this project: mostly
  append-heavy time-series ingestion, followed by heavy analytical
  range/columnar scans (backtests iterating over date ranges across many
  securities, feature computation over lookback windows) — exactly
  DuckDB's design target, unlike SQLite (row-store, weak for this) or
  bare Postgres (built for OLTP concurrency Phase 1 does not need yet).
- Zero operational overhead: no server process to run/manage in a
  single-developer research phase, which keeps Phase 0/1's "Foundation
  first, minimal viable system" principle intact
  (`PROJECT_MASTER_PLAN.md` §21, §20).
- Parquet as the underlying file format gives us: (a) natural
  immutability (a Parquet file is written once per ingestion batch,
  matching Raw-layer append-only semantics), (b) portability if the
  project later needs a different query engine, and (c) efficient
  storage for years of daily OHLCV data.
- DuckDB can query Parquet directly and also supports an embedded
  transactional table mode, so both the Raw (immutable, file-based) and
  Clean (versioned, queryable) layers can be served by one engine
  without introducing two separate storage technologies in Phase 1.
- Migration path if concurrency needs grow (e.g., a future multi-process
  live trading system with concurrent readers/writers): DuckDB's SQL
  surface is close enough to PostgreSQL that a future migration is a
  bounded, well-understood effort — not a full rewrite of the data
  model or the `DataRepository` interface.

## Alternatives Considered

- **SQLite**: Rejected as the primary analytical store — the OHLCV /
  backtest access pattern (wide date-range scans across many symbols) is
  exactly what row-oriented SQLite is weak at. It remains a reasonable
  choice for small transactional metadata later (e.g., ingestion
  checkpoints) if a need arises, but is not adopted now to avoid running
  two storage technologies without a concrete need.
- **PostgreSQL**: Rejected for Phase 1 — the operational cost (running a
  server, connection management, migrations tooling) is not justified
  yet by any concurrency or multi-user requirement. Revisit if/when Live
  Trading (Phase 16) needs concurrent readers/writers beyond what an
  embedded engine comfortably serves.
- **Raw Parquet without DuckDB**: Rejected alone — Parquet without a
  query engine pushes all filtering/joining logic into application code;
  DuckDB gives that for free while still using Parquet as the file
  format.
- **Object storage (S3-compatible)**: Rejected for Phase 1 — this is a
  local/single-environment research phase; introducing cloud storage
  now is unjustified complexity. Revisit for Phase 15/16 operational
  hardening if the deployment environment requires it.

## Consequences

### Positive

- Analytical workloads (backtests, feature computation) will be fast
  against a DuckDB/Parquet backend once implemented.
- No server to operate; storage is just files, which is easy to reason
  about, back up, and reproduce (supports `PROJECT_MASTER_PLAN.md` §1.3's
  own Reproducibility question).
- Clear migration path to PostgreSQL later if concurrency demands grow.

### Negative / Trade-offs

- DuckDB's single-process embedded model is not natively suited to
  concurrent multi-writer access; if Phase 16 (Live Trading) needs
  concurrent writers (e.g., simultaneous ingestion + live decision
  reads), this must be re-evaluated — flagged here as a known future
  risk, not solved by this ADR.
- Choosing DuckDB now without a concrete DuckDB-backed implementation
  means Phase 1 ships with the in-memory reference implementation only;
  the "real" storage backend remains unimplemented until a follow-up
  task. This is an accepted, explicit scope boundary (Phase 1 spec §1.2),
  not an oversight.

## Status of Implementation at Time of This ADR

Only `InMemoryDataRepository` exists (Phase 1 reference implementation,
used by the test suite). No DuckDB/Parquet code has been written yet.
