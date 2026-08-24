# ADR-0010: Persistent Storage Backend Implementation (DuckDB + Parquet)

**Status:** Accepted
**Date:** 2026-08-24
**Deciders:** Claude Code (Phase 4 session), pending project owner review
**Related documents:** `PROJECT_MASTER_PLAN.md` §7, §18, ADR-0002 (data
storage technology choice), ADR-0009 (Trade Journal data model),
`docs/specifications/PHASE-4-baseline-models-and-storage.md`

---

## Context

ADR-0002 (Phase 1) chose DuckDB + Parquet as the *target* storage
technology but deliberately shipped only `InMemoryDataRepository`,
deferring the concrete backend until real data volume/query patterns were
known — building it against only mock data would have been premature
optimization. Phase 2 and Phase 3 made the identical, explicitly-stated
scoping decision for `ExperimentTracker` and `TradeJournalRepository`
respectively: in-process/in-memory only, real persistence deferred.

Phase 4's mandate is to build that deferred backend now, because the
project is about to need it for real: long-horizon Paper Trading (Phase
15) will accumulate months to years of decisions, trades, and market data
that must survive process restarts. This ADR records the concrete
backend design.

## Decision

### 1. One DuckDB catalog file; Parquet only for high-volume time series

A single on-disk DuckDB file (`<root>/catalog.duckdb`) holds every
relational/metadata table: `security_master`, `corporate_actions`,
`benchmark_points`, `universe_membership`, `decisions`, `trades`,
`post_trade_analyses`, `counterfactuals`, `corrections`, `experiments`,
`experience_records`, plus a `raw_ingestion_batches` audit manifest.
Only per-security OHLCV bars (Raw and Clean market data — the one dataset
whose volume scales with `securities × trading days` and can plausibly
reach millions of rows over years of paper trading) live outside DuckDB
tables, as append-only Parquet files under `<root>/parquet/price_bars/`
(Clean) and `<root>/parquet/raw_market_data/` (Raw).

