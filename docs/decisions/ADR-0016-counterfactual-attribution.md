# ADR-0016: Counterfactual Analysis / Performance Attribution

## Context

`PROJECT_MASTER_PLAN_SOURCE.md` sections 33-34 call for Counterfactual
Analysis (compare the selected action's realized outcome against
alternatives it did not take) and Performance Attribution (decompose
realized return into market/sector/factor/selection/timing/execution).
Phase 3 (`docs/specifications/PHASE-3-trade-journal.md` sections 5.6,
5.7, 7) already defined the data model for both
(`trade_journal.models.AlternativeOutcome`, `CounterfactualRecord`,
`AttributionResult`) and implemented exactly the one component each that
Phase 3's own data could honestly compute: the HOLD counterfactual
(`compute_hold_counterfactual`) and the `execution` attribution component
(`compute_execution_attribution`). Everything else was left `None`,
explicitly reserved for phases that did not exist yet.

Phase 9 (Learning Engine) is now complete. Phases 5-8 (Regime, Prediction,
Decision, Position Sizing/Risk) have all shipped, each already persisted
in the same DuckDB catalog. Per the session handoff, Phase 10 is
"Counterfactual / Attribution" — closing out as much of Phase 3's
reserved-field list as can now be filled in *honestly*, without
estimating a number the system cannot actually derive.

## Decision

### 1. Reuse Phase 3's `AlternativeOutcome` / `CounterfactualRecord` /
   `AttributionResult` types verbatim — no parallel Phase 10 types

Unlike Phase 9's `LearningExperimentRecord` (which genuinely didn't fit
`backtest.experiment.ExperimentRecord`'s shape and needed a new type),
Phase 3's three types here are *already* exactly shaped as forward-looking
placeholders for this phase — every reserved field's docstring says which
future phase would fill it in, and that phase has now arrived. Defining
new, parallel types would fragment the Trade Journal / Experience Dataset
pipeline that already consumes these exact types
(`trade_journal.experience.build_experience_records` already reads
`CounterfactualRecord.alternatives`). Phase 10 imports and populates them,
touching zero lines in `trade_journal/models.py`.

### 2. `CounterfactualRecord` persistence is not reimplemented

`TradeJournalRepository.record_counterfactual`/`get_counterfactual`
(in-memory and DuckDB, both from Phase 3) already accept and round-trip
an arbitrary-length tuple of `AlternativeOutcome`s via
`storage.serialization.counterfactual_to_payload`/
`payload_to_counterfactual` — verified by reading the existing
implementation before writing any new code. Only `AttributionResult` gets
a new repository (`counterfactual.repository.AttributionRepository` +
`storage.counterfactual_repository.DuckDBAttributionRepository`), because
only `AttributionResult` has never had one.

### 3. CASH counterfactual defaults to the system's existing zero-rate
   assumption, not a new one

Every `risk_free_rate` parameter already in this codebase
(`backtest.metrics.sharpe_ratio`, `sortino_ratio`) defaults to `0.0` and
nothing overrides it anywhere in the current system. Introducing a
different default for the CASH counterfactual (e.g. inventing a
"typical" risk-free rate) would be exactly the kind of estimated-value-
presented-as-fact this project's stated principle forbids. Phase 10 keeps
`risk_free_rate=0.0` as the default and accepts an explicit override
(never fetched from any data source that does not exist), consistent with
existing precedent rather than inventing a new one.

### 4. `market` attribution is `PerformanceReport.benchmark_cumulative_return`
   verbatim — no new benchmark computation

Phase 2's `BenchmarkEngine`/`compute_performance_report` already compute
and persist this figure per experiment. Recomputing it independently in
Phase 10 would risk drifting from the number `ExperimentRepository`
already stores, and would inherit the still-open
`PRICE_RETURN`/`TOTAL_RETURN` `DECISION REQUIRED` (Phase 2 spec section
9.3) a second time in a second place. Reading the existing field is both
simpler and strictly safer.

### 5. `selection` is defined as an exact residual, not estimated

`selection := cumulative_return - market - execution`. This is not a
model of "stock-picking skill" in the academic-attribution sense — it is
whatever part of the realized return isn't explained by passive market
exposure or the (already-established) execution cost drag, and it is
explicitly documented as a **combined selection-and-timing** residual
rather than pure selection. The alternative — attempting a full
Brinson-Fachler-style decomposition to split `selection` from `timing` —
was considered and rejected for this phase (see Alternatives Considered,
item 2): it requires a time-varying-weight-vs-benchmark model this system
does not yet have validated, and a wrong-but-plausible-looking number is
worse than an honestly-labeled residual. The residual construction
guarantees an exact, testable identity
(`market + selection + execution == cumulative_return`), which a modeled
`timing` split would not necessarily preserve without additional
reconciliation work.

