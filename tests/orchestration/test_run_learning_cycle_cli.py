"""Session 37 tests for `scripts/run_learning_cycle.py` (ADR-0086).

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
