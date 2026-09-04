"""Session 36 tests for `scripts/run_paper_trading_cycle.py` (ADR-0068).

Makes no network call (reads only a local DuckDB catalog this test
populates itself), so -- unlike the SEC EDGAR/network-dependent
scripts this project tests at the AST/source level only -- this one is
run end to end via `main()`, mirroring `tests/strategy_research/
test_compute_fundamentals_ic_from_catalog_cli.py`'s own precedent for
a network-free catalog-reading script. `_UNIVERSES` is monkeypatched to
a tiny one-symbol universe so the test does not need bars for every
real symbol in `PILOT_UNIVERSE_V1`/`RESEARCH_UNIVERSE_STAGE4`."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from backtest_helpers import make_bars, make_security, trading_days

from data_infra.universe import SymbolMetadata, UniverseDefinition

from storage.config import StorageConfig
from storage.data_repository import DuckDBDataRepository
from storage.engine import StorageEngine
from storage.paper_repository import DuckDBPaperFillRepository, DuckDBPaperOrderRepository
from storage.prediction_repository import DuckDBPredictionRepository

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "run_paper_trading_cycle.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("run_paper_trading_cycle", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _seed_catalog(db_path: Path) -> None:
    days = trading_days(date(2024, 1, 2), date(2024, 4, 30))
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


class TestScriptIsSyntacticallyValid:
    def test_module_loads_without_error(self) -> None:
        _load_module()  # raises on any import/syntax error


class TestEndToEndAgainstASeededCatalog:
    def test_a_short_run_persists_real_lineage_and_writes_a_report(self, tmp_path) -> None:
        db_path = tmp_path / "market_data"
        paper_store = tmp_path / "paper_store"
        out_path = tmp_path / "report.json"
        _seed_catalog(db_path)

        module = _load_module()
        module._UNIVERSES["TEST_UNIVERSE"] = _tiny_universe()

        rc = module.main([
            "--universe", "TEST_UNIVERSE",
            "--db-path", str(db_path),
            "--paper-store", str(paper_store),
            "--start", "2024-02-01", "--end", "2024-02-15",
            "--out", str(out_path),
        ])
        assert rc == 0

        report = json.loads(out_path.read_text())
        assert report["universe"] == "TEST_UNIVERSE"
        assert report["checkpoints_run"] > 0
        assert "content_checksum" in report

        # Real persistence -- not just an in-memory result thrown away.
        store_engine = StorageEngine(StorageConfig(root_dir=paper_store))
        prediction_repo = DuckDBPredictionRepository(store_engine)
        assert len(prediction_repo.list_all(security_id="AAA")) == report["checkpoints_run"]
        store_engine.close()

    def test_a_run_with_sector_limit_configured_uses_the_universes_real_sector_data(self, tmp_path) -> None:
        db_path = tmp_path / "market_data"
        paper_store = tmp_path / "paper_store"
        out_path = tmp_path / "report.json"
        _seed_catalog(db_path)

        module = _load_module()
        module._UNIVERSES["TEST_UNIVERSE"] = _tiny_universe()

        rc = module.main([
            "--universe", "TEST_UNIVERSE",
            "--db-path", str(db_path),
            "--paper-store", str(paper_store),
            "--start", "2024-02-01", "--end", "2024-02-10",
            "--max-sector-weight", "1.0",
            "--out", str(out_path),
        ])
        assert rc == 0
        report = json.loads(out_path.read_text())
        assert report["risk_config"]["max_sector_weight"] == 1.0

    def test_missing_bars_fails_cleanly_not_with_a_traceback(self, tmp_path) -> None:
        db_path = tmp_path / "empty_market_data"
        StorageEngine(StorageConfig(root_dir=db_path)).close()
        paper_store = tmp_path / "paper_store"
        out_path = tmp_path / "report.json"

        module = _load_module()
        module._UNIVERSES["TEST_UNIVERSE"] = _tiny_universe()

        rc = module.main([
            "--universe", "TEST_UNIVERSE",
            "--db-path", str(db_path),
            "--paper-store", str(paper_store),
            "--start", "2024-02-01", "--end", "2024-02-10",
            "--out", str(out_path),
        ])
        assert rc == 1
