"""Real, executable tests for `scripts/generate_paper_performance_tearsheet.py`
(Session 38, ADR-0138). Makes no network call -- seeds a real DuckDB
`--paper-store` with real `RiskCheckedPosition` records (the same
source `scripts/run_paper_trading_cycle.py`'s own `_equity_history()`
reads, ADR-0136) and runs `main()` end to end, mirroring `tests/
data_infra/test_convert_finra_short_interest_response.py`'s own
precedent for a network-free script."""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

pytest.importorskip("quantstats", reason="optional [reporting] extra not installed")
pytest.importorskip("pandas", reason="optional [reporting] extra not installed")

from risk.enums import RiskCheckStatus  # noqa: E402
from risk.models import PortfolioRiskState, RiskCheckedPosition  # noqa: E402

from storage.config import StorageConfig  # noqa: E402
from storage.engine import StorageEngine  # noqa: E402
from storage.risk_repository import DuckDBRiskRepository  # noqa: E402

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "generate_paper_performance_tearsheet.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("generate_paper_performance_tearsheet", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _utc(y, m, d) -> datetime:
    return datetime(y, m, d, tzinfo=timezone.utc)


def _seed_risk_checkpoints(paper_store: Path, *, portfolio_values: list[float]) -> None:
    engine = StorageEngine(StorageConfig(root_dir=paper_store))
    repository = DuckDBRiskRepository(engine)
    for i, value in enumerate(portfolio_values):
        as_of = _utc(2024, 2, 1) + timedelta(days=i)
        risk_state = PortfolioRiskState(
            as_of_time=as_of, portfolio_value=value, cash=value, gross_exposure=0.0, net_exposure=0.0,
        )
        repository.record(RiskCheckedPosition(
            risk_id=f"RISK-{i + 1:06d}", security_id="AAA", as_of_time=as_of,
            status=RiskCheckStatus.PASS, reason="normal_sizing", breached_limits=(),
            final_target_weight=None, final_target_quantity=None,
            sizing_id=None, decision_id=None, prediction_id=None, risk_state=risk_state,
            risk_version="test_risk_engine_v1", feature_version="test_feature_v1",
        ))
    engine.close()


class TestScriptIsSyntacticallyValid:
    def test_module_loads_without_error(self) -> None:
        _load_module()


class TestEndToEndAgainstASeededStore:
    def test_writes_a_real_html_tearsheet(self, tmp_path) -> None:
        paper_store = tmp_path / "paper_store"
        out_path = tmp_path / "tearsheet.html"
        _seed_risk_checkpoints(paper_store, portfolio_values=[100_000.0 * (1.001 ** i) for i in range(30)])

        module = _load_module()
        rc = module.main([
            "--paper-store", str(paper_store), "--security-id", "AAA", "--out", str(out_path),
        ])
        assert rc == 0
        assert out_path.is_file()
        html = out_path.read_text(errors="ignore")
        assert "<html" in html.lower()

    def test_custom_title_appears_in_the_output(self, tmp_path) -> None:
        paper_store = tmp_path / "paper_store"
        out_path = tmp_path / "tearsheet.html"
        _seed_risk_checkpoints(paper_store, portfolio_values=[100_000.0, 101_000.0, 99_500.0, 102_000.0])

        module = _load_module()
        rc = module.main([
            "--paper-store", str(paper_store), "--security-id", "AAA", "--out", str(out_path),
            "--title", "My Custom Tearsheet Title",
        ])
        assert rc == 0
        assert "My Custom Tearsheet Title" in out_path.read_text(errors="ignore")


class TestInsufficientData:
    def test_fewer_than_two_checkpoints_fails_cleanly_not_with_a_traceback(self, tmp_path) -> None:
        paper_store = tmp_path / "paper_store"
        out_path = tmp_path / "tearsheet.html"
        _seed_risk_checkpoints(paper_store, portfolio_values=[100_000.0])

        module = _load_module()
        rc = module.main([
            "--paper-store", str(paper_store), "--security-id", "AAA", "--out", str(out_path),
        ])
        assert rc == 1
        assert not out_path.exists()

    def test_no_checkpoints_at_all_fails_cleanly(self, tmp_path) -> None:
        paper_store = tmp_path / "paper_store"
        out_path = tmp_path / "tearsheet.html"
        _seed_risk_checkpoints(paper_store, portfolio_values=[])

        module = _load_module()
        rc = module.main([
            "--paper-store", str(paper_store), "--security-id", "AAA", "--out", str(out_path),
        ])
        assert rc == 1

    def test_missing_paper_store_fails_cleanly(self, tmp_path) -> None:
        module = _load_module()
        rc = module.main([
            "--paper-store", str(tmp_path / "does_not_exist"), "--security-id", "AAA",
            "--out", str(tmp_path / "tearsheet.html"),
        ])
        assert rc == 1
