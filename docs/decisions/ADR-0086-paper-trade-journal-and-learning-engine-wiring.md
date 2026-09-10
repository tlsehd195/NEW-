# ADR-0086: wire real Paper Trading into the Trade Journal, and the Trade Journal into the Learning Engine

**Status:** Accepted
**Session:** 37

## Context

The account owner asked whether this project has a feature that
retrains from Paper/Live Trading results ("모의투자 하는거와 실제투자
하는걸로 재학습 하는 기능 없어?"). Investigating the actual code (not
just the specifications) found two fully-built, fully-tested, but never
-connected halves:

- `trade_journal.experience.build_experience_records` (Phase 3) turns
  real Trade Journal records into `ExperienceRecord`s, and
  `learning.pipeline.run_learning_pipeline` (Phase 9) turns those into a
  trained `CandidateModelArtifact` + `EvaluationResult` --
  `tests/integration/test_paper_learning_readiness_lineage.py`
  (Phase 17) already proves this whole chain works, end to end, with
  hand-assembled data.
- `orchestration.paper_runner.run_cycle` (ADR-0067/ADR-0068) and
  `scripts/run_paper_trading_cycle.py` (ADR-0068) already run a real,
  repeated Paper Trading loop against real market data, persisting
  real orders/fills through `broker.paper.*`'s own repositories.