This follows the instruction's suggested division exactly ("Parquet: 대용량
시계열/원본/정규화 시장 데이터; DuckDB: Journal, Experiment, Registry,
metadata 및 분석용 relational data") and additionally keeps every
relational dataset in *one* file so cross-cutting SQL analysis (e.g., "join
experiments to trades to decisions for every strategy_version") is a plain
`JOIN`, not a federation across separate files — directly serving the
"장기간 분석/조회가 가능하도록 partitioning/indexing/query interface를
설계한다" requirement without introducing a second query engine.

Benchmark data (`BenchmarkPoint`) is a DuckDB table, not Parquet, despite
being a time series: a single benchmark index has volume comparable to
metadata (one row per trading day for one series), not to per-security
OHLCV (one row per trading day *per security*). Treating it as "large
time-series data" would be premature engineering for data that will
realistically never need columnar/Parquet-scale handling.

### 2. Parquet append-only, one immutable file per batch

`storage.parquet_layer.write_batch()` never opens an existing `.parquet`
file for append or rewrite — every `append_bars()`/`append_raw_payloads()`
call produces one new file, named with a UUID, written to a temp file in
the same directory and atomically renamed (`os.replace`) into place. This
directly implements Phase 1 spec §17 (Raw Data Immutability) at the
concrete storage layer, and gives crash-safety for free: an interruption
between the write and the rename leaves at most an orphaned temp file that
no reader ever globs (readers only match `*.parquet`), never a
half-written file a query could read mid-write.

Querying is done by pointing DuckDB's `read_parquet()` at a directory glob
(`<dir>/*.parquet`); DuckDB re-expands the glob on every query, so a newly
appended file becomes visible to the next query with no separate "refresh"
or catalog-registration step — restart-safety and append-visibility both
fall out of this without extra bookkeeping.

### 3. Raw vs. Clean market data are physically distinct datasets

Phase 1's domain model only ever materializes the *normalized* `PriceBar`
(Clean layer) — `DataProvider.fetch()` returns raw provider dicts, but
Phase 1's reference `IngestionRunner` never persisted them anywhere; only
`normalize()`'s output reached the repository. Phase 4 adds an explicit
Raw store (`append_raw_payloads()` → `parquet/raw_market_data/`) that
persists the exact pre-normalization payload dict, separately from Clean
`PriceBar`s (`parquet/price_bars/`), directly satisfying the instruction's
explicit minimum list ("Raw Market Data" and "Clean Market Data" as two
distinct items). Raw ingestion is *not* deduplicated by content — every
ingestion run's batch is retained as its own record of "what we received
and when," which is a different question than Clean's "what is the
current, deduplicated value for this security/timestamp."

### 4. Idempotency: application-level natural-key checks, not just DB constraints

- **Clean bars**: `append_bars()` queries existing
  `(security_id, timestamp, provenance.source, provenance.data_version)`
  keys from the Parquet dataset before writing, mirroring
  `IngestionRunner`'s own in-memory dedup (Phase 1 spec §25) one layer
  down, so the repository is idempotent even if a caller bypasses
  `IngestionRunner` entirely.
- **Metadata tables** (`security_master`, `corporate_actions`,
  `benchmark_points`, `universe_membership`): `INSERT ... ON CONFLICT DO
  NOTHING` against a `PRIMARY KEY`/natural-key constraint.
- **Trade Journal** (`decisions`, `trades`): a `natural_key` column
  (`UNIQUE`), checked with a `SELECT` before `INSERT` — this is a
  check-then-insert rather than a database-level `ON CONFLICT ... RETURNING`
  specifically so a duplicate call returns the *existing* record (matching
  `InMemoryTradeJournalRepository`'s documented behavior, Phase 3 spec §8),
  not merely "no-ops."
- **Experiments**: keyed by `experiment_id`, already a globally-unique
  natural key from Phase 2's `ExperimentTracker`.
- **Experience records**: keyed by `trade_id`, *not* the caller-supplied
  `experience_id` — see the "Known correctness fix" note below.

### 5. Repository abstraction preserved; no Phase 1/2/3 consumer code changed

Every persistent repository (`DuckDBDataRepository`,
`DuckDBTradeJournalRepository`, `DuckDBExperimentRepository`,
`DuckDBExperienceRepository`) implements exactly the Protocol its
in-memory predecessor already satisfies (`DataRepository`,
`TradeJournalRepository`, and two new Protocols this phase adds,
`ExperimentRepository`/`ExperienceRepository`, for registries that
previously had no interface at all because they had no second
implementation to be abstracted from). `BacktestEngine`,
`ingest_backtest_result`, and every other Phase 2/3 consumer are
unmodified — they still only ever see the Protocol. `src/baseline/`
(Phase 4's own package) is the only code that constructs a concrete
`DuckDB*Repository` and hands it to Phase 2/3 code as a Protocol value,
exactly mirroring how `ingest_backtest_result` treats Phase 2 as a
read-only source (ADR-0009).

### 6. One small, additive Phase 1 change: `AppendableDataRepository` Protocol

`data_infra.provider.IngestionRunner` was typed against the concrete
`InMemoryDataRepository` class rather than a Protocol. This phase adds
`AppendableDataRepository` (a `DataRepository` extended with
`all_bars()`/`append_bars()`) to `data_infra/repository.py` and widens
`IngestionRunner.__init__`'s type hint to accept it, so
`DuckDBDataRepository` — which implements the same two extra methods —
can be used as an ingestion target with zero `IngestionRunner` code
changes. `InMemoryDataRepository` already satisfies the new Protocol
structurally; this is a type-hint widening only, verified by the full
existing Phase 1-3 suite (202 tests) still passing unmodified.

## Known correctness fix found during this phase's own testing

`trade_journal.experience.build_experience_records()`'s module docstring
already states its `experience_id` ("XR-000001", ...) is "scoped to a
single call, not a globally monotonic sequence." Phase 4's integration
tests (running `build_experience_records` twice against a growing,
persistent journal — the normal Part C pattern) caught that persisting on
this id verbatim would silently drop every experience record after the
first call, once a second call legitimately reused "XR-000001" for a
different trade. `DuckDBExperienceRepository` instead dedupes on
`trade_id` (globally unique, from the persistent Trade Journal's own
`trade_id_seq`) and allocates its own storage-level `experience_id` via a
dedicated `experience_id_seq`, ignoring the caller-supplied one. This is a
Phase 4-internal fix (inside `storage/experience_repository.py`, a file
this phase created) — no Phase 3 code was touched, since Phase 3's
documented scoping of `experience_id` was correct for its own,
single-call, in-memory use.

A second, similar fix: `run_baseline()`/`run_multiple_baselines()`
(`src/baseline/runner.py`) must share one `ExperimentTracker` instance
across multiple baseline runs being compared, because `BacktestEngine`
defaults to a *fresh* tracker per instance (Phase 2 spec §13, and already
exercised by `tests/backtest/test_engine_reproducibility.py`'s
`test_experiment_ids_increment_monotonically_within_a_shared_tracker`).
Two `run_baseline()` calls with independent trackers would both produce
`experiment_id="BT-000001"`, and `ExperimentRepository.record()`'s
idempotency (by design) would then silently drop the second experiment.
`run_multiple_baselines()` shares one tracker across every strategy in a
comparison run so this cannot happen when using that entry point.

## Alternatives Considered

- **Parquet for everything, including Trade Journal/Experiment records**:
  Rejected — these are point-lookup/filter-heavy, small-relative-to-OHLCV
  workloads (natural-key idempotency checks, `audit_trail(trade_id)`
  lookups) that a row-identifiable DuckDB table serves directly; forcing
  them through columnar Parquet files would need a DuckDB table anyway
  just to track natural keys for idempotency, so nothing is saved by
  avoiding a table.
- **PostgreSQL/a server-based database**: Rejected for the same reason
  ADR-0002 rejected it for Phase 1 — this remains a single-process
  research/paper-trading phase; the operational cost of a server process
  is not justified yet. Still flagged (per ADR-0002) as the natural
  migration path if Phase 16 needs concurrent multi-process writers.
- **A generic recursive dataclass↔dict serializer** (e.g. via
  `dataclasses.asdict` + a generic type-directed loader) instead of
  explicit per-type `*_to_row`/`row_to_*` functions in
  `storage/serialization.py`: Rejected — a generic mapper cannot
  correctly round-trip `Enum` members and `timedelta` through JSON without
  re-deriving the target type at read time anyway, and would hide a wrong
  conversion as a silent type mismatch rather than a loud `KeyError`.
  Explicit functions are more code but keep every conversion auditable,
  consistent with this project's fail-closed philosophy applied to
  storage round-tripping.
- **DuckDB `ATTACH`-ing separate database files per domain** (one for
  data, one for journal, one for experiments) instead of one catalog:
  Rejected — see point 1 above; one file enables direct cross-domain SQL
  joins and is simpler to back up/reason about (single file = single
  restore point), with no concurrency requirement in this phase that
  would argue for splitting them.

## Consequences

### Positive

- Every dataset the Phase 4 instruction lists as a minimum (Raw Market
  Data, Clean Market Data, Security Master, Universe Membership,
  Corporate Actions, Benchmark, Trade Journal, Decision Snapshot,
  Order/Fill records, Experiment records, Experience records, version
  metadata) now has a concrete, tested, restart-safe persistent home.
- `DataRepository`/`TradeJournalRepository` consumers (including all of
  Phase 2/3's own code and tests) are completely unaffected — the
  Protocol boundary ADR-0002/ADR-0009 established did its job.
- The single-file DuckDB catalog makes ad hoc analytical SQL across
  experiments/trades/decisions available immediately, without building a
  separate reporting layer.

### Negative / Trade-offs

- DuckDB's single-process embedded model still is not suited to
  concurrent multi-writer access (ADR-0002's already-accepted limitation,
  unchanged by this phase) — a future multi-process Paper/Live Trading
  deployment (Phase 15/16) needing simultaneous ingestion + decision reads
  from separate processes must revisit this.
- Storing full-fidelity `payload_json` blobs alongside flattened query
  columns is some duplication (the same value is queryable both as a
  column and inside the JSON blob) — accepted deliberately: flattened
  columns serve fast/indexed SQL filtering (`WHERE sharpe_ratio > ...`),
  while `payload_json` is the single source of truth for exact
  reconstruction, so neither responsibility is compromised for the other.

## Status of Implementation at Time of This ADR

Implemented in `src/storage/` (`config.py`, `engine.py`, `schema.py`,
`parquet_layer.py`, `serialization.py`, `data_repository.py`,
`trade_journal_repository.py`, `experiment_repository.py`,
`experience_repository.py`) and `src/baseline/` (`runner.py`,
`report.py`), exercised by `tests/storage/`, `tests/baseline/`, and
`tests/integration/`.
