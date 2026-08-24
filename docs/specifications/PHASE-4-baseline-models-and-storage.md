# PHASE 4 SPECIFICATION — Baseline Models + Persistent Data Storage

**Status:** ACTIVE (design confirmed, reference implementation complete)
**Phase:** Phase 4 — Baseline Models
**Depends on:** `PROJECT_MASTER_PLAN.md`, `docs/decisions/ADR-0001` through
`ADR-0009`, Phase 1 (`docs/specifications/PHASE-1-data-infrastructure.md`,
`src/data_infra/*`), Phase 2 (`docs/specifications/PHASE-2-backtesting.md`,
`src/backtest/*`), Phase 3 (`docs/specifications/PHASE-3-trade-journal.md`,
`src/trade_journal/*`)
**Produces ADRs:** ADR-0010 (persistent storage backend implementation)

---

## 0. Purpose of This Document

Phase 4 has two, deliberately paired goals, stated directly in the
initialization instruction:

1. Build a trustworthy **Baseline Model/Strategy** system before any
   complex AI — the point of a baseline is not to maximize return, but to
   establish the bar a future ML/AI system must actually clear to be worth
   its added complexity (`PROJECT_MASTER_PLAN.md` §85-86).
2. Build the **persistent storage layer** (DuckDB + Parquet) that Phase
   1's ADR-0002 designed but deliberately deferred, so that months-to-years
   of future Paper Trading data can accumulate without being lost on
   process restart, and so Trade Journal / Experiment / Experience data
   survive across sessions the same way `PROJECT_MASTER_PLAN.md` requires
   project *documentation* to (§59: "AI가 기억하는 프로젝트가 아니라 파일이
   기억하는 프로젝트다" — this phase extends that principle from documents
   to trading data).

Like every prior phase, **no AI/LLM API, no Toss Securities integration,
and no Live Trading is implemented in this phase.**

---

## 1. Scope

### 1.1 In scope for Phase 4

- A DuckDB + Parquet persistent storage backend implementing the exact
  Protocols Phase 1's `DataRepository` and Phase 3's
  `TradeJournalRepository` already define, plus two new Protocols this
  phase introduces for registries that previously had no interface at all
  (`ExperimentRepository`, `ExperienceRepository`) — see §4 and ADR-0010.
- Restart-safety, append-only immutability, idempotent re-ingestion, and
  provenance preservation for every persisted dataset — verified by tests,
  not asserted by documentation alone (§8, §16).
- A baseline runner (`src/baseline/runner.py`) that runs Phase 2's
  existing `BuyAndHoldStrategy` and `SimpleMomentumStrategy` (both already
  built in Phase 2 — this phase does not add new strategy logic) through
  the same `BacktestEngine`, journals the result via Phase 3's
  `ingest_backtest_result`, and persists the experiment/experience
  records (§9-12).
- A baseline comparison report (`src/baseline/report.py`) that presents
  `PerformanceReport`/`BenchmarkResult` figures side by side without
  declaring a "winner" by return alone (§10).
- Provenance readiness for Paper Trading (`HISTORICAL_SIMULATION |
  PAPER_TRADING | LIVE_TRADING`, already defined in Phase 3) verified
  specifically against the persistent backend (§13-15, Part C).
- Evaluation of whether any of Phase 3's three open `DECISION REQUIRED`
  items must be resolved now (§19 — conclusion: no).

### 1.2 Out of scope for Phase 4

- AI/LLM API calls, Toss Securities integration, real or paper order
  submission, Live Trading — none of this is touched, per explicit
  instruction.
- A Learning Engine that actually trains on the persisted Experience
  Dataset (Phase 9). This phase only makes sure the dataset accumulates
  durably; nothing consumes it yet.
- Market Regime Detection, Prediction Engine, Decision Agent, Position
  Sizing/Risk Engine (Phases 5-8) — the baseline strategies still compute
  their own signal directly, exactly as in Phase 2.
- A real external market data provider. Phase 4's storage layer is
  exercised against the same kind of deterministic mock/fixture data
  Phase 1-3 already use; provider selection remains ADR-0005's deferred,
  dedicated decision.
- Concurrent multi-process/multi-writer access to the DuckDB catalog —
  this remains a single-process phase (ADR-0002's already-accepted
  limitation, reaffirmed by ADR-0010).
