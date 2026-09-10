"""Session 37 tests for `scripts/run_learning_cycle.py` (ADR-0113).

Makes no network call (reads only a local DuckDB `--paper-store`
this test populates itself by first running
`scripts/run_paper_trading_cycle.py` against a tiny seeded catalog),
mirroring `test_run_paper_trading_cycle_cli.py`'s own end-to-end-via-
`main()` precedent."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

from backtest_helpers import make_bars, make_security, trading_days

from data_infra.universe import SymbolMetadata, UniverseDefinition

from storage.config import StorageConfig
from storage.data_repository import DuckDBDataRepository
from storage.engine import StorageEngine

_PAPER_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "run_paper_trading_cycle.py"
_LEARNING_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "run_learning_cycle.py"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _seed_catalog(db_path: Path) -> None:
    days = trading_days(date(2024, 1, 2), date(2024, 6, 28))
    prices = [100.0 * (1.006 ** i) for i in range(len(days))]
    bars = make_bars("AAA", days, prices)
    engine = StorageEngine(StorageConfig(root_dir=db_path))
    repository = DuckDBDataRepository(engine)
    repository.add_security(make_security("AAA", "AAA"))
    repository.append_bars(bars)
    engine.close()


def _tiny_universe() -> UniverseDefinition:
    return UniverseDefinition(
        name="TEST_UNIVERSE", version="v1", role="RESEARCH", description="d",
        symbols=(SymbolMetadata(symbol="AAA", sector="Technology"),),
    )


def _run_paper_cycle(tmp_path: Path, db_path: Path, paper_store: Path, *, end: str) -> None:
    paper_module = _load_module(_PAPER_SCRIPT_PATH, "run_paper_trading_cycle")
    paper_module._UNIVERSES["TEST_UNIVERSE"] = _tiny_universe()
    rc = paper_module.main([
        "--universe", "TEST_UNIVERSE",
        "--db-path", str(db_path),
        "--paper-store", str(paper_store),
        "--start", "2024-02-01", "--end", end,
        "--out", str(tmp_path / "paper_report.json"),
    ])
    assert rc == 0


class TestScriptIsSyntacticallyValid:
    def test_module_loads_without_error(self) -> None:
        _load_module(_LEARNING_SCRIPT_PATH, "run_learning_cycle_syntax_check")


class TestNoPaperStoreYet:
    def test_an_empty_paper_store_fails_closed_with_a_clear_message(self, tmp_path, capsys) -> None:
        paper_store = tmp_path / "paper_store"
        # A brand-new, never-run store -- DuckDBTradeJournalRepository
        # creates its schema on first connection but has zero real rows.
        StorageEngine(StorageConfig(root_dir=paper_store)).close()

        module = _load_module(_LEARNING_SCRIPT_PATH, "run_learning_cycle_empty")
        rc = module.main(["--paper-store", str(paper_store), "--out", str(tmp_path / "out.json")])

        assert rc == 1
        assert "no real Experience records" in capsys.readouterr().err


class TestEndToEndAgainstARealPaperStore:
    def test_mean_reward_baseline_runs_end_to_end_against_real_paper_trading_experience(self, tmp_path) -> None:
        """The fixture's steady upward drift produces one real opening
        BUY that never closes within the run's own window -- Phase 9's
        DataCleaningConfig.require_realized_outcome=True default
        correctly EXCLUDES an unrealized opening leg (never fabricates a
        0.0 label for it), so this specific real run's own dataset is
        legitimately INSUFFICIENT_SAMPLES/FAILED. That is the honest,
        correct outcome for this fixture, not a bug -- what this test
        actually verifies is that the full real chain (Experience ->
        Dataset -> Candidate -> Evaluation -> persistence) executes and
        persists real records end to end regardless of which outcome
        results."""
        db_path = tmp_path / "market_data"
        paper_store = tmp_path / "paper_store"
        _seed_catalog(db_path)
        _run_paper_cycle(tmp_path, db_path, paper_store, end="2024-06-20")

        module = _load_module(_LEARNING_SCRIPT_PATH, "run_learning_cycle_e2e")
        out_path = tmp_path / "learning_report.json"
        rc = module.main(["--paper-store", str(paper_store), "--out", str(out_path)])
        assert rc == 0

        report = json.loads(out_path.read_text())
        assert report["provenance"] == "PAPER_TRADING"
        assert report["trainer_version"] == "mean_reward_baseline_trainer_v1"
        assert report["experience_record_count"] > 0  # the real opening BUY still became a real ExperienceRecord
        assert report["candidate_status"] == "CANDIDATE"
        assert report["dataset_quality_status"] == "INSUFFICIENT_SAMPLES"  # no closing SELL in this window
        assert report["experiment_status"] == "FAILED"  # honest reflection of INSUFFICIENT_SAMPLES, not a crash

        # Real persistence into the same --paper-store catalog, not just
        # an in-memory result thrown away -- mirrors
        # test_run_paper_trading_cycle_cli.py's own "real persistence"
        # assertion style.
        from storage.learning_repository import DuckDBCandidateModelRepository
        engine = StorageEngine(StorageConfig(root_dir=paper_store))
        candidate_repo = DuckDBCandidateModelRepository(engine)
        assert candidate_repo.get(report["candidate_id"]) is not None
        engine.close()

    def test_linear_regression_without_feature_id_fails_closed(self, tmp_path) -> None:
        db_path = tmp_path / "market_data"
        paper_store = tmp_path / "paper_store"
        _seed_catalog(db_path)
        _run_paper_cycle(tmp_path, db_path, paper_store, end="2024-03-01")

        module = _load_module(_LEARNING_SCRIPT_PATH, "run_learning_cycle_linear_no_features")
        rc = module.main([
            "--paper-store", str(paper_store), "--trainer", "linear_regression",
            "--out", str(tmp_path / "out.json"),
        ])
        assert rc == 1

    def test_linear_regression_against_real_data_honestly_reports_unfitted(self, tmp_path) -> None:
        """No Strategy in this codebase sets OrderIntent.features yet
        (ADR-0048's own documented gap) -- every real DecisionSnapshot
        this script reads today has features=None, so a real
        LinearRegressionTrainer run against real Paper data must report
        fitted=False rather than fabricate a fit. This is the module
        docstring's own documented limitation, verified here rather than
        just asserted in prose."""
        db_path = tmp_path / "market_data"
        paper_store = tmp_path / "paper_store"
        _seed_catalog(db_path)
        _run_paper_cycle(tmp_path, db_path, paper_store, end="2024-06-20")

        module = _load_module(_LEARNING_SCRIPT_PATH, "run_learning_cycle_linear_unfitted")
        out_path = tmp_path / "learning_report.json"
        rc = module.main([
            "--paper-store", str(paper_store), "--trainer", "linear_regression",
            "--feature-id", "momentum_20d", "--out", str(out_path),
        ])
        assert rc == 0
        report = json.loads(out_path.read_text())
        assert report["candidate_parameters"]["fitted"] is False
        assert report["candidate_parameters"]["train_sample_count"] == 0

    def test_running_it_twice_is_idempotent_on_dataset_version(self, tmp_path) -> None:
        db_path = tmp_path / "market_data"
        paper_store = tmp_path / "paper_store"
        _seed_catalog(db_path)
        _run_paper_cycle(tmp_path, db_path, paper_store, end="2024-06-20")

        module = _load_module(_LEARNING_SCRIPT_PATH, "run_learning_cycle_idempotent")
        first_out = tmp_path / "first.json"
        second_out = tmp_path / "second.json"
        assert module.main(["--paper-store", str(paper_store), "--out", str(first_out)]) == 0
        assert module.main(["--paper-store", str(paper_store), "--out", str(second_out)]) == 0

        first = json.loads(first_out.read_text())
        second = json.loads(second_out.read_text())
        # Same real Trade Journal content -> same dataset_version (a
        # content hash, learning.dataset.build_training_dataset's own
        # contract) -> the same, not a duplicated, persisted dataset/
        # candidate record.
        assert first["dataset_version"] == second["dataset_version"]
        assert first["dataset_id"] == second["dataset_id"]
        assert first["candidate_id"] == second["candidate_id"]

    def test_a_second_run_against_new_experience_persists_real_resolvable_ids(self, tmp_path) -> None:
        """Session 37 (ADR-0114): an external review found that every
        `repo.record(...)` return value was discarded -- harmless on the
        FIRST run of a fresh store (the in-process id allocator, which
        restarts at 1 every invocation, and the DB's own persistent
        sequence happen to agree), but on a SECOND run whose dataset
        genuinely differs (a new dataset_version, so record() does NOT
        take its natural-key early-return path and DOES reassign a new
        id from the DB sequence), the report and the cross-references
        inside evaluation_results/learning_experiments silently kept the
        stale in-process id instead of the one actually persisted --
        `test_running_it_twice_is_idempotent_on_dataset_version` above
        could never catch this, since identical data always takes the
        early-return path. Verified here by looking the reported ids up
        directly in the DB, not by trusting the report's own internal
        consistency (the very thing that was wrong)."""
        # _seed_catalog's own steady uptrend produces exactly ONE trade
        # ever (BaselineRuleDecisionAgent never exits an uptrend), so a
        # longer --end alone would not actually change the Trade
        # Journal's content or dataset_version -- _seed_reversal_catalog
        # (rise then decline) is used instead so the second run's window
        # genuinely includes a second, real trade (the closing SELL) the
        # first run's window does not.
        db_path = tmp_path / "market_data"
        paper_store = tmp_path / "paper_store"
        _seed_reversal_catalog(db_path)
        paper_module = _load_module(_PAPER_SCRIPT_PATH, "run_learning_cycle_second_run_paper")
        paper_module._UNIVERSES["TEST_UNIVERSE"] = _tiny_universe()

        def _run_paper(end: str) -> None:
            # --resume: the same --paper-store is invoked twice over an
            # overlapping [--start, --end] range -- without it, the
            # second call would re-derive fresh lineage ids and
            # genuinely double-submit the first call's own already-
            # processed checkpoints (ADR-0073).
            rc = paper_module.main([
                "--universe", "TEST_UNIVERSE", "--db-path", str(db_path), "--paper-store", str(paper_store),
                "--start", "2024-08-01", "--end", end, "--resume", "--out", str(tmp_path / f"paper_{end}.json"),
            ])
            assert rc == 0

        _run_paper("2024-10-01")  # before the reversal -- only the opening BUY on record

        module = _load_module(_LEARNING_SCRIPT_PATH, "run_learning_cycle_second_run")
        first_out = tmp_path / "first.json"
        assert module.main(["--paper-store", str(paper_store), "--out", str(first_out)]) == 0

        _run_paper("2025-06-30")  # past the reversal -- the closing SELL is now also on record
        second_out = tmp_path / "second.json"
        assert module.main(["--paper-store", str(paper_store), "--out", str(second_out)]) == 0

        first = json.loads(first_out.read_text())
        second = json.loads(second_out.read_text())
        assert second["dataset_version"] != first["dataset_version"]  # genuinely new content, not idempotent

        from storage.learning_repository import (
            DuckDBCandidateModelRepository,
            DuckDBEvaluationRepository,
            DuckDBLearningExperimentRepository,
            DuckDBTrainingDatasetRepository,
        )

        engine = StorageEngine(StorageConfig(root_dir=paper_store))
        dataset_repo = DuckDBTrainingDatasetRepository(engine)
        candidate_repo = DuckDBCandidateModelRepository(engine)
        evaluation_repo = DuckDBEvaluationRepository(engine)
        experiment_repo = DuckDBLearningExperimentRepository(engine)

        real_dataset = dataset_repo.get(second["dataset_id"])
        real_candidate = candidate_repo.get(second["candidate_id"])
        real_evaluation = evaluation_repo.get(second["evaluation_id"])
        real_experiment = experiment_repo.get(second["experiment_id"])
        engine.close()

        assert real_dataset is not None and real_dataset.dataset_version == second["dataset_version"]
        assert real_candidate is not None
        # The actual bug: these cross-references, read back from real
        # persisted rows, must point at each other -- not at a stale
        # in-process id that never made it into the database at all.
        assert real_evaluation is not None
        assert real_evaluation.candidate_id == real_candidate.candidate_id
        assert real_evaluation.dataset_id == real_dataset.dataset_id
        assert real_experiment is not None
        assert real_experiment.candidate_id == real_candidate.candidate_id
        assert real_experiment.dataset_id == real_dataset.dataset_id
        assert real_experiment.evaluation_id == real_evaluation.evaluation_id


def _seed_reversal_catalog(db_path: Path) -> None:
    """Rises for 250 trading days (long enough to clear a real BUY, and
    to clear RegimeDetector's own 100-day trend_long_window before
    --start) then reverses into a sustained decline -- the only way to
    make BaselineRuleDecisionAgent produce a real closing SELL
    (decision/agent.py only exits on a negative expected return).
    Deterministic (fixed seed), confirmed by direct instrumentation to
    produce a real SELL before being written as a test."""
    import random

    days = trading_days(date(2024, 1, 2), date(2025, 6, 30))
    rng = random.Random(3)
    closes = [100.0]
    for i in range(1, len(days)):
        daily_return = 0.006 if i < 250 else -0.015
        closes.append(closes[-1] * (1 + daily_return + rng.gauss(0.0, 0.005)))
    bars = make_bars("AAA", days, closes)
    engine = StorageEngine(StorageConfig(root_dir=db_path))
    repository = DuckDBDataRepository(engine)
    repository.add_security(make_security("AAA", "AAA"))
    repository.append_bars(bars)
    engine.close()


class TestFullLoopWithARealClosedTrade:
    """Session 37 (ADR-0113) capstone: the account owner's original
    question was whether real Paper/Live Trading results ever feed back
    into retraining. This is the first test to prove the FULL loop --
    a real Paper Trading run producing a real closing SELL, through the
    Trade Journal's now-fixed decision-join and realized-PnL gaps
    (paper_runner.py), into a real, non-trivial, COMPLETED training
    run -- rather than each half being merely plumbed but never proven
    to work together end to end."""

    def test_a_real_closed_trade_produces_a_real_completed_training_run(self, tmp_path) -> None:
        db_path = tmp_path / "market_data"
        paper_store = tmp_path / "paper_store"
        _seed_reversal_catalog(db_path)

        paper_module = _load_module(_PAPER_SCRIPT_PATH, "run_learning_cycle_capstone_paper")
        paper_module._UNIVERSES["TEST_UNIVERSE"] = _tiny_universe()
        paper_out = tmp_path / "paper_report.json"
        rc = paper_module.main([
            "--universe", "TEST_UNIVERSE", "--db-path", str(db_path), "--paper-store", str(paper_store),
            "--start", "2024-08-01", "--end", "2025-06-30", "--out", str(paper_out),
        ])
        assert rc == 0

        learning_module = _load_module(_LEARNING_SCRIPT_PATH, "run_learning_cycle_capstone_learning")
        learning_out = tmp_path / "learning_report.json"
        rc2 = learning_module.main(["--paper-store", str(paper_store), "--out", str(learning_out)])
        assert rc2 == 0

        report = json.loads(learning_out.read_text())
        # The point of ADR-0113: a real closed trade's real
        # realized_return actually reaches a real, non-trivial dataset
        # and a COMPLETED training run -- not INSUFFICIENT_SAMPLES/FAILED,
        # which is what every real Paper Trading run produced before
        # this session's fixes (see the other tests in this file, still
        # correctly documenting that outcome for a fixture with no SELL).
        assert report["dataset_sample_count"] >= 1
        assert report["dataset_quality_status"] == "OK"
        assert report["experiment_status"] == "COMPLETED"
        assert report["test_metrics"]["sample_count"] >= 1
        assert report["test_metrics"]["mean_label"] is not None