### 6. `timing`, `sector`, `factor` remain `None`, reserved — this phase
   does not force them to a value

`sector`/`factor`: unchanged from Phase 3/8 — `SecurityMaster` still has
no sector/factor fields, so there is nothing to attribute to. `timing`:
see item 5 — deferred, not fabricated.

### 7. `alternative_action_1`/`alternative_action_2` remain out of scope,
   deferred to Phase 11 (Model Evolution)

Phase 3 section 7.2 already reasoned that comparing the selected action
against a different model's or strategy's hypothetical decision requires
that alternative to "actually exist and be runnable," and assigned this
to Phase 11. That framing is preserved even though Phase 6-9 now give the
system multiple `Predictor` implementations and a working
`DecisionAgent`: orchestrating a full alternate decision pipeline over
the same historical window and registering/tracking that as a comparable
"candidate decision process" is precisely what "Model Evolution" as a
named phase is for. Implementing it piecemeal inside Phase 10 would
both duplicate work Phase 11 is meant to own and pre-empt design
decisions (how an alternate model run is versioned/registered) that
belong there.

### 8. Zero new `AsOfDataView`/`DataRepository` call sites

CASH needs no data query; HOLD reuses Phase 3's existing, already-audited
call unchanged; `build_attribution_result` reads only already-computed
`ExperimentRecord` fields. This phase adds no new leakage *surface* at
all, rather than adding a new guarded call site and re-proving it safe.

## Alternatives Considered

1. **Give `AttributionResult` a `provenance` field.** Rejected:
   `ExperimentRecord` itself (Phase 2/4) has no `provenance` field, so
   adding one only to `AttributionResult` would create an inconsistency
   between a record and the experiment it describes, and would require
   touching Phase 3's frozen `AttributionResult` dataclass for a gap that
   predates Phase 10 and is not required for this phase's own
   correctness (section 6 of the spec documents how provenance is still
   carried transitively).
2. **Implement a full Brinson-Fachler `timing`/`selection` split now**,
   using `PositionSizingResult.proposed_target_weight` time series
   against `BenchmarkResult.value_series`. Rejected for this phase: the
   raw ingredients exist, but validating a weight-based attribution model
   correctly (period alignment, cash-drag handling, multi-position
   portfolios where Phase 8's own Known Issue already documents an
   `average_cost` proxy limitation) is a substantially larger, separate
   piece of work with real risk of a subtly-wrong-but-confident number.
   The exact-residual `selection` (decision 5) delivers the master plan's
   actual goal — "AI가 실제로 alpha를 만들어냈는지 분석한다" — honestly,
   today, without that risk. A future phase can subtract a properly
   validated `timing` out of this residual without changing its meaning.
3. **New Phase 10-only types instead of reusing Phase 3's.** Rejected —
   see decision 1.
4. **A new `counterfactual_records` table**, independent of Phase 3's
   `counterfactuals` table. Rejected — Phase 3's table and serialization
   already handle an arbitrary-length `alternatives` tuple; a second
   table would fragment counterfactual history across two places for no
   benefit.

## Consequences

### Positive

- Zero modifications to Phase 1-9 source files; `git diff | grep '^-'`
  on `src/storage/schema.py` and `src/storage/serialization.py` shows no
  deleted/changed lines, only additions.
- `CounterfactualRecord`s produced by Phase 10 flow into the Learning
  Engine's Experience Dataset with no code change to `trade_journal/` or
  `learning/` — `build_experience_records` already wires this up.
- The `market + selection + execution == cumulative_return` identity is
  a strong, directly-testable correctness property — a bug here fails a
  test immediately rather than silently producing a plausible-looking
  wrong number.
- No new leakage surface — nothing new to re-audit for point-in-time
  safety beyond what Phase 2/3 already established.

### Negative / Trade-offs

- `selection` conflates stock-selection and timing skill; a caller who
  reads it as pure selection skill will be misled unless they also read
  the field's documentation. Mitigated by explicit docstrings/spec
  language calling it a "combined residual" rather than "selection".
- `alternative_action_1`/`alternative_action_2` and `timing` remain
  unimplemented; Master Plan section 33/34's full vision is only
  partially delivered this phase. This is a deliberate, documented scope
  boundary (decisions 6-7), not an oversight.
- `AttributionResult`'s append/latest-wins persistence (mirroring
  `PostTradeAnalysis`/`CounterfactualRecord`) means recomputing
  attribution for the same experiment after new logic ships creates a
  new row rather than updating in place — consistent with existing
  precedent, but callers wanting "the one true value" must always go
  through `get()` (latest), never assume `list_all()` has no duplicates
  per `experiment_id`.

## Status of Implementation at Time of This ADR

Implemented alongside this document: `src/counterfactual/` package,
`src/storage/counterfactual_repository.py`, additive `schema.py`/
`serialization.py` changes, and the full test suite described in Phase
10 spec section 11.
