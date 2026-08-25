# ADR-0015: Learning Engine Architecture

**Status:** Accepted
**Date:** 2026-08-25
**Deciders:** Claude Code (Phase 9 session), pending project owner review
**Related documents:** `PROJECT_MASTER_PLAN.md` §10.7, §11, §1.5, ADR-0009
(Trade Journal data model), ADR-0010 (persistent storage backend),
ADR-0014 (position sizing + portfolio risk engine),
`docs/specifications/PHASE-9-learning-engine.md`

---

## Context

`PROJECT_MASTER_PLAN.md` §11.1 defines the Learning Engine pipeline:
`Experience → Data Cleaning → Labeling → Training Dataset → Candidate
Training → Evaluation`, with §11.2's Candidate Model state machine
(`CANDIDATE → BACKTESTED → VALIDATED → OOS_TESTED → PAPER_TESTED →
APPROVED → DEPLOYED`) and §1.5/§11.5's constitutional guarantee that a
learning result never auto-applies to Live. Phase 9 builds the first
five pipeline stages, ending at `CANDIDATE` only. This ADR records the
structural choices made to keep that guarantee real rather than merely
documented, and the reuse-vs-new-type decisions made against Phase 3/4's
existing `ExperienceRecord`/`ExperimentRepository`.

## Decision

### 1. `LearningExperimentRecord` is a new type, not a reuse of `backtest.experiment.ExperimentRecord`