- A new baseline "Simple ML" model. Phase 2 spec §10.3 already reserved
  the `Strategy` Protocol as the only thing such a model would need to
  satisfy; Phase 4 does not add one, since the instruction's minimum
  (Buy & Hold + Simple Momentum) is already met by Phase 2's existing
  strategies and adding an unrequested model would be exactly the kind of
  scope creep `PROJECT_MASTER_PLAN.md` §84 warns against.

---

## 2. Phase 1-3 Structures Reused (Investigation Summary)

Re-confirmed by direct inspection of `src/data_infra/`, `src/backtest/`,
`src/trade_journal/` before writing this spec:

| Existing element | Where | Reused as |
|---|---|---|
| `DataRepository` Protocol | Phase 1 | Implemented by `storage.data_repository.DuckDBDataRepository` — no changes to the Protocol itself |
| `TradeJournalRepository` Protocol | Phase 3 | Implemented by `storage.trade_journal_repository.DuckDBTradeJournalRepository` — no changes |
| `BuyAndHoldStrategy` / `SimpleMomentumStrategy` | Phase 2 (`backtest/strategy.py`) | Run directly by `baseline.runner.run_baseline` — no new strategy code |
| `BacktestEngine` / `BacktestConfig` / `BacktestResult` | Phase 2 | Called unmodified by `baseline.runner.run_baseline` |
| `ExperimentTracker` / `ExperimentRecord` | Phase 2 | `ExperimentRecord` is what `storage.experiment_repository.DuckDBExperimentRepository` persists; `ExperimentTracker` itself is untouched, but see §11.1 for a sharing requirement this phase's own testing surfaced |
| `ingest_backtest_result` | Phase 3 | Called unmodified by `baseline.runner.run_baseline` to populate the persistent journal |
| `build_experience_records` | Phase 3 | Called unmodified; its output is what `storage.experience_repository.DuckDBExperienceRepository` persists (see §12.1 for a dedup-key correction this phase made in its own new code, not in Phase 3's) |
| `Order` / `Fill` / `PortfolioView` (frozen dataclasses) | Phase 2 | Serialized/deserialized by `storage/serialization.py` for persistence; the domain types themselves are untouched |

**One additive, backward-compatible Phase 1 change** was made:
`data_infra.repository.AppendableDataRepository`, a new Protocol
(`DataRepository` + `all_bars()`/`append_bars()`), and
`data_infra.provider.IngestionRunner`'s constructor now accepts this
Protocol instead of the concrete `InMemoryDataRepository` class. This is a
type-hint widening only — `InMemoryDataRepository` already satisfies the
new Protocol structurally, no behavior changed, and the full prior-phase
suite (202 tests) passes unmodified after the change. See ADR-0010 §6 for
full reasoning.

No other Phase 1/2/3 source file required modification.

---

## 3. Architecture

### 3.1 Layer diagram

```
Application / Backtest / Trade Journal / Baseline Runner
        │  (depends only on Protocols below — never on DuckDB/Parquet directly)
        ▼
┌─────────────────────────┐   ┌─────────────────────────┐
│ DataRepository (Phase 1) │   │ TradeJournalRepository    │
│ ExperimentRepository      │   │ (Phase 3)                  │
│ ExperienceRepository       │   │                              │
│ (Phase 4, new)              │   └─────────────┬───────────────┘
└─────────────┬─────────────┘                 │
              │                                 │
              ▼                                 ▼
┌───────────────────────────────────────────────────────────┐
│ storage/ (Phase 4)                                          │
│  engine.py      — StorageEngine: one DuckDB connection/file  │
│  schema.py       — idempotent DDL for every relational table  │
│  config.py        — StorageConfig: on-disk file layout          │
│  parquet_layer.py  — append-only Parquet batch writer/reader     │
│  serialization.py   — explicit, typed row<->dataclass conversion  │
│  data_repository.py       — DuckDBDataRepository                    │
│  trade_journal_repository.py — DuckDBTradeJournalRepository          │
│  experiment_repository.py     — DuckDBExperimentRepository            │
│  experience_repository.py      — DuckDBExperienceRepository            │
└─────────────┬─────────────────────────────────┬─────────────────────┘
              ▼                                 ▼
   <root>/catalog.duckdb                 <root>/parquet/
   (all relational/metadata tables)       price_bars/<batch>.parquet
                                           raw_market_data/<batch>.parquet
```

### 3.2 Storage location

`storage.config.StorageConfig(root_dir)` controls where everything lives.
`root_dir` is created (with a `parquet/` subdirectory) on first use.
Production/paper-trading usage is expected to point `root_dir` at
`data/storage/` (the repository's existing, previously-empty `data/`
directory — see `PROJECT_MASTER_PLAN.md` §59's directory layout); every
test in this phase uses `tmp_path` so the real `data/` directory is never
touched by the test suite itself.

### 3.3 One DuckDB catalog, Parquet only for OHLCV-scale time series

See ADR-0010 §1 for full reasoning. In short: everything **except**
per-security price bars (Raw and Clean) lives in DuckDB tables inside one
catalog file, because only per-security OHLCV volume scales as
`securities × trading days` and can plausibly reach a size where
columnar Parquet + DuckDB's native `read_parquet()` meaningfully
outperforms a row-oriented table. Benchmark data, despite being a time
series, is small enough (one series) that it stays a DuckDB table.

---

## 4. Persisted Data Scope

Every dataset the Phase 4 instruction lists as a minimum now has a
concrete, tested, restart-safe home:

| Dataset | Storage | Module |
|---|---|---|
| Raw Market Data | Append-only Parquet (`parquet/raw_market_data/`) | `data_repository.py::append_raw_payloads` |
| Clean Market Data | Append-only Parquet (`parquet/price_bars/`) | `data_repository.py::append_bars`/`get_bars` |
| Security Master | DuckDB table `security_master` | `data_repository.py::add_security`/`get_security` |
| Universe Membership | DuckDB table `universe_membership` | `data_repository.py::add_universe_membership`/`get_universe` |
| Corporate Actions | DuckDB table `corporate_actions` | `data_repository.py::add_corporate_action`/`get_corporate_actions` |
| Benchmark | DuckDB table `benchmark_points` | `data_repository.py::add_benchmark_point`/`get_benchmark` |
| Trade Journal (Decision Snapshot, Trade Record, Post Trade Analysis, Counterfactual, Correction) | DuckDB tables `decisions`, `trades`, `post_trade_analyses`, `counterfactuals`, `corrections` | `trade_journal_repository.py` |
| Order/Fill records | Embedded inside `decisions.payload_json`/`trades.payload_json` (full-fidelity `Order`/`Fill` objects, same embedding discipline as Phase 3's in-memory implementation, ADR-0009 §1) | `trade_journal_repository.py` |
| Experiment records | DuckDB table `experiments` | `experiment_repository.py` |
| Experience records | DuckDB table `experience_records` | `experience_repository.py` |
| Data/Feature/Model/Strategy version metadata | Columns on `decisions`/`trades`/`experiments`/`experience_records` (`data_version`, `feature_version`, `model_version`, `strategy_version`, `risk_version`, `configuration_version`) — no separate registry table, since every version value already has a queryable home on the record it describes | (all of the above) |

Every table's DDL lives in `storage/schema.py` and is idempotent
(`CREATE TABLE IF NOT EXISTS` / `CREATE SEQUENCE IF NOT EXISTS`), so
reopening an existing catalog file never redefines or truncates a table.

---

## 5. Raw vs. Clean Market Data

Phase 1's reference implementation only ever materialized the
*normalized* `PriceBar` (Clean layer); the pre-normalization provider
payload was never persisted anywhere, even in-memory. Phase 4 adds an
explicit Raw store (`append_raw_payloads`) that persists the exact
payload dict `DataProvider.fetch()` returned, as its own, physically
separate Parquet dataset (`parquet/raw_market_data/`), with a DuckDB
manifest table (`raw_ingestion_batches`) recording which batches exist.

Raw ingestion is **not** deduplicated by content the way Clean bars are —
every ingestion run's batch is retained as its own record of "what we
received and when." This matches Phase 1's Raw Data Immutability
principle (Phase 1 spec §17) applied literally: Raw answers "what did we
receive," not "what is the current value" (that is Clean's job).

---

## 6. Restart Safety, Immutability, Idempotency (design summary; full
test evidence in §16)

- **Restart safety**: `StorageEngine` reopens an existing DuckDB file and
  re-runs (idempotent) schema DDL; Parquet directories are read via glob,
  which re-expands on every query. Verified in `tests/storage/*` by
  closing one `StorageEngine`, opening a second one against the same
  `StorageConfig`, and reading back everything written by the first.
- **Append-only immutability**: Parquet batches are written to a temp
  file and atomically renamed into place (`os.replace`); no code path
  opens an existing `.parquet` file for in-place modification. DuckDB
  table rows for Trade Journal/market metadata have **no**
  `update_*`/`delete_*` method on any repository class — mutation is
  structurally unreachable, exactly matching Phase 3's in-memory
  discipline (ADR-0009 §2-3). Corrections remain additive
  (`record_correction` → `CorrectionRecord`), never in-place edits.
- **Idempotency**: natural-key checks before every insert (see ADR-0010
  §4 for the exact key per dataset), so re-running ingestion, re-ingesting
  a `BacktestResult`, or re-persisting an `ExperimentRecord` never
  duplicates a row.
- **Failure/corruption handling**: (a) the temp-file-then-atomic-rename
  Parquet write pattern means a crash between write and rename leaves at
  most an orphaned temp file, never a partially-written `.parquet` a
  reader could pick up; (b) DuckDB table writes made inside an explicit
  transaction roll back completely on error — verified directly in
  `tests/storage/test_failure_recovery.py` by forcing both failure modes.
- **Version consistency**: `data_version`/`strategy_version`/
  `configuration_version`/`experiment_id` are always copied verbatim from
  the upstream Phase 1-3 object that produced them, never re-derived at
  storage time — the same discipline Phase 3's Point-in-Time-applied-to-
  the-Journal principle already established (Phase 3 spec §4), continued
  one layer down into the persistent backend.

---

## 7. Long-Horizon Query Interface (and why not more than this)

DuckDB's SQL surface is the query interface — every persisted table is
directly queryable (`tests/integration/test_experiment_to_storage.py`
exercises a raw SQL query across the `experiments` table as a concrete
example). No additional indexing beyond each table's declared
`PRIMARY KEY`/`UNIQUE` constraints and DuckDB's own automatic statistics
is added in this phase: the instruction explicitly warns against
premature optimization (`PROJECT_MASTER_PLAN.md` §84), and this phase has
no real multi-year dataset yet against which a specific indexing/
partitioning need could be identified rather than guessed. Parquet
directories are organized per-security under `price_bars/`/
`raw_market_data/` purely for human/operational legibility (so a
directory listing shows which securities have data); query correctness
does not depend on that layout, since `get_bars`/`get_raw_payloads`
filter by the `security_id` **column**, not by parsing directory names.

---

## 8. Test Strategy (Storage)

Phase 4's initialization instruction requires: write, restart, read,
append, duplicate ingestion, idempotency, corruption/failure handling,
version consistency. Each is covered:

| Requirement | Test file |
|---|---|
| Write / read / append | `tests/storage/test_data_repository_persistence.py` |
| Restart recovery | `tests/storage/test_data_repository_persistence.py`, `test_trade_journal_persistence.py`, `test_experiment_repository.py`, `test_experience_repository.py` (each has a dedicated restart test) |
| Duplicate ingestion / idempotency | `test_data_repository_persistence.py::test_append_is_idempotent_on_natural_key`, `test_trade_journal_persistence.py::TestIdempotency`, `test_experiment_repository.py::test_recording_same_experiment_id_twice_is_idempotent`, `test_experience_repository.py::test_record_many_is_idempotent` |
| Immutable records | `test_trade_journal_persistence.py::TestImmutability`, `test_data_repository_persistence.py::test_append_creates_new_immutable_file_never_rewrites` |
| Provenance | `test_raw_market_data.py`, `test_trade_journal_persistence.py::TestProvenanceSeparation`, `test_experience_repository.py::test_provenance_filter_never_mixes_categories` |
| Version lineage | `test_trade_journal_persistence.py::TestVersionLineage`, `test_experiment_repository.py` (configuration/data/code version round-trip) |
| Corruption/failure handling | `test_failure_recovery.py` (both atomic-Parquet-write and DuckDB-transaction-rollback scenarios) |

---

## 9. Baseline Strategies

Both required baselines already exist, built in Phase 2 and unmodified by
this phase:

- **S&P 500 Buy & Hold** — `backtest.strategy.BuyAndHoldStrategy`.
- **Simple Momentum** — `backtest.strategy.SimpleMomentumStrategy`.

Both already implement the shared `Strategy` Protocol (Phase 2 spec §5)
and already run through the identical `BacktestEngine` — the "동일한
Backtest Engine에서 실행되어야 한다" requirement (Part B point 9) was
already satisfied by Phase 2's design; Phase 4 formalizes *running and
comparing* them, not their existence.

---

## 10. Baseline Runner and Comparison Report

`src/baseline/runner.py::run_baseline` wires, for one strategy:

```
BacktestEngine.run()
    -> trade_journal.backtest_adapter.ingest_backtest_result()
    -> (optional) ExperimentRepository.record()
    -> (optional) ExperienceRepository.record_many()
```

`run_multiple_baselines({label: strategy, ...}, ...)` runs every entry
against the **same** `BacktestConfig`/`DataRepository` (same period,
capital, cost model, benchmark) with one **shared** `ExperimentTracker` —
see §11.1 for why sharing the tracker is required.

`src/baseline/report.py::build_comparison_report`/`compare_reports`
assemble the already-computed `PerformanceReport`/`BenchmarkResult`
figures (cumulative return, CAGR, volatility, Sharpe, Sortino, max
drawdown, Calmar, turnover, transaction cost, win rate, avg trade return,
excess return, annualized excess return — the full Phase 2 spec §11 list)
side by side. **No new metric is computed and no accept/reject gate is
introduced** — `BaselineComparisonReport` deliberately has no
rank/best/winner field (enforced by
`tests/baseline/test_baseline_runner.py::test_baseline_purpose_is_not_return_maximization_no_ranking_field`),
directly implementing Part B point 12: the baseline's purpose is to
establish a reference point for future AI, not to be "won."

### 10.1 Sharing an `ExperimentTracker` across baseline runs

`BacktestEngine` defaults to a **fresh** `ExperimentTracker` per instance
(Phase 2 spec §13; already exercised by
`tests/backtest/test_engine_reproducibility.py`'s
`test_experiment_ids_increment_monotonically_within_a_shared_tracker`).
Two independent `run_baseline()` calls, each creating its own
`BacktestEngine` with no tracker passed in, therefore both produce
`experiment_id="BT-000001"` — and because
`ExperimentRepository.record()` is deliberately idempotent on
`experiment_id` (§11 below), the *second* call's experiment would
silently fail to persist (not error — just vanish), which is exactly the
kind of quiet failure this project's fail-closed philosophy exists to
prevent. This was caught by this phase's own integration testing before
being documented here, not discovered later. `run_multiple_baselines()`
resolves it by constructing one `ExperimentTracker` and passing it to
every `run_baseline()` call in the comparison; `run_baseline()` also
accepts an explicit `experiment_tracker` argument directly for callers
managing this themselves.

---

## 11. Experiment Repository

`storage.experiment_repository.ExperimentRepository` (new Protocol) +
`DuckDBExperimentRepository` persist a Phase 2 `ExperimentRecord`
verbatim: `experiment_id`, `strategy_version`, `data_version`,
`feature_version`, `configuration_version`, `start_date`/`end_date`,
`initial_capital`, `transaction_cost_config`, `slippage_config`,
`benchmark`, the full `PerformanceReport` (`metrics`), `code_version`,
`seed`, `result`, `timestamp`. Flattened scalar columns
(`sharpe_ratio`, `cagr`, `max_drawdown`, ...) exist alongside a
full-fidelity `payload_json` blob so both fast SQL filtering and exact
reconstruction are served (ADR-0010 §"Negative/Trade-offs").

Phase 2's `BacktestEngine`/`ExperimentTracker` are **not modified** —
persistence is an explicit, additional step the caller (the baseline
runner) performs after `engine.run()` returns, mirroring exactly how
`ingest_backtest_result` already treats Phase 2 as a read-only source
(ADR-0009).

### 11.1 See §10.1 for the shared-tracker requirement this repository's idempotency depends on.

---

## 12. Experience Repository (Part C readiness)

`storage.experience_repository.ExperienceRepository` (new Protocol) +
`DuckDBExperienceRepository` persist Phase 3's `ExperienceRecord`s.

### 12.1 Dedup key: `trade_id`, not `experience_id`

`trade_journal.experience.build_experience_records`'s own module
docstring documents `experience_id` as scoped to a single call, not a
globally monotonic sequence — correct for Phase 3's in-memory,
single-call use, but calling it twice against a **growing, persistent**
journal (the normal Part C pattern: the journal accumulates trades over
days/months of paper trading, and `build_experience_records` is re-run
periodically to pick up new trades) legitimately produces the same
`"XR-000001"` for two different trades on two different calls. This
phase's own integration testing caught that persisting on that id
verbatim would silently drop every record after the first call.
`DuckDBExperienceRepository` therefore dedupes on `trade_id` (globally
unique, from the persistent journal's own monotonic sequence) and
allocates its own storage-level `experience_id` via a dedicated DuckDB
sequence, discarding the caller-supplied one. See ADR-0010's "Known
correctness fix" section for the full account. This is a Phase
4-internal correction (inside code this phase created); Phase 3's
`experience.py` was not modified, since its documented scoping was
correct for what it was actually used for at the time.

---

## 13. Paper Trading Data Foundation (Part C)

`PROJECT_MASTER_PLAN.md` §4.3-4.4's full loop —
`Market Data → Strategy/Model → Decision → Risk → Order → Fill → Trade
Journal → Experience Dataset` — already has a place to land, end to end,
through the persistent backend built in this phase:
`tests/integration/test_backtest_to_storage.py` and
`tests/baseline/test_baseline_runner.py` exercise the whole chain from
`BacktestEngine` through to a restart-surviving, queryable
`ExperienceRecord`.

**No Risk Engine or Decision Agent exists yet** (Phase 7-8), so today
this loop is exercised only via Phase 2's simplified
`Strategy.generate_orders` → `Order` path, exactly as Phase 2/3 already
documented as their own scope boundary. Nothing in this phase assumes
those layers exist; `DecisionSnapshot`'s reserved fields for them
(`risk_state`, `expected_return`, ...) remain `None`, unchanged from
Phase 3.

---

## 14. Provenance Readiness for Paper/Live Trading

`TradeProvenance.HISTORICAL_SIMULATION | PAPER_TRADING | LIVE_TRADING`
(defined in Phase 3) is verified against the **persistent** backend
specifically in this phase
(`tests/storage/test_trade_journal_persistence.py::TestProvenanceSeparation`,
`tests/storage/test_experience_repository.py::test_provenance_filter_never_mixes_categories`):
every list/query method that accepts a `provenance` filter correctly
isolates each category after a restart, and no code path infers or
defaults `provenance` — it is always copied verbatim from the caller, the
same discipline Phase 3 already established (Phase 3 spec §10.2)
continued through the persistent layer.

No Paper/Live producer of `PAPER_TRADING`/`LIVE_TRADING` records exists
yet (Phase 13/15/16) — this phase proves the storage and separation are
ready to receive them, not that they are being produced.

---

## 15. Learning Engine — explicitly not built

Per `PROJECT_MASTER_PLAN.md` §11 and this phase's explicit instruction,
no Learning Engine is implemented. `DuckDBExperienceRepository.list_all()`
exists so a future Phase 9 Learning Engine has a durable dataset to read
from; nothing in this phase trains on it, scores it, or assumes any
particular reward-function design beyond what Phase 3 already
provisionally established (`reward = realized_return`, documented in
Phase 3 spec §5.8 as a placeholder, not a claimed-correct signal).

---

## 16. Test Strategy (Baseline + Integration)

| Requirement | Test file |
|---|---|
| Deterministic replay | `tests/baseline/test_baseline_runner.py::TestDeterministicReplay` |
| Benchmark comparison | `tests/baseline/test_baseline_runner.py::TestBenchmarkComparisonAndMetrics` |
| Transaction cost / slippage | `test_baseline_runner.py::test_transaction_cost_and_slippage_are_nonzero_by_default` |
| Metric correctness | `test_baseline_runner.py::test_excess_return_matches_strategy_minus_benchmark`, `test_report_contains_all_required_metric_fields` |
| Reproducibility | `test_baseline_runner.py::TestReproducibility` (including a restart-surviving variant) |
| Backtest → Trade Journal → Persistent Storage | `tests/integration/test_backtest_to_storage.py` |
| Experiment → Persistent Storage | `tests/integration/test_experiment_to_storage.py` |

All of Phase 1-3's existing tests (202) continue to pass unmodified
(`python3 -m pytest tests/ -q`); Phase 4 adds 51 new tests (34 storage +
9 baseline + 8 integration), for **253 total**.

---

## 17. Configuration

No new environment variables or secrets are introduced — the storage
backend is purely local-file-based (`StorageConfig.root_dir`), consistent
with `PROJECT_MASTER_PLAN.md` §14's configuration/secrets discipline; no
credential of any kind is needed to read/write a local DuckDB file or
Parquet directory. `pyproject.toml` now declares `duckdb`/`pyarrow` as
runtime dependencies (previously dev-only `pytest`), since the storage
backend is now part of `src/`, not merely tooling.

---

## 18. Interaction with the Master Plan and Prior Phases

No conflicts were found between this specification and
`PROJECT_MASTER_PLAN.md` / ADR-0001, or with the Phase 1-3 specifications
and ADRs. One additive, backward-compatible change was made to Phase 1
code (§2, `AppendableDataRepository`) — verified against the full prior
test suite. Two correctness fixes were made in **this phase's own new
code** (§10.1 experiment-tracker sharing, §12.1 experience-record dedup
key) after being caught by this phase's integration tests; neither
required touching Phase 2 or Phase 3 source.

---

## 19. DECISION REQUIRED Review — Phase 3's Three Open Items

Per instruction, this phase evaluated whether any of Phase 3's three
outstanding `DECISION REQUIRED` items must be resolved now, rather than
deferring by default.

1. **Benchmark return type (PRICE_RETURN vs. TOTAL_RETURN)** — Not
   resolved. This is a real-data-provider-sourcing decision (ADR-0005
   scope), unaffected by adding a persistent storage backend:
   `BenchmarkPoint.return_type` is stored and round-tripped exactly as
   given, for either value, with no change in this phase. Nothing in
   Phase 4's storage design requires picking one to proceed.
2. **Per-decision `data_version` on `DecisionSnapshot`** — Not resolved.
   This remains a Phase 2 `BacktestEngine` architecture question (whether
   to expose which bar's `data_version` informed each individual
   decision), not a storage question — the persistent
   `DuckDBTradeJournalRepository` stores whatever value
   `ingest_backtest_result` gives it (`None`, today), faithfully and
   losslessly. Building storage for a field does not require deciding
   how that field gets populated.
3. **Corporate-action-aware `portfolio_state` reconstruction** — Not
   resolved, for the same reason: this is about what
   `ingest_backtest_result` computes before handing a `PortfolioView` to
   the Journal, not about how the Journal (or its persistent backend)
   stores it. The persistent repository stores the exact `PortfolioView`
   it is given, with the same fidelity as the in-memory implementation.

**Conclusion**: none of the three require resolution to complete Phase
4's mandate. All three remain correctly deferred, consistent with
`docs/PROJECT_STATUS.md` Session 4's own recommendation to revisit them
at Phase 9 (Learning Engine) if finer per-decision lineage precision
becomes materially necessary at that point.

---

## 20. Definition of Done for Phase 4

- [x] Master Plan / prior ADRs / prior specs reviewed (§0-2)
- [x] This specification written
- [x] Persistent Storage architecture defined (§3-8, ADR-0010)
- [x] Repository abstraction preserved — no Phase 1-3 consumer code
      changed beyond one additive Protocol widening (§2, §18)
- [x] Restart safety, immutability, idempotency, provenance, version
      lineage, failure/corruption handling implemented and tested (§6, §8)
- [x] Baseline strategies run through the shared `BacktestEngine` (§9)
- [x] Baseline vs. benchmark comparison report, without a return-only
      accept/reject gate (§10)
- [x] Every experiment recorded with the full required field set (§11)
- [x] Paper Trading data foundation (provenance separation, Experience
      Dataset persistence) verified against the persistent backend (§12-15)
- [x] DECISION REQUIRED review completed — none required resolution now (§19)
- [x] Full test suite passing: 253/253 (202 prior + 51 new)
- [x] `docs/PROJECT_STATUS.md` updated
- [x] `README.md` updated
- [x] Design + reference implementation committed to git
