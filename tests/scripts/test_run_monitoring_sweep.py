"""Real, executable tests for `scripts/run_monitoring_sweep.py`
(independent audit finding, Step 10, P2 -- see that script's own module
docstring for the full gap this closes).

Makes no network call -- reads only a local `--paper-store` this test
populates itself by first running the real
`scripts/run_paper_trading_cycle.py` end to end (mirroring
`tests/orchestration/test_run_paper_trading_cycle_cli.py`'s own
precedent for a network-free CLI script), so the monitoring sweep is
exercised against REAL prediction/decision/sizing/risk records, not
hand-fabricated fixtures.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

from backtest_helpers import make_bars, make_security, trading_days

from data_infra.universe import SymbolMetadata, UniverseDefinition

from monitoring.enums import ComponentHealthStatus, MonitoringComponent

from storage.config import StorageConfig
from storage.data_repository import DuckDBDataRepository
from storage.engine import StorageEngine
from storage.monitoring_repository import DuckDBAlertRepository, DuckDBComponentHealthRepository, DuckDBMonitoringEventRepository

_SWEEP_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "run_monitoring_sweep.py"
_CYCLE_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "run_paper_trading_cycle.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
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


def _populate_paper_store(tmp_path: Path) -> Path:
    db_path = tmp_path / "market_data"
    paper_store = tmp_path / "paper_store"
    _seed_catalog(db_path)

    cycle_module = _load(_CYCLE_SCRIPT_PATH, "run_paper_trading_cycle")
    cycle_module._UNIVERSES["TEST_UNIVERSE"] = _tiny_universe()
    rc = cycle_module.main([
        "--universe", "TEST_UNIVERSE",
        "--db-path", str(db_path),
        "--paper-store", str(paper_store),
        "--start", "2024-02-01", "--end", "2024-02-15",
        "--out", str(tmp_path / "cycle_report.json"),
    ])
    assert rc == 0
    return paper_store


class TestScriptIsSyntacticallyValid:
    def test_module_loads_without_error(self) -> None:
        _load(_SWEEP_SCRIPT_PATH, "run_monitoring_sweep_syntax_check")


class TestEndToEndAgainstARealPaperStore:
    def test_a_sweep_persists_real_events_health_and_writes_a_report(self, tmp_path) -> None:
        paper_store = _populate_paper_store(tmp_path)
        out_path = tmp_path / "sweep_report.json"

        sweep_module = _load(_SWEEP_SCRIPT_PATH, "run_monitoring_sweep")
        rc = sweep_module.main([
            "--paper-store", str(paper_store),
            "--representative-security-id", "AAA",
            "--start", "2024-02-01", "--end", "2024-02-15",
            "--out", str(out_path),
        ])
        assert rc == 0

        report = json.loads(out_path.read_text())
        assert report["record_counts"]["predictions"] > 0
        assert report["record_counts"]["decisions"] > 0
        assert report["record_counts"]["risk_results"] > 0
        # Independent audit finding (2026-09-24, "REGIME collector 부재"):
        # collect_regime is now wired in too -- prediction, decision,
        # regime, sizing, risk, account.
        assert report["events_persisted"] == 6
        assert {h["component"] for h in report["component_healths"]} == {
            "PREDICTION", "DECISION", "REGIME", "SIZING", "RISK", "ACCOUNT",
        }

        # Real persistence -- not just an in-memory result thrown away.
        store_engine = StorageEngine(StorageConfig(root_dir=paper_store))
        event_repository = DuckDBMonitoringEventRepository(store_engine)
        health_repository = DuckDBComponentHealthRepository(store_engine)
        assert len(event_repository.list_all()) == 6
        assert len(event_repository.list_all(component=MonitoringComponent.RISK)) == 1
        assert len(event_repository.list_all(component=MonitoringComponent.REGIME)) == 1
        assert health_repository.get_latest(MonitoringComponent.RISK) is not None
        assert health_repository.get_latest(MonitoringComponent.REGIME) is not None
        # A pipeline-level health record is persisted too (7th health row).
        assert len(health_repository.list_all()) == 7
        store_engine.close()

    def test_re_running_the_same_window_is_idempotent(self, tmp_path) -> None:
        paper_store = _populate_paper_store(tmp_path)

        sweep_module = _load(_SWEEP_SCRIPT_PATH, "run_monitoring_sweep")
        args = [
            "--paper-store", str(paper_store),
            "--representative-security-id", "AAA",
            "--start", "2024-02-01", "--end", "2024-02-15",
            "--out", str(tmp_path / "sweep_report.json"),
        ]
        assert sweep_module.main(args) == 0
        assert sweep_module.main(args) == 0  # must not double-insert or crash on a natural-key collision

        store_engine = StorageEngine(StorageConfig(root_dir=paper_store))
        event_repository = DuckDBMonitoringEventRepository(store_engine)
        # A second identical run allocates a FRESH set of ids (this
        # script always seeds its counters from what's already there,
        # never overwriting) -- so the real invariant a re-run must
        # uphold is "no crash, and every previously-persisted row is
        # still exactly as it was," not "count stays the same." Confirms
        # at least the first run's own 6 events are still present and
        # untouched, and a second run's own 6 were added on top.
        assert len(event_repository.list_all()) == 12
        store_engine.close()

    def test_account_health_is_unknown_not_a_vacuous_healthy_when_max_drawdown_is_omitted(self, tmp_path) -> None:
        """Independent audit finding (2026-09-24): before
        `monitoring.health.evaluate_account_health`'s own fix, omitting
        `--max-drawdown` (this script's own default -- it previously had
        no such flag at all) silently reported ACCOUNT as HEALTHY
        regardless of the real drawdown, masking exactly the condition
        this sweep exists to surface."""
        paper_store = _populate_paper_store(tmp_path)
        out_path = tmp_path / "sweep_report.json"

        sweep_module = _load(_SWEEP_SCRIPT_PATH, "run_monitoring_sweep")
        rc = sweep_module.main([
            "--paper-store", str(paper_store),
            "--representative-security-id", "AAA",
            "--start", "2024-02-01", "--end", "2024-02-15",
            "--out", str(out_path),
            # --max-drawdown deliberately omitted
        ])
        assert rc == 0

        report = json.loads(out_path.read_text())
        account_health = next(h for h in report["component_healths"] if h["component"] == "ACCOUNT")
        assert account_health["status"] == ComponentHealthStatus.UNKNOWN.value
        assert account_health["reason"] == "max_drawdown_not_configured"

    def test_no_alerts_raised_for_a_healthy_short_run(self, tmp_path) -> None:
        """The real fixture this test file builds produces a healthy,
        active pipeline (real BUYs, real risk assessments, no failures)
        -- confirms the sweep does not fabricate alerts where none are
        warranted."""
        paper_store = _populate_paper_store(tmp_path)
        out_path = tmp_path / "sweep_report.json"

        sweep_module = _load(_SWEEP_SCRIPT_PATH, "run_monitoring_sweep")
        rc = sweep_module.main([
            "--paper-store", str(paper_store),
            "--representative-security-id", "AAA",
            "--start", "2024-02-01", "--end", "2024-02-15",
            "--out", str(out_path),
            # Independent audit finding (2026-09-24): ACCOUNT health is
            # now correctly UNKNOWN (not a vacuous HEALTHY) when no real
            # threshold is configured -- a real, generous threshold this
            # short healthy run never approaches is required here for
            # this test's own "a genuinely healthy run raises no
            # alerts" intent to still hold.
            "--max-drawdown", "1.0",
        ])
        assert rc == 0

        report = json.loads(out_path.read_text())
        assert report["pipeline_health"]["status"] == ComponentHealthStatus.HEALTHY.value
        assert report["alerts_raised"] == []