The instruction requires reusing an existing Experiment system rather
than duplicating one. `backtest.experiment.ExperimentRecord` was
examined first: it is tightly shaped around a *backtest run*
(`transaction_cost_config`, `slippage_config`, `benchmark`, and a
`metrics: PerformanceReport` field requiring `cumulative_return`/`cagr`/
`sharpe_ratio`/etc.). A training run has none of those concepts and a
genuinely different shape (`dataset_id`, `trainer_version`,
`evaluator_version`, split-based metrics). Reusing the type would force
either fabricating backtest-shaped fields for something that never ran
a backtest (the exact "fabricated precision" failure mode ADR-0009 §4
already rejects) or loosening `ExperimentRecord`'s own fields to
`Optional` for every phase, weakening a type eight phases of tests
already depend on. `LearningExperimentRecord` is instead a new,
purpose-built type -- but it reuses the *pattern*
`storage.experiment_repository` already established (one DuckDB
catalog, an id-allocating tracker, natural-key idempotency) rather than
inventing a new persistence architecture. This mirrors the identical
"reuse an existing type when it genuinely fits, define a new one when
the shape is genuinely different" discipline `risk.models.
PositionSizingResult`/`RiskCheckedPosition` already applied against
`decision.models.DecisionOutput` (ADR-0014).

### 2. `CandidateModelStatus` reserves the full master-plan state machine, but this phase's code can only ever produce `CANDIDATE`

All seven states (`CANDIDATE`/`BACKTESTED`/`VALIDATED`/`OOS_TESTED`/
`PAPER_TESTED`/`APPROVED`/`DEPLOYED`) are defined now, the same
"reserve ahead of the first producer" pattern `trade_journal.enums.
DecisionAction.HOLD/EXIT/NO_TRADE` (Phase 3, populated Phase 7) and
`backtest.enums.OrderStatus.CANCELLED` already established. Structural,
not just documented, enforcement: `learning.trainer.
MeanRewardBaselineTrainer.train()` is the only code path that
constructs a `CandidateModelArtifact`, and it hardcodes
`CandidateModelStatus.CANDIDATE` -- no parameter, branch, or config
value can make it emit `APPROVED`/`DEPLOYED`
(`tests/learning/test_learning_boundary.py` verifies this both by
exercising the trainer and by an AST scan of every file in
`learning/*.py` confirming neither enum member is referenced anywhere
except its own definition in `enums.py`).

### 3. `TrainingDatasetConfig.provenance` (via `build_training_dataset`'s `provenance` parameter) has no default -- mixing is structurally, not just conventionally, prevented

Every other Learning Engine config (`DataCleaningConfig`, `LabelConfig`,
`SplitConfig`, `SamplingConfig`) has an illustrative default value;
`provenance` deliberately does not, on `build_training_dataset` itself.
A caller must always name exactly one `TradeProvenance` category, and
`DataCleaner` then marks any input record whose provenance does not
match that declared category as `INVALID` -- `provenance_mismatch` --
never silently included. This is the identical "no default that could
silently mix categories" choice `decision.models.DecisionOutput.
provenance` already defaults *to* a single named value rather than
`None`-meaning-any, applied here as "no default at all" because Phase 9
specifically must never let two provenance categories blend into one
dataset (instruction section 6).

### 4. `as_of_cutoff` filtering happens before Data Cleaning ever sees a record, mirroring `AsOfDataView`'s "future data simply does not exist" discipline

`dataset.py::_filter_by_cutoff` drops any experience whose resolved
decision time is after `as_of_cutoff` *before* handing the remaining
records to `DataCleaner`. This is not the same code as `backtest.asof.
AsOfDataView` (Experience Dataset construction is a different data
source, at a different point in the pipeline, so no existing guard
could be literally reused) but is the identical discipline applied one
layer further: a future-dated experience is treated as if it does not
exist yet for a dataset built at an earlier cutoff, not merely filtered
out of the final result after being examined. `tests/learning/
test_learning_point_in_time.py` verifies rebuilding a dataset at a fixed
cutoff, after new, later experiences are added to the journal, produces
a byte-for-byte identical `TrainingDataset` (including `dataset_version`).

### 5. `dataset_version` hashes actual sample content, not just `source_experience_ids`

**Self-discovered bug, fixed before this ADR was written**: an initial
implementation computed `dataset_version` from `source_experience_ids` +
configuration alone. `trade_journal.experience.build_experience_records`
already documents `experience_id`/`TradeRecord.trade_id` as scoped to a
single `TradeJournalRepository` instance's own id sequence (the same
scoping `storage.experience_repository.DuckDBExperienceRepository`'s
own docstring explains, Phase 4's "Known correctness fix" for
`experience_id` dedup). Two independently-built journals (e.g. two
separate backtest runs) therefore legitimately produce colliding
`TRD-000001`..`TRD-000010` ids for entirely different trades on
different dates -- and a version hash built only from those ids
collided too, even though the actual sample content (label values,
timestamps) differed. Fixed by hashing a sorted
`(trade_id, label_value, sample_as_of_time)` fingerprint of the actual
labeled samples alongside the id list and configuration --
`data_infra.versioning.compute_data_version`'s own contract ("any real
content change must produce a different [version]", ADR-0003) is now
actually satisfied, not just approximately satisfied.
`tests/integration/test_learning_pipeline.py::
test_two_independent_pipeline_runs_do_not_collide_in_storage` is the
regression test.

### 6. Storage-layer ids are allocated by DuckDB sequences, never trusted from the caller's in-process allocator

**Second self-discovered bug, fixed before this ADR was written**: the
identical scoping problem in decision 5 also breaks primary-key
uniqueness -- `DatasetIdAllocator`/`MeanRewardBaselineTrainer`/
`Evaluator`/`LearningExperimentTracker` are all fresh, per-call
in-process counters restarting at `"...-000001"`, so two independent
pipeline runs' `TrainingDataset.dataset_id`/`CandidateModelArtifact.
candidate_id`/etc. collide even after decision 5's content-hash fix
made their *natural keys* (`dataset_version`, etc.) correctly distinct.
Fixed by applying the exact precedent `storage.experience_repository.
DuckDBExperienceRepository` already set for `experience_id`: each of
the four `storage.learning_repository.DuckDB*Repository.record()`
methods allocates a fresh, storage-level id from a dedicated DuckDB
sequence (`training_dataset_id_seq`, `candidate_model_id_seq`,
`evaluation_id_seq`, `learning_experiment_id_seq`) for a genuinely new
row, only after its natural-key dedup check has already confirmed the
row doesn't exist -- the caller-supplied in-process id is always
discarded on the write path. `DuckDBLearningExperimentRepository` also
gained a `natural_key` column (`dataset_version` + `candidate_id` +
`evaluation_id`), replacing its initial (equally id-scoping-vulnerable)
dedup-by-`experiment_id`.

### 7. Label source: `TradeRecord.realized_return`, never a newly-computed forward return

Per instruction section 8's "실제 프로젝트 목표와 기존 데이터로 검증
가능한 최소 label부터 구현한다," the only label this phase implements
is the trade's own already-realized outcome -- no new price-data-driven
forward-return calculation, which would both duplicate logic
`backtest.metrics`/`trade_journal.analysis` already own and introduce a
fresh leakage surface this phase has no need to open.
`label_horizon` is honestly `None` (the horizon is each trade's own
variable `holding_period`, not a fixed N-day window) rather than a
fabricated constant.

### 8. Chronological, non-random train/validation/test split; no Purged K-Fold/Embargo yet

`build_training_dataset` sorts labeled samples by `sample_as_of_time`
and slices train/validation/test as contiguous, chronologically
non-overlapping ranges -- `tests/learning/test_learning_point_in_time.py::
TestTemporalSplitIntegrity` verifies no train sample is chronologically
after any test sample and no `trade_id` appears in more than one split.
Per instruction section 10, full Purged K-Fold/Embargo is explicitly
deferred to a later Validation-focused phase (`PROJECT_MASTER_PLAN.md`
§13.5) -- this phase's split only needs to not leak, not to implement
the full validation protocol.

## Alternatives Considered

- **Reusing `backtest.experiment.ExperimentRecord` for training runs**:
  Rejected -- see decision 1.
- **Letting `provenance` default to `None` meaning "all provenances"**
  on `build_training_dataset`: Rejected -- see decision 3; would make
  provenance mixing the easy/default path instead of an explicit,
  deliberate choice, precisely what instruction section 6 forbids.
- **Persisting every intermediate `CleaningResult`/`LabeledSample` row
  into new DuckDB tables**: Rejected -- both are pure, deterministic,
  recomputable functions of (Experience Dataset state, `as_of_cutoff`,
  configuration); persisting them would duplicate `experience_records`
  data already in the catalog for no addressable benefit beyond what
  `TrainingDataset`'s own metadata (`sample_count`, `excluded_count`,
  `splits`, `source_experience_ids`) already provides for audit and
  reproducibility.
- **A single "always predict 0.0" trainer instead of the mean-reward
  baseline**: Rejected -- a mean predictor is the actual null hypothesis
  for a regression-shaped label (minimizes squared error on its own
  training data), giving `Evaluator`'s baseline-comparison output an
  actually informative contrast point rather than two equivalent
  trivial predictors.

## Consequences

### Positive

- Zero new leakage-guard code duplicating `AsOfDataView` -- the
  `as_of_cutoff` discipline (decision 4) is Experience-Dataset-specific
  but follows the identical reasoning.
- `TrainingDataset`/`CandidateModelArtifact`/`EvaluationResult`/
  `LearningExperimentRecord` give Phase 10 (Counterfactual/Attribution)
  and Phase 11 (Model Evolution/Registry) concrete, already-tested types
  to extend -- in particular `CandidateModelStatus`'s reserved states
  are ready for Phase 10/11 to assign, without a schema change.
- Both self-discovered bugs (decisions 5, 6) are fixed using this
  project's own established precedent (content-hash correctness,
  storage-allocated ids) rather than a novel mechanism, keeping the
  fix auditable against prior phases' reasoning.

### Negative / Trade-offs

- `MeanRewardBaselineTrainer` is intentionally not a real model -- no
  claim of predictive value, exactly like `predict.predictor.
  RandomWalkPredictor` before it. A real trainer is future work, behind
  the same `CandidateTrainer` Protocol seam.
- `EvaluationResult`'s `baseline_metrics` is computed only over the TEST
  split; `Evaluator` does not yet implement PBO/Deflated Sharpe/
  Walk-Forward validation (explicitly deferred, instruction section 13).
- No sector/factor-style richer state features are used in labeling or
  cleaning -- Data Cleaning and Labeling operate only on what
  `ExperienceRecord`/`TradeRecord`/`DecisionSnapshot` already expose
  (an inherited, not introduced, limitation).

## Status of Implementation at Time of This ADR

Implemented in `src/learning/` (`enums.py`, `config.py`, `models.py`,
`cleaning.py`, `labeling.py`, `dataset.py`, `trainer.py`,
`evaluation.py`, `experiment.py`, `repository.py`, `pipeline.py`) and
`src/storage/learning_repository.py` (+ `storage/schema.py`,
`storage/serialization.py` additions). Exercised by `tests/learning/`,
`tests/storage/test_learning_repository.py`, and
`tests/integration/test_learning_pipeline.py`.
