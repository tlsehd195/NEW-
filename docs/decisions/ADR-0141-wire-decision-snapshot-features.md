# ADR-0141: Wire Real `DecisionSnapshot.features` So `LinearRegressionTrainer` Gets Real Samples

**Status:** Accepted
**Date:** 2026-09-17
**Deciders:** Claude Code (session continued), pending project owner review
**Related documents:** `docs/decisions/ADR-0048` (originally documented
this gap for `OrderIntent.features`/backtest `Strategy`),
`scripts/run_learning_cycle.py` (the read side, unmodified -- its own
module docstring's "honest current limitation" is what this ADR closes)

---

## Context

One of the account owner's own quoted questions this session, verbatim
from an uploaded evaluation report: `MeanRewardBaselineTrainer`/
`LinearRegressionTrainer` have "0 real training samples since no
strategy logs features." Investigating confirmed this precisely:
`scripts/run_learning_cycle.py`'s own module docstring already
disclosed it honestly ("no Strategy/DecisionAgent in this codebase
sets `OrderIntent.features` yet"), and a direct read of `orchestration.
paper_runner.run_cycle`'s own `trade_journal_repository.record_decision(...)`
call confirmed it never passed a `features=` argument at all.

Tracing the full chain end to end (rather than assuming) found every
other link already correct and waiting: `DecisionSnapshot.features`
(a real field), `storage.trade_journal_repository`'s `record_decision`/
serialization (`features` already round-trips through `payload_json`),
`trade_journal.experience.build_experience_records` (already copies
`decision.features` into `ExperienceRecord.state["features"]`, per its
own comment referencing this exact gap), `learning.labeling.Labeler`
(already copies `record.state.get("features")` into `LabeledSample.
features`), and `scripts/run_learning_cycle.py`'s own `--feature-id`
flag (already fully wired to `LinearRegressionTrainer(feature_ids=...)`).
The ENTIRE read side was already correct -- the gap was exactly one
write-site call, never populating the one field everything downstream
was already built to consume.

## Decision -- a new `_prediction_features()` helper, real values only, `None` never fabricated as a value

Added `orchestration.paper_runner._prediction_features(prediction:
PredictionOutput) -> Optional[dict]`, called once per security per
cycle, passed as `features=` to the existing `record_decision(...)`
call. Reuses five already-computed `PredictionOutput` fields
(`expected_return`, `probability`, `expected_volatility`, `uncertainty`,
`confidence`) -- the exact five concepts `PROJECT_MASTER_PLAN.md`
section 8.1 itself names, no new computation, no new data source.

Each field is individually `Optional[float]` on `PredictionOutput`
itself -- a `None` value is OMITTED from the dict entirely, never
written as `"key": None`. Confirmed why this matters, not merely
guessed: `LinearRegressionTrainer._samples_with_required_features`
checks KEY PRESENCE only (`required <= set(s.features)`), so a
present-but-`None` value would pass that check and then crash
`LinearRegressionModel.fit`'s own arithmetic on that "eligible" sample.
Omitting the key instead makes that sample correctly excluded for
genuinely lacking the feature -- the same "never leave a landmine for
downstream arithmetic" discipline this codebase already applies
elsewhere. Returns `None` (not `{}`) when every field is `None`, so
`DecisionSnapshot.features` stays a real "no features available"
rather than an empty-but-present dict reading differently downstream.

## Consequences

### Positive

- `LinearRegressionTrainer` can now actually fit against real Paper
  Trading data once enough real closed trades accumulate -- verified
  directly: a real closing SELL's own `DecisionSnapshot.features`
  now contains real `expected_return`/`confidence` values matching
  that cycle's own `PredictionOutput`, not asserted only in prose.
- No existing fixture in this repository's own test suite happens to
  have enough real closed trades to reach a real `fitted=True` result
  yet (the largest existing fixture, `TestFullLoopWithARealClosedTrade`,
  produces exactly one usable TRAIN sample -- itself insufficient for
  a real OLS fit, an honest, unrelated limitation of that fixture's
  own size, not of this fix) -- a larger multi-round-trip fixture that
  reaches `fitted=True` is a natural next step for a future session,
  not fabricated here to make a nicer-looking test.

### Negative / Trade-offs

- Only the five `PredictionOutput` fields are wired as features --
  regime axis observations (categorical, e.g. `LiquidityState`) are
  not encoded into numeric features here; doing so would need a real
  encoding scheme this ADR does not design, left for a future session.
- Backtest's own `Strategy`/`OrderIntent.features` path (ADR-0048's
  original context) remains unfixed -- this ADR is Paper Trading's
  `run_cycle` only, a different execution path.

## Tests

`tests/orchestration/test_paper_runner.py::TestDecisionSnapshotFeatures`
(3 new tests: real prediction fields reach a real `DecisionSnapshot`
via `run_cycle`, a `None`-valued field is omitted rather than written
as `None`, all-`None` fields return `None` not `{}`).
`tests/orchestration/test_run_learning_cycle_cli.py::
TestFullLoopWithARealClosedTrade` gained a direct assertion that the
real closing SELL's own `DecisionSnapshot.features` is now populated
end to end through the full CLI. The pre-existing `test_linear_
regression_against_real_data_honestly_reports_unfitted` test's
docstring and `--feature-id` value were corrected (it now uses a real
feature name, `expected_return`) -- its `fitted=False` outcome is
unchanged, but for the fixture's own genuinely-zero-TRAIN-samples
reason, not a missing-features reason that no longer applies. Full
suite re-run clean after these changes.

## Status of Implementation at Time of This ADR

Code and tests complete and committed. A fixture large enough to
reach a real `fitted=True` end-to-end result is left for a future
session, per Consequences above.
