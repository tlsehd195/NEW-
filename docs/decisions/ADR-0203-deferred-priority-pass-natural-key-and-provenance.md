# ADR-0203: Deferred-item priority pass -- candidate natural key & SecurityMaster/UniverseMembership provenance

**Status:** Accepted
**Date:** 2026-09-25
**Deciders:** Claude Code session (continuing ADR-0195 through ADR-0202's
external-audit response), account owner

**Related documents:** `docs/decisions/ADR-0195-external-audit-p1-fixes-2026-09-24.md`
(P1-4's original deferral), `docs/decisions/ADR-0196-external-audit-batch-a-2026-09-24.md`
(F-4's original deferral), `docs/decisions/ADR-0003-data-model.md`

## Context

After the P1/P2/P3 external-audit response (ADR-0195 through ADR-0202)
merged, the account owner asked for a fresh priority ranking of every
item still open or deliberately deferred across the whole project, not
just the audit report's own scope. Two items ranked highest (real,
already-reproduced correctness gaps sitting in the codebase today, as
opposed to items blocked on a Live entrypoint that does not exist yet
or on an external API key not yet issued) were explicitly named
"execute now": the two items each of ADR-0195 (P1-4) and ADR-0196
(F-4) had deliberately left open with the reasoning recorded but not
acted on.

## Decision

### 1. Candidate natural key now includes a trainer-hyperparameter hash (ADR-0195 P1-4's deferred half)

**Reproduction** (re-confirmed before fixing): `DuckDBCandidateModelRepository._natural_key`
was `dataset_version|trainer_version|seed|provenance`. `trainer_version`
is a fixed per-class string for most trainers, so retraining the exact
same dataset with different runtime hyperparameters (e.g.
`LinearRegressionTrainer(feature_ids=[...], ridge=X)` vs. the same
`feature_ids` with a different `ridge`) produced an identical natural
key -- `record()`'s own idempotency check silently returned the OLD
candidate and the new, genuinely different one was never persisted, no
error raised. Reproduced directly in a new test before fixing (and
re-confirmed by reverting the fix and watching the test fail with the
exact collision).

**Fix:** `CandidateModelArtifact` gained `trainer_config_version:
Optional[str] = None` -- a content hash (`data_infra.versioning.
compute_data_version`, the same primitive `learning.dataset` already
uses for `dataset_version`) of a trainer's own runtime hyperparameters,
never its learned/output values.
- `LinearRegressionTrainer` computes it once at `__init__` from
  `{feature_ids, ridge}` and passes it into every `CandidateModelArtifact`
  it produces.
- `MeanRewardBaselineTrainer` has no runtime hyperparameters --
  `trainer_config_version` stays `None`, the honest value, never a
  fabricated hash standing in for "nothing to hash."
- `TrailingWindowMeanTrainer` (`src/evolution/trainer.py`) already
  encodes its only hyperparameter (`window`) directly into
  `trainer_version` itself (`f"trailing_window_mean_trainer_v1_w{window}"`)
  -- it had no collision to begin with, so it is left unchanged, also
  `None`.

`DuckDBCandidateModelRepository._natural_key` now includes
`str(c.trainer_config_version)`. Threaded through
`storage.serialization.candidate_model_to_payload`/
`payload_to_candidate_model` for the round trip.

### 2. SecurityMaster/UniverseMembership gained an Optional Provenance (ADR-0196 F-4's deferred half)

Re-verified against ADR-0003: `Provenance` was scoped to exactly
`PriceBar`/`CorporateAction`/`BenchmarkPoint` -- not an oversight, but
also not something that should stay permanently closed once a real
writer can honestly fill it. While designing this, discovered the true
scope was larger than ADR-0196 F-4 estimated ("touches the schema, two
dataclasses, 3 real writers"): two of the three writers producing
`SecurityMaster`/`UniverseMembership` records (`data_infra.universe`'s
static `UniverseDefinition`s, `data_infra.providers.
sp500_index_constituent_history`'s CSV parse) do not track a real fetch
timestamp anywhere in the codebase -- `Provenance.retrieved_at` cannot
be honestly filled for them without fabricating a date, which this
project's own "never fabricate" discipline forbids. Raised this fork to
the account owner rather than guessing; decision: add `provenance` as
**Optional** (`Optional[Provenance] = None`), not required like its
`PriceBar`/`CorporateAction`/`BenchmarkPoint` siblings -- fill it only
where a writer has a real value, leave it honestly `None` elsewhere,
and do not touch the ~25 existing test call sites across 6 test files
and 2 production scripts that construct these dataclasses via
`valid_from=` alone.

**What got filled:**
- `data_infra.security_master_backfill.build_delisted_security_masters_from_bars`
  derives `SecurityMaster` records from real, already-ingested
  `PriceBar`s, each carrying its own real `Provenance` -- this writer
  can honestly build one: `source="derived_from_price_bars"`,
  `source_dataset` names every distinct underlying bar provider
  (comma-joined, never silently picking just one when a security's
  history spans a primary + fallback source), `source_record_id` is
  the security_id, `retrieved_at` is the caller-supplied `as_of_time`
  (a real "when this derivation ran" value, never `datetime.now()`),
  `data_version` a content hash of the derived record's own inputs.

**What stayed `None`, disclosed in each function's own docstring rather
than silently:**
- `data_infra.universe.build_universe_memberships`/`build_security_masters`
  -- neither a hand-curated `UniverseDefinition` nor
  `_SP500_PIT_CONFIRMED_LISTED_FROM` (itself sourced from
  `scripts/compute_sp500_pit_listed_from.py`'s one-time run) tracks a
  retrieval timestamp.
- `sp500_index_constituent_history.build_sp500_index_universe_memberships`
  -- `parse_ticker_intervals` reads a CSV path directly with no
  fetch-time metadata. This module's own docstring already fixes what
  `Provenance.source` must say the day this is wired
  (`"fja05680_sp500_ticker_start_end"`) -- left as a named pointer for
  whichever future session threads a real retrieval timestamp in as a
  new parameter, rather than guessing one now.

**Schema:** `security_master`/`universe_membership` DuckDB tables each
gained 6 nullable columns (`provenance_source`,
`provenance_source_dataset`, `provenance_source_record_id`,
`provenance_retrieved_at`, `provenance_data_version`,
`provenance_schema_version`) -- the same column-decomposition
convention `corporate_actions`/`benchmark_points` already use, just
nullable instead of `NOT NULL` to match the Optional field.
`storage.serialization` gained `provenance_to_row_optional`/
`row_to_provenance_optional` (None-safe wrappers around the existing
`provenance_to_row`/`row_to_provenance`), and `DuckDBDataRepository.
add_security`/`add_universe_membership` now write all 6 new columns.

## Consequences

### Positive
- Two real, previously-open correctness/traceability gaps are closed
  with genuine code + tests, not just re-documented.
- The candidate natural-key fix has an exact-same-shape verification to
  ADR-0195's original `features` fix: reverted, confirmed the new test
  fails with the real collision, restored.
- The provenance schema change is additive and backward-compatible --
  every existing caller passing no `provenance=` argument gets the
  identical `None` default and identical persisted `NULL` columns as
  before this ADR; none of the ~25 existing call sites needed to
  change.

### Negative / Trade-offs
- `SecurityMaster`/`UniverseMembership.provenance` is `Optional`, unlike
  its `PriceBar`/`CorporateAction`/`BenchmarkPoint` siblings -- a real,
  disclosed asymmetry in this project's own `Provenance` convention,
  not an oversight: forced-required would have meant either fabricating
  `retrieved_at` values this session cannot honestly source, or a much
  larger change threading a new required parameter through 2 production
  scripts and ~25 test call sites. The account owner chose the smaller,
  honest-gap-preserving option explicitly.
- Two of the three writers still produce `provenance=None` -- this ADR
  narrows but does not close ADR-0196 F-4's original traceability gap.
  Each function's own docstring now names exactly what real value is
  missing and what a future session should thread in, rather than
  leaving the gap unstated.

## Tests

`tests/learning/test_linear_trainer.py` (`TestTrainerConfigVersion`, 4
new tests), `tests/storage/test_learning_repository.py`
(`test_a_retrain_with_different_trainer_hyperparameters_is_not_silently_dropped`),
`tests/data_infra/test_security_master_backfill.py`
(`TestProvenance`, 3 new tests), `tests/storage/
test_data_repository_persistence.py`
(`test_security_master_and_universe_membership_provenance_survives_restart`).

Both the natural-key fix and the provenance round-trip fix were
verified as real regression guards before this commit: each was
temporarily reverted, the new test confirmed to fail with the exact
expected collision/loss, then restored.

Full suite run before merge as the merge gate (see PR).
