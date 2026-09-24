# ADR-0195: External audit (2026-09-24) — P1 findings, independently re-verified and fixed

**Status:** Accepted
**Date:** 2026-09-24
**Deciders:** Claude Code (session continued), account owner (asked for each
finding to be independently re-verified before acting, in order, one at a
time — "제가 먼저 하나씩 직접 재검증")

## Context

The account owner shared an externally-produced, 13-stage independent audit
report of this repository at commit `76ab684`. Per this session's own
established discipline (and the very first item this same audit surfaced —
see the CLAUDE.md correction landed just before this ADR, retracting an
earlier session's own git-forensics error), no claim in an external document
is acted on without independent verification against this repository's own
code and a real, runnable reproduction. Every one of the 5 P1 findings below
was independently reproduced in this session (not merely read and trusted)
before any fix was written, and the account owner explicitly asked for this
one-at-a-time verify-then-fix order rather than a bulk pass.

No P0 finding was reported, and none was found on re-verification.

## Decision — each P1 finding, its independent reproduction, and its fix

### P1-1: `backtest.contribution.compute_contribution_report_from_fills` silently desynchronized from the real engine on a stock split

**Reproduction**: `PortfolioAccounting.apply_fill(buy) -> apply_split(2.0)
-> apply_fill(sell)` (the real engine's own path) produces
`realized_pnl=200.0` for buy 100sh@10 -> 2:1 split -> sell 200sh@6 (this
fixture's own zero-commission convention). The pre-fix replay function,
given only the two `Fill`s (no corporate-action replay at all), produced
`-800.0` — sign-flipped and wrong by 1000, since it applied the sell's real
200-share quantity against a position the replay never split-adjusted.

**Fix**: `compute_contribution_report_from_fills` gained a new required
`corporate_actions` parameter. Every action is now replayed in chronological
order (`effective_time or event_time`, merged against each fill's
`execution_time`) via the same `backtest.corporate_actions.
CorporateActionApplier` the real engine uses — actions with no orderable
timestamp are skipped, never guessed. The one real caller
(`scripts/run_long_horizon_validation.py`) now fetches the real corporate
actions covering the held-out TEST window from the repository before calling
it. `corporate_actions` has no default — an omission must be an explicit,
visible `()`, not a silent gap.

**Tests**: `tests/backtest/test_contribution.py`, new
`TestFromFillsCorporateActionReplay` class (split-matches-engine,
pre-fix-reproduction pinned as a permanent regression test, dividend
replay, split-after-last-fill, unorderable-action-is-skipped).

### P1-2: Integrity-ERROR/CRITICAL folds silently counted toward every candidate's aggregate, PBO, DSR, and evidence level

**Reproduction**: `strategy_research.walk_forward_evaluation.
_aggregate` (renamed target of the fix) computed every statistic —
`fold_count`, `positive_net_return_folds`, median/stdev/worst/best,
`regime_breakdown` — from `folds` unconditionally, with no
`is_valid_performance` check anywhere in `strategy_research`. Confirmed by
`grep`: the only consumer of `BacktestResult.is_valid_performance` in the
whole codebase was `src/baseline/report.py`. Separately,
`scripts/run_long_horizon_validation.py`'s own PBO/DSR computation read
`agg.folds` directly, same gap.

**Fix**: `WalkForwardAggregate` gained `total_fold_count`/
`excluded_integrity_invalid_fold_count` (new, explicit fields);
`fold_count` and every derived statistic now count ONLY folds where
`fold.result.net.is_valid_performance` is true (`_is_valid_fold`); `folds`
itself still holds every fold run, valid or not, for transparency —
`worst_fold_index`/`best_fold_index` now reference each fold's own stable
`fold_index`, not a position that would be ambiguous once the tuple holds
excluded folds too. `run_long_horizon_validation.py`'s PBO/DSR computation,
and the standalone `scripts/compute_pbo_dsr_from_report.py`, both now
filter to fold indices valid **for every candidate being compared**
(the intersection, not each candidate's own independent valid set) —
`pbo_dsr.py`'s own CSCV algorithm requires every candidate's fold-return
list to be the same length, in the same fold order (position *i* means the
same time window for every candidate); filtering per-candidate
independently would desynchronize that positional correspondence the
moment two candidates disagree about which folds are integrity-invalid.
`_fold_dict` (the JSON report writer) now also surfaces each fold's own
`is_valid_performance`.

**Tests**: `tests/strategy_research/test_walk_forward_evaluation.py`, new
`TestIntegrityInvalidFoldsExcludedFromAggregate` class (one CRITICAL fold
excluded from every statistic via `dataclasses.replace` on a real
`GrossNetResult`'s integrity report, and the all-folds-invalid empty-
aggregate case). `tests/strategy_research/
test_compute_pbo_dsr_from_report_cli.py`, two new tests (a poisoned-fold
exclusion check, and the fold-alignment case: two candidates with
*different, disjoint* invalid fold indices must not raise and must still
compare correctly).

### P1-3: `broker.paper.us_longterm_runner.run_buy_and_hold_paper_session` bypassed the real risk engine with a hardcoded `status=PASS`

**Reproduction**: the function constructed `risk.models.RiskCheckedPosition`
directly with `status=RiskCheckStatus.PASS`, synthetic
`RISK-BAH`/`SIZE-BAH`/`DEC-BAH` ids, and `risk_state=None` — no single-
position weight, sector weight, gross exposure, minimum-cash, or
max-order-notional limit was ever evaluated for this strategy, the only
registered `PaperStrategyKind` where that was true. Confirmed this is a
real, scheduled production path: `scripts/
run_multi_strategy_paper_trading_cycle.py` calls it, and builds a real
`RiskConfig` from CLI flags that it passed to the `RUN_CYCLE` strategy path
but never to this one.

**Fix, and the architectural correction mid-fix**: the first fix attempt
called `risk.engine.PortfolioRiskEngine.assess` directly from inside
`broker/paper/us_longterm_runner.py` — importing `risk.engine` and
`trade_journal.enums.DecisionAction` there. Running the full suite caught
this immediately: `tests/broker/test_broker_boundary.py` enforces, for
real, exactly the "Broker layer never calls Decision/PositionSizer/
RiskEngine directly" boundary this module's own docstring already claimed
to respect. The corrected design: `run_buy_and_hold_paper_session` now
takes a `risk_check: RiskCheckCallback` — a plain
`Callable[[security_id, as_of_time, target_weight, target_quantity,
portfolio_state], RiskCheckedPosition]` — and never imports `risk.engine`/
`risk.sizing`/`decision.*`/`DecisionAction` itself. The real
`PositionSizingResult` construction (with `decision_action=DecisionAction.
BUY`, required for the engine's hard limits to apply at all) and the real
`risk_engine.assess` call now live in a new
`orchestration.paper_runner.build_buy_and_hold_risk_check` — orchestration
already legitimately imports both, the same as `run_cycle` already does via
its own sizer. The running portfolio state fed to the risk check is built
locally, per symbol, from each symbol already allocated earlier in the same
call (this function's own bar-priced `average_cost`/`market_value` — no new
data source, since this strategy's first allocation, by construction, never
has pre-existing positions).

**Consequence for existing tests**: `RiskConfig`'s own default
`max_position_weight` (0.10) is tuned for a diversified RUN_CYCLE
strategy — real buy_and_hold usage (PILOT_UNIVERSE/RESEARCH_UNIVERSE, 15-87
symbols) never approaches it, but this project's own small unit-test
fixtures (1-3 symbols) legitimately allocate more per symbol. Existing
tests were updated to use an explicit permissive `RiskConfig` (documented
why), isolating the allocation-logic tests from the new, separate
limit-enforcement tests.

**Tests**: `tests/broker/paper/test_us_longterm_runner.py`, new
`TestRiskEngineLimitsActuallyApply` class (max_position_weight clamps a
single-symbol allocation, a near-zero gross-exposure budget rejects every
symbol, minimum_cash_ratio leaves the configured buffer untouched) — all
against a REAL, strict `DeterministicPortfolioRiskEngine`, not a stub.
Existing tests in this file and `tests/integration/
test_us_longterm_paper_trading_lineage.py` updated to pass an explicit
permissive risk check. `tests/broker/test_broker_boundary.py` and
`tests/broker/paper/test_paper_boundary.py` re-run clean (the two tests
that caught the first, architecturally-wrong fix attempt).

### P1-4: `learning.dataset`'s `dataset_version` fingerprint excluded `features`, letting a retrain with different features silently overwrite-as-same

**Reproduction**: `sample_fingerprint` hashed only `(trade_id, label_value,
sample_as_of_time)` per sample — `LabeledSample.features` (a real,
populated field, "copied from ExperienceRecord.state['features']") was
never part of `dataset_version` at all. Confirmed the real consequence:
`storage.learning_repository.DuckDBCandidateModelRepository._natural_key`
= `dataset_version|trainer_version|seed|provenance`, and `record()`'s own
idempotency check (`if existing is not None: return <the OLD one>`) means a
retrain of the SAME closed trades with a DIFFERENT feature set — a real,
common event, since feature engineering changes far more often than the
underlying labeled trades — collides on an unchanged `dataset_version` and
silently returns the old candidate, with the new one never persisted and no
error raised anywhere. Reproduced directly in
`tests/storage/test_learning_repository.py`'s new test: two full
`run_learning_pipeline` calls differing only in `features_fn`, recorded
into the same repository, before the fix would leave exactly 1 candidate.

**Fix**: `sample_fingerprint` now hashes `(trade_id, label_value,
sample_as_of_time, feature_version, features)` per sample —
`features` (an `Optional[dict]`) is serialized to a canonical
(sorted-key) JSON string first, since the fingerprint list is sorted and
Python dicts are not orderable.

**Deliberately not fixed here (scoped out, flagged for a future ADR if
pursued)**: the audit's own fix recommendation also named "trainer
parameter hash in the candidate natural key." Investigated: `learning.
linear_trainer.LinearRegressionTrainer` takes real runtime hyperparameters
(`feature_ids`, `ridge`) that are not reflected in `trainer_version`
(a fixed per-class string) or anywhere else on `CandidateModelArtifact` —
a real, plausible, independent gap of the same shape. Not fixed in this
ADR because closing it would need a new field on `CandidateModelArtifact`
(there is currently nowhere to put a trainer-hyperparameter hash) and a
ripple through the `Trainer` Protocol/serialization/every constructor call
site — a real feature addition, not a same-shape same-scope fix, and this
session did not independently reproduce it as an ACTIVE collision the way
the `features` gap was reproduced. Left as an open, named gap rather than
silently ignored.

**Tests**: `tests/learning/test_dataset.py`,
`TestReproducibleVersioning` gained two tests (different features on the
same trades produce a different `dataset_version`; no features at all —
`MeanRewardBaselineTrainer`'s own real current usage — still reproduces
identically). `tests/storage/test_learning_repository.py`, new
`test_a_retrain_with_different_features_is_not_silently_dropped` —
the exact repository-level collision, closed.

### P1-5: `ingest_insider_transactions_full.yml`'s own durable-Release-publish step (added earlier this same session) always failed after succeeding

**Reproduction**: `bash -c 'if-no-files-found: ignore'` → `bash: line 1:
if-no-files-found:: command not found`, exit 127. The line was a stray
`with:`-block YAML key left inside a `run: |` block with no `with:` key at
all (this step only has `name`/`if`/`env`/`run`) — under `set -euo
pipefail` (every `run:` block in this repo starts with it), it killed the
step, and therefore the job, with FAILURE every single run, immediately
after the real `gh release upload` on the line before it had already
succeeded.

**Fix**: the stray line deleted. New consolidated
`tests/deploy/test_workflow_run_block_hygiene.py` scans every workflow's
`run:` blocks for a bare `<known-step-key>: <value>` line matching a
GitHub-Actions step-level key that would never legitimately appear as
literal shell text (`if-no-files-found`, `retention-days`,
`continue-on-error`, `working-directory`) — this bug class can recur in
any future workflow edit, not just this one file — plus a pinned
regression test for this exact line.

## Consequences

- `compute_contribution_report_from_fills`'s signature is now a breaking
  change for any caller not yet updated (none exist outside this
  repository's own `scripts/run_long_horizon_validation.py`, which was
  updated in this same change).
- `run_buy_and_hold_paper_session`'s signature changed
  (`risk_check` required, `risk_engine`/`sector_by_security` removed) —
  the one real caller and both test files were updated in this same
  change.
- `WalkForwardAggregate.fold_count` now means "valid folds only," not
  "every fold run" — `total_fold_count` is the old meaning under a new
  name. Any external consumer of a `full-validation-*.json` report
  written before this fix should not assume `fold_count == len(folds)`
  for reports written after it.
- The next real `run_full_validation.yml` execution will, for the first
  time, produce PBO/DSR/evidence numbers that correctly exclude
  integrity-invalid folds, correctly replay corporate actions in
  held-out-window contribution reports, and correctly enforce risk
  limits on any future BUY_AND_HOLD paper-trading run — none of the
  existing `docs/research/reports/full-validation-*.json` files
  (including the one from this session's own `run #36017147499`) reflect
  these fixes and should not be treated as superseded by them without a
  fresh run.

## Tests

Full repository suite run as the merge gate (see PR) — see each finding's
own "Tests" section above for the specific new/updated files.
