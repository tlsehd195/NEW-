# PHASE 10 SPECIFICATION — Counterfactual / Attribution

## 0. Git / Branch Integrity Check (prerequisite, performed before any Phase 10 work)

Performed at session start, from scratch, not reusing any prior session's
PASS result (per repeated user instruction in every prior phase).

Findings:

- The designated working branch `claude/phase-10-counterfactual-attribution-ubum6u`
  (as freshly checked out at session start) contained only the repository's
  `Initial commit` (`c3abad0`) — it had been created from `main`, not from
  the Phase 0-9 lineage. `origin/claude/phase-10-counterfactual-attribution-ubum6u`
  had already been deleted upstream (observed as `[deleted]` on `git fetch --prune`).
- The real Phase 0-9 lineage lives on `origin/claude/phase-4-baseline-storage-tuavwk`,
  HEAD `0bd2350` ("Phase 9: Learning Engine").
- `c3abad0` (the designated branch's only commit) was verified to be an
  ancestor of `0bd2350` (`git merge-base --is-ancestor`), i.e. identical to
  the root of the real lineage — no content existed on the designated
  branch that the real lineage did not already contain.
- Resolution: `git checkout -B claude/phase-10-counterfactual-attribution-ubum6u origin/claude/phase-4-baseline-storage-tuavwk`
  — a local branch-pointer reset, not a rewrite of any shared history
  (the stale remote branch was already gone; nothing was force-pushed).
- Post-reset verification: `git log --oneline` shows the full linear chain
  Initial commit -> Phase 0 -> ... -> Phase 9 (`0bd2350`), zero merge
  commits (`git log --merges` empty), `origin/main` and
  `origin/claude/autonomous-ai-investment-system-wvscwe` both verified
  ancestors of HEAD, working tree clean.
- All Phase 9 deliverables present on disk (`src/learning/`,
  `src/storage/learning_repository.py`,
  `docs/specifications/PHASE-9-learning-engine.md`, ADR-0015).
- Baseline test run (after installing the `duckdb`/`pyarrow`/`pytest`
  dependencies declared in `pyproject.toml` but not preinstalled in this
  fresh container): **553/553 passed**.

**Verdict: PASS** (with the branch-pointer correction above recorded as a
deviation from the literal session handoff, not from the actual, verified
repository state). Phase 10 proceeds on this basis.

---

## 1. Purpose of This Document

Specifies the design, scope, and boundaries of Phase 10 — Counterfactual
Analysis and Performance Attribution — per `PROJECT_MASTER_PLAN_SOURCE.md`
sections 33 ("Counterfactual Analysis") and 34 ("Performance Attribution"),
building on the placeholder types Phase 3 already defined for this purpose
(`docs/specifications/PHASE-3-trade-journal.md` sections 5.6, 5.7, 7.2;
ADR-0009).

---

## 2. Scope

### 2.1 In scope for Phase 10

- A second, honestly-computable `AlternativeOutcome` — the **CASH**
  counterfactual ("what if the capital that was deployed had simply sat
  in cash, earning the system's assumed risk-free rate, from
  `decision_time` to `evaluation_time`?"). Combined with Phase 3's
  existing **HOLD** counterfactual, a `CounterfactualRecord` can now carry
  two real alternatives instead of one.
- A convenience comparison: the realized advantage of the actually
  selected action over each computed alternative
  (`trade.realized_return - alternative.hypothetical_return`), computed
  only when both sides are real numbers.
- Two new `AttributionResult` components that Phase 2's `BenchmarkEngine`
  and `PerformanceReport` (both already built, unchanged) now make
  honestly computable:
  - `market` — the benchmark's own cumulative return over the identical
    experiment window (`PerformanceReport.benchmark_cumulative_return`).
  - `selection` — the exact residual `cumulative_return - market -
    execution`, i.e. whatever part of the strategy's return is not
    explained by passive market exposure or the (already Phase-3-computed)
    execution cost drag.
- A new, additive persistence path for `AttributionResult` (which,
  unlike `CounterfactualRecord`/`PostTradeAnalysis`, has never had a
  repository — Phase 3 defined the type but nothing writes or reads it).
  `CounterfactualRecord` persistence is **not** re-implemented — Phase 3's
  `TradeJournalRepository.record_counterfactual` / `get_counterfactual`
  (in-memory and DuckDB) already accept and round-trip an arbitrary tuple
  of `AlternativeOutcome`s; Phase 10 simply calls it with a richer tuple.
- Pure orchestration functions (`src/counterfactual/`) that assemble
  these results from already-computed Phase 2/3 data. No new
  `AsOfDataView` or `DataRepository` call site is introduced beyond the
  one Phase 3 already established (`compute_hold_counterfactual`'s call
  to `DataRepository.get_bars(..., as_of_time=evaluation_time)`, reused
  unchanged) — the CASH alternative and both new attribution components
  require no data repository access at all.

### 2.2 Out of scope for Phase 10 (explicitly deferred)

- `alternative_action_1` / `alternative_action_2` (master plan section
  33) — Phase 3 section 7.2 already established that a counterfactual
  against *a different model's or strategy's hypothetical decision*
  "requires that alternative to actually exist and be runnable" and
  assigned this to **Phase 11 (Model Evolution)**. That reasoning still
  holds: Phase 6-9 gave the system multiple `Predictor` implementations
  and a rule-based `DecisionAgent`, but running an alternate model's full
  decision pipeline against the same historical window to produce a
  second, independently-generated action is exactly Model Evolution's
  charter, not this phase's. Phase 10 does not implement it.
- `sector` / `factor` attribution — still no sector/factor data source
  (`data_infra.models.SecurityMaster` has no such fields; unchanged
  Known Issue since Phase 8/ADR-0014 section 9).
- `timing` attribution — a rigorous, honest timing/allocation effect
  (as distinct from `selection`) requires a Brinson-Fachler-style
  time-varying-weight-vs-benchmark decomposition. The system has the raw
  ingredients (`PositionSizingResult.proposed_target_weight` time
  series, `BenchmarkResult.value_series`) but building and validating
  that model is a materially larger, separate piece of work with real
  risk of producing a number that *looks* precise but embeds an
  unstated methodological assumption. Per this project's standing
  principle ("정확한 counterfactual/attribution 결과를 계산할 수 없는
  경우 추정값을 사실처럼 저장하지 않는다"), `timing` stays `None`,
  reserved, same as Phase 3 left it.
- `PostTradeAnalysis`'s other reserved fields (`prediction_error`,
  `timing_error`, `risk_estimation_error`, `regime_error`,
  `signal_error` — master plan section 32, `Phase 3 spec section 5.5`).
  Post Trade Analysis is a distinct master-plan section (32) from
  Counterfactual (33) / Attribution (34); filling those fields in is a
  natural next increment but not this phase's explicit charter. Left
  untouched.
- Any order/broker/execution mutation, any automatic `CandidateModelStatus`
  transition, any Paper/Live Trading behavior (Phases 12-16).

### 2.3 Changes to Phase 1-9 code

None. Phase 10 is 100% additive:

- `src/counterfactual/` — entirely new package.
- `src/storage/schema.py` / `src/storage/serialization.py` — pure
  additions (one new table + sequence, two new serialization functions);
  `git diff | grep '^-'` on both files shows no deletions or edits to
  existing lines.
- `src/storage/counterfactual_repository.py` — entirely new file.
- No existing file in `src/trade_journal/`, `src/backtest/`,
  `src/data_infra/`, `src/regime/`, `src/predict/`, `src/decision/`,
  `src/risk/`, `src/learning/`, or `src/baseline/` is modified.

---

## 3. Counterfactual Analysis

### 3.1 What already existed (Phase 3, unchanged)

`trade_journal.analysis.compute_hold_counterfactual(repository,
security_id, decision_time, evaluation_time)` — "if, instead of trading,
the position had simply been left alone from `decision_time` to
`evaluation_time`, what would the security's own price return have been?"
A real, post-hoc price replay. Phase 10 imports and calls this function;
it is not modified or reimplemented.

### 3.2 New: the CASH alternative

`counterfactual.counterfactual.compute_cash_counterfactual(decision_time,
evaluation_time, risk_free_rate=0.0)` — "if, instead of trading, the
capital had simply sat in cash from `decision_time` to `evaluation_time`?"

This system has no risk-free-rate data source anywhere (every existing
`risk_free_rate` parameter in the codebase — `backtest.metrics.
sharpe_ratio`/`sortino_ratio` — defaults to `0.0` and no caller overrides
it). Consistent with that existing, documented assumption,
`compute_cash_counterfactual` defaults `risk_free_rate=0.0` and computes
`hypothetical_return = risk_free_rate * (horizon.days / 365.25)` — exactly
`0.0` under the system's standing zero-rate assumption, and a real,
non-fabricated number if a caller ever supplies a nonzero rate. `basis`
is always stated (`"cash_baseline_zero_rate"` or
`"cash_baseline_explicit_rate"`) so nothing here is ever presented as a
market-derived figure. No `DataRepository` call is made — this
alternative needs no market data at all.

### 3.3 `build_counterfactual_record`

`counterfactual.counterfactual.build_counterfactual_record(repository,
trade, selected_action, decision_time, evaluation_time, *,
risk_free_rate=0.0, computed_at=None) -> CounterfactualRecord` assembles
`(hold_outcome, cash_outcome)` into a `trade_journal.models.
CounterfactualRecord` — the exact Phase 3 type, unmodified. `evaluation_time`
is a required, explicit parameter (never internally defaulted to "now"),
matching Phase 3's own `compute_hold_counterfactual` signature and this
project's standing rule against hidden nondeterminism.

### 3.4 `compute_counterfactual_advantage`

`counterfactual.counterfactual.compute_counterfactual_advantage(trade,
alternative) -> Optional[float]` = `trade.realized_return -
alternative.hypothetical_return` when both sides are real (not `None`).
This is the direct, literal implementation of master plan section 33's
"실제로 선택한 행동과 선택하지 않은 행동을 비교한다" — a real, signed
number, `None` when either side is unknown (e.g. an unrealized/open
trade), never estimated.

### 3.5 Persistence

Unchanged: `TradeJournalRepository.record_counterfactual(trade_id,
selected_action, alternatives)` / `get_counterfactual(trade_id)` (Phase 3,
both in-memory and DuckDB implementations) already accept any tuple of
`AlternativeOutcome`. Phase 10's orchestration
(`counterfactual.pipeline.run_counterfactual_analysis`) builds the record
and hands it to the caller, who persists it exactly as Phase 3 already
does — no new table, no new repository method. `storage.serialization.
counterfactual_to_payload` / `payload_to_counterfactual` already
round-trip an arbitrary-length `alternatives` tuple (verified by reading
the existing implementation; no change needed).

Because `trade_journal.experience.build_experience_records` already reads
`journal.get_counterfactual(trade.trade_id).alternatives` into
`ExperienceRecord.counterfactual_results` (Phase 3, unmodified), a
2-alternative `CounterfactualRecord` produced by Phase 10 flows into the
Learning Engine's Experience Dataset automatically, with zero changes to
`trade_journal/` or `learning/`.

---

## 4. Performance Attribution

### 4.1 What already existed (Phase 3, unchanged)

`trade_journal.analysis.compute_execution_attribution(transaction_costs,
initial_capital) -> float` = `-(transaction_costs / initial_capital)` —
the aggregate execution cost drag as a fraction of starting capital, at
**experiment** level (not trade level — Phase 3 section 5.7 already
established that market/sector/factor/selection/timing decomposition is
inherently a portfolio-level analysis). Phase 10 imports and calls this
function unchanged.

### 4.2 New: `market`

`counterfactual.attribution.compute_market_attribution(metrics:
PerformanceReport) -> Optional[float]` = `metrics.
benchmark_cumulative_return` — the benchmark's own cumulative return over
the identical experiment window, already computed by Phase 2's
`BenchmarkEngine` and carried on every `PerformanceReport`. `None`
exactly when no benchmark was configured for the experiment (honest
absence, not a computed zero). This inherits Phase 2 section 9.3's still
-open `DECISION REQUIRED` on `PRICE_RETURN` vs `TOTAL_RETURN` benchmark
semantics unchanged — Phase 10 does not resolve it, consistent with
every prior phase's re-review-and-defer of that item.

### 4.3 New: `selection` (residual)

`counterfactual.attribution.compute_selection_attribution(metrics,
market, execution) -> Optional[float]`:

```
selection = cumulative_return - market - execution      (when market is not None)
selection = None                                          (when market is None)
```

By construction this is an **exact identity**:
`market + selection + execution == metrics.cumulative_return` whenever
`market` is not `None`. This is the one attribution invariant Phase 10
guarantees and tests directly
(`tests/counterfactual/test_attribution.py::
TestAttributionReconciles`). `selection` is documented, in both the
docstring and this spec, as a **combined** selection-and-timing residual
— whatever active return remains once passive market exposure and
execution cost drag are removed — not a claim of pure stock-picking
skill in isolation from timing effects. A true, separately-computed
`timing` component (section 2.2) would need to be subtracted out of this
residual by a future phase, not fabricated by this one.

### 4.4 `build_attribution_result`

`counterfactual.attribution.build_attribution_result(experiment:
ExperimentRecord, computed_at=None) -> AttributionResult` reads
`experiment.metrics` (a `PerformanceReport`) and `experiment.
initial_capital` — both already persisted by Phase 4's `ExperimentRepository`
— and returns the exact Phase 3 `AttributionResult` type: `market` and
`selection` populated as above, `execution` via Phase 3's unchanged
function, `sector`/`factor`/`timing` left `None` (reserved, per 2.2).

### 4.5 Persistence

`AttributionResult` has never had a repository (Phase 3 defined the type
only). Phase 10 adds one:

- `counterfactual.repository.AttributionRepository` (Protocol) +
  `InMemoryAttributionRepository` — `record`, `get` (latest by
  `experiment_id`), `get_history`, `list_all`. Mirrors the append/
  latest-wins discipline Phase 3 already uses for `PostTradeAnalysis`/
  `CounterfactualRecord` (section 9 of the Phase 3 spec,
  "Immutability & Correction") — `AttributionResult` has no field of its
  own that identifies one version as authoritative other than recency,
  exactly like those two types, so it gets the same discipline rather
  than a new one invented for this phase.
- `storage.counterfactual_repository.DuckDBAttributionRepository` —
  persistent implementation, new `attribution_results` table (`seq`
  primary key via a new `attribution_seq` sequence, `experiment_id`,
  `computed_at`, `payload_json`), same shape as the existing
  `post_trade_analyses`/`counterfactuals` tables (section 15 of the
  Phase 4 spec's persistence pattern).

---

## 5. Point-in-Time / Leakage Protection

Phase 10 introduces **zero new `AsOfDataView`/`DataRepository` call
sites**:

- The CASH counterfactual makes no data query at all (its result is a
  pure function of `decision_time`, `evaluation_time`, and the caller-
  supplied `risk_free_rate`).
- The HOLD counterfactual reuses Phase 3's `compute_hold_counterfactual`
  verbatim, including its existing `as_of_time=evaluation_time` guard
  (already justified in Phase 3 spec section 7.2 as legitimate
  retrospective analysis, mirroring Phase 2 spec section 8.3's reasoning
  for benchmark/mark-to-market queries).
- `build_attribution_result` performs no data repository query
  whatsoever — it only reads fields off an already-computed,
  already-persisted `ExperimentRecord`. Its point-in-time safety is
  entirely inherited from Phase 2's `BenchmarkEngine`
  (`as_of_time`-guarded, unchanged) and Phase 4's `ExperimentRepository`
  (unchanged).

`tests/counterfactual/test_point_in_time.py` verifies: (a)
`compute_cash_counterfactual` never imports or calls anything from
`data_infra`; (b) recomputing a `CounterfactualRecord` for the same trade
after new, later bars have been ingested into the repository produces a
byte-identical result to before those bars existed, for a fixed
`evaluation_time` (the same discipline Phase 6/7/8's own
`test_*_point_in_time.py` files already established); (c)
`build_attribution_result` is a pure function of its `ExperimentRecord`
input with no hidden global/clock read.

---

## 6. Provenance Separation

Neither `CounterfactualRecord` nor `AttributionResult` carries its own
`provenance` field (Phase 3's original design; `ExperimentRecord` itself
has no `provenance` field either — inherited gap, not something Phase 10
introduces or is in scope to fix). Provenance is carried transitively:
a `CounterfactualRecord` is always built from one specific `TradeRecord`
(which does carry `TradeProvenance`), and Phase 10's functions never
read or mix data across two different trades or experiments in a single
call. `tests/counterfactual/test_provenance.py` verifies that
`build_counterfactual_record`/`run_counterfactual_analysis`, when run
across a journal containing trades of more than one `TradeProvenance`,
never lets one trade's `CounterfactualRecord` reflect another trade's
data.

---

## 7. Reproducibility

No file under `src/counterfactual/` imports the `random` module or calls
`datetime.now()`/`datetime.utcnow()` internally — every timestamp
(`decision_time`, `evaluation_time`, `computed_at`) is a required or
explicitly-defaulted-`None` parameter supplied by the caller, matching
this project's standing convention (`decision.py`, `risk.py`,
`learning/*.py`, etc.). Verified by AST scan,
`tests/counterfactual/test_reproducibility.py`, mirroring Phase 9's
`test_reproducibility.py` pattern exactly.

---

## 8. Structural Boundary

`src/counterfactual/*.py` constructs no `backtest.orders.Order`, no
broker/execution object, no `risk.models.PositionSizingResult`/
`RiskCheckedPosition`, and no `learning.enums.CandidateModelStatus.
APPROVED`/`DEPLOYED`. `tests/counterfactual/test_boundary.py` verifies
this via the same `dataclasses.fields()`/`inspect.signature()`/AST-scan
reflection technique every prior phase's `test_*_boundary.py` already
uses — confirming, in particular, that `AttributionResult` and
`CounterfactualRecord` (both reused Phase 3 types) still have no
order/broker/execution-shaped field, and that no new Phase 10 code path
constructs one.

---

## 9. Lineage

`attribution_results.experiment_id` joins directly to `experiments.
experiment_id` (Phase 4's existing table) — a one-column join proves
attribution lineage, the same pattern Phase 7/8's `decision_outputs`/
`risk_assessments` already use for their own upstream joins.
`counterfactuals.trade_id` (Phase 3's existing table, unmodified) already
joins to `trades.trade_id` -> `decisions.snapshot_id` — Phase 10 adds no
new join surface for counterfactuals because it adds no new table for
them. `tests/integration/test_attribution_lineage.py` demonstrates both
joins against a live DuckDB catalog produced by a real backtest run.

---

## 10. Persistence Summary

New DuckDB objects (schema.py, additive only):

```sql
CREATE SEQUENCE IF NOT EXISTS attribution_seq START 1;
CREATE TABLE IF NOT EXISTS attribution_results (
    seq BIGINT PRIMARY KEY DEFAULT nextval('attribution_seq'),
    experiment_id TEXT NOT NULL,
    computed_at TIMESTAMP,
    payload_json TEXT NOT NULL
);
```

No existing table's schema changes. No new table is added for
`CounterfactualRecord` (reuses Phase 3's `counterfactuals` table
unchanged).

---

## 11. Test Strategy

- `tests/counterfactual/test_cash_counterfactual.py` — unit tests for
  `compute_cash_counterfactual` (zero-rate default, nonzero-rate case,
  horizon computation, ordering validation).
- `tests/counterfactual/test_counterfactual_record.py` —
  `build_counterfactual_record` assembly, `compute_counterfactual_advantage`.
- `tests/counterfactual/test_attribution.py` — `market`/`selection`
  computation, the reconciliation identity, the `market is None ->
  selection is None` case, unchanged `execution`.
- `tests/counterfactual/test_attribution_repository.py` — in-memory
  repository record/get/get_history/list_all.
- `tests/counterfactual/test_point_in_time.py` — leakage guards (section 5).
- `tests/counterfactual/test_provenance.py` — provenance isolation
  (section 6).
- `tests/counterfactual/test_reproducibility.py` — determinism, AST scan
  (section 7).
- `tests/counterfactual/test_boundary.py` — structural boundary (section 8).
- `tests/storage/test_attribution_repository.py` — DuckDB persistence,
  restart safety (reopen the same on-disk file, confirm data survives).
- `tests/integration/test_counterfactual_pipeline.py` — end-to-end: run
  a real baseline backtest, ingest into the Trade Journal, compute and
  persist counterfactuals for its trades via the *existing*
  `TradeJournalRepository.record_counterfactual`, confirm
  `build_experience_records` (Phase 3, unmodified) picks up the richer
  `alternatives` tuple automatically.
- `tests/integration/test_attribution_lineage.py` — the join described
  in section 9, against a live DuckDB catalog.

All existing Phase 1-9 tests (553) must remain passing, unmodified.

---

## 12. Definition of Done for Phase 10

- [ ] This specification and ADR-0016 written.
- [ ] `src/counterfactual/` package implemented (counterfactual.py,
      attribution.py, repository.py, pipeline.py).
- [ ] `src/storage/counterfactual_repository.py` implemented.
- [ ] `src/storage/schema.py` / `src/storage/serialization.py` — additive
      changes only, verified via `git diff | grep '^-'`.
- [ ] All new tests (section 11) written and passing.
- [ ] All 553 pre-existing tests still passing, unmodified.
- [ ] `docs/PROJECT_STATUS.md` updated.
- [ ] Git integrity re-verified on the final commit.