Neither side ever called the other. `run_cycle` never recorded a
`DecisionSnapshot` or `TradeRecord` for anything it did --
`trade_journal.backtest_adapter`'s own module docstring had explicitly
anticipated this exact gap ("the rest of the package ... has no
Phase-2-specific dependency, so a future Paper/Live adapter can populate
the same Journal without touching them"), but nothing had ever built
that adapter. `broker.paper.journal.build_trade_record` existed as a
`PaperFillRecord -> TradeRecord` bridge function but had zero real
callers anywhere in `src/` (only its own unit test used it). As a
result, `build_experience_records`/`run_learning_pipeline` had nothing
real from Paper Trading to ever read, despite the daily GitHub Actions
Paper Trading scheduler (ADR-0082/ADR-0083/ADR-0085) having been live
for several sessions.

## Decision

**1. `src/trade_journal/paper_adapter.py` (new module).** The Paper
adapter `backtest_adapter.py` anticipated. `record_decision_and_trades`
is called once per security per `run_cycle` checkpoint: it ALWAYS
records a `DecisionSnapshot` (mirrors `ingest_backtest_result` recording
one "for every Order regardless of status"), and a `TradeRecord` for
every real fill that checkpoint produced. `PaperJournalState` carries a
local `backtest.portfolio.PortfolioAccounting` replay + open-position
timestamps across successive calls (the same "caller-owned state
carried forward" shape `PaperRunnerState.value_history` already uses),
since `run_cycle` is called once per checkpoint (streaming) rather than
once per finished run (`ingest_backtest_result`'s own bulk-replay
shape). `reconstruct_journal_state` rebuilds that same state from a
journal's own already-persisted trades, for a resumed run.

`DecisionSnapshot.order` is always left `None` here -- it is typed for
`backtest.orders.Order` (`order.order_id`), and
`broker.validation.build_validated_order` produces the structurally
different `broker.models.ValidatedOrder` (`client_order_id`, no
`order_id`). Passing one through as the other broke both
`TradeJournalRepository.record_decision`'s natural-key derivation and
`storage.serialization.decision_snapshot_to_payload` identically --
caught by this module's own tests before it ever reached
`orchestration.paper_runner`. An explicit `natural_key` is supplied
instead for idempotent dedup.

**2. `orchestration.paper_runner.run_cycle`: opt-in `trade_journal`/
`journal_state` parameters.** Both default to `None` (skip -- every
existing caller's behavior is unchanged, matching the same "persist
only if supplied" precedent the five `*_repository` parameters already
established). Supplying only one of the pair raises `ValueError`
(fail-closed, not a silent half-wiring). `run_cycle` now also keeps the
real `fills` `PaperTradingSession.submit` returns (previously discarded
as `_fills`) so the adapter has something to record.

**3. `scripts/run_paper_trading_cycle.py`: wired, on by default.** A
`DuckDBTradeJournalRepository` is constructed against the same
`--paper-store` catalog file (the same "one catalog file, several
tables" pattern `storage.paper_repository`/`storage.trade_journal_repository`
already share). `journal_state` is *always* reconstructed from whatever
the journal already has (empty for a fresh store) -- not only under
`--resume`, the same "always correct, never just a `--resume` special
case" choice ADR-0073 already made for `PaperTradingSession.restore()`.
The report gains `trade_journal_decisions`/`trade_journal_trades`
counts.

**4. `scripts/run_learning_cycle.py` (new script).** The missing "read
side": builds real `ExperienceRecord`s from whatever `--paper-store` a
real `run_paper_trading_cycle.py` run already populated, runs
`learning.pipeline.run_learning_pipeline`, and persists every stage
(`TrainingDataset`/`CandidateModelArtifact`/`EvaluationResult`/
`LearningExperimentRecord`) through the real DuckDB-backed
`storage.learning_repository` classes, in the same catalog file.
Read-only with respect to the Trade Journal -- `run_paper_trading_cycle.py`
remains the only writer. Default trainer is `MeanRewardBaselineTrainer`,
not `LinearRegressionTrainer`: no `Strategy`/`DecisionAgent` in this
codebase sets `OrderIntent.features` yet (ADR-0048's own documented
gap), so every real `DecisionSnapshot`/`LabeledSample.features` this
script reads today is `None` -- `LinearRegressionTrainer` is still
offered (`--trainer linear_regression --feature-id ...`) but will
honestly report `fitted=False` against real data until some Strategy
actually populates real features, which this ADR does not attempt.

## What this does NOT do

Does not populate `OrderIntent.features` for any Strategy/DecisionAgent
-- `LinearRegressionTrainer` (and any future feature-based trainer)
still has nothing real to fit on. Does not wire `Live` Trading
(`orchestration.live_runner`) to the Trade Journal -- Live activation
remains structurally blocked (zero `VALIDATED` strategy candidates,
Toss capability verification pending, per
`docs/operations/PRODUCTION-READINESS-MATRIX.md`), so there is no real
Live experience to record yet; the same adapter shape (a
`LiveJournalState` + a Live-specific `record_decision_and_trades`
equivalent) would be the natural next step once Live actually runs, not
built speculatively here (RULE 0.8). Does not make the Paper Trading
scheduler (`.github/workflows/paper_trading_cycle.yml`) call
`run_learning_cycle.py` automatically -- retraining is left a distinct,
manually-invoked step, mirroring this project's existing separation
between the ingestion/paper-cycle/keepalive workflows rather than
silently growing one of them. Does not change what
`MeanRewardBaselineTrainer` or `LinearRegressionTrainer` themselves
compute, or any Learning Engine dataset/labeling/evaluation logic --
purely a wiring change connecting two already-correct halves. Does not
promote any `CandidateModelArtifact` past `CandidateModelStatus.CANDIDATE`
-- no code path here or anywhere else does that automatically (Phase 17
Production Safety Review invariant, re-verified unchanged).

## Tests

`tests/trade_journal/test_journal_paper_adapter.py` (6 tests, named to
avoid a module-basename collision with the pre-existing
`tests/broker/paper/test_paper_adapter.py`): a HOLD/no-fill
cycle still records exactly one decision and zero trades; calling twice
for the same security/checkpoint dedupes via natural key; a BUY then a
closing SELL computes exact `realized_pnl`/`realized_return`/
`holding_period` against hand-verified numbers (not just "is not
None"); partial fills across two calls each produce their own
`TradeRecord`; `reconstruct_journal_state` rebuilds a state that
produces identical `realized_pnl` to an uninterrupted single-process
run, and reconstructs an empty state from an empty journal.
`tests/orchestration/test_paper_runner.py::TestTradeJournalWiring` (5
tests): a warranted BUY produces a real decision+trade record end to
end through `run_cycle`; a risk-rejected cycle still records a decision
but no trade; a closing SELL (when the fixture's own drift produces
one) realizes real, non-fabricated PnL; supplying only one of
`trade_journal`/`journal_state` raises; omitting both leaves existing
behavior unchanged (regression-checked against the file's own
pre-existing scenario). `tests/orchestration/test_run_paper_trading_cycle_cli.py::TestTradeJournalWiring`
(2 tests): a real CLI run persists exactly one real decision per
checkpoint; `--resume` never double-counts journal records across two
runs. `tests/orchestration/test_run_learning_cycle_cli.py` (6 tests):
module loads; an empty `--paper-store` fails closed with a clear
message; a real end-to-end run against real Paper Trading experience
persists a real `CandidateModelArtifact`/`EvaluationResult`
(honestly reporting `INSUFFICIENT_SAMPLES`/`FAILED` for a fixture whose
one real BUY never closes within the run's own window -- not a bug);
`--trainer linear_regression` without `--feature-id` fails closed;
`--trainer linear_regression` against real data honestly reports
`fitted=False, train_sample_count=0` (the documented current
limitation, verified rather than just asserted); running the script
twice against the same store is idempotent on `dataset_version`. 19 new
tests total across the four files above. Full suite re-run: 2408 passed.
