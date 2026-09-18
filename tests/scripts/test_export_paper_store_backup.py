"""Real, executable tests for `scripts/export_paper_store_backup.py`
(external review, Session 38 continued -- see ADR-0149's own follow-up
in PROJECT_STATUS.md). Makes no network call -- seeds a real DuckDB
`--paper-store` with real `RiskCheckedPosition` records and runs
`main()` end to end, mirroring `tests/scripts/
test_generate_paper_performance_tearsheet_cli.py`'s own precedent for a
network-free script."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from risk.enums import RiskCheckStatus  # noqa: E402
from risk.models import PortfolioRiskState, RiskCheckedPosition  # noqa: E402

from storage.config import StorageConfig  # noqa: E402
from storage.engine import StorageEngine  # noqa: E402
from storage.risk_repository import DuckDBRiskRepository  # noqa: E402
from storage.trade_journal_repository import DuckDBTradeJournalRepository  # noqa: E402

from trade_journal.enums import DecisionAction  # noqa: E402

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "export_paper_store_backup.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("export_paper_store_backup", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _utc(y, m, d) -> datetime:
    return datetime(y, m, d, tzinfo=timezone.utc)


def _seed_one_risk_record(paper_store: Path) -> None:
    """Seeds `risk_assessments` -- a real Learning Engine/telemetry
    table, deliberately NOT part of the ledger this backup covers
    (ADR-0156) -- used by tests asserting it is correctly EXCLUDED."""
    engine = StorageEngine(StorageConfig(root_dir=paper_store))
    repository = DuckDBRiskRepository(engine)
    risk_state = PortfolioRiskState(
        as_of_time=_utc(2024, 2, 1), portfolio_value=100_000.0, cash=100_000.0, gross_exposure=0.0, net_exposure=0.0,
    )
    repository.record(RiskCheckedPosition(
        risk_id="RISK-000001", security_id="AAA", as_of_time=_utc(2024, 2, 1),
        status=RiskCheckStatus.PASS, reason="normal_sizing", breached_limits=(),
        final_target_weight=None, final_target_quantity=None,
        sizing_id=None, decision_id=None, prediction_id=None, risk_state=risk_state,
        risk_version="test_risk_engine_v1", feature_version="test_feature_v1",
    ))
    engine.close()


def _seed_one_decision_record(paper_store: Path) -> None:
    """Seeds `decisions` -- a real ledger table (ADR-0156)."""
    engine = StorageEngine(StorageConfig(root_dir=paper_store))
    repository = DuckDBTradeJournalRepository(engine)
    repository.record_decision(
        decision_time=_utc(2024, 2, 1), security_id="AAA", decision=DecisionAction.BUY,
        natural_key=("test_decision", "AAA", _utc(2024, 2, 1)),
    )
    engine.close()


class TestScriptIsSyntacticallyValid:
    def test_module_loads_without_error(self) -> None:
        _load_module()


class TestExportFunction:
    def test_every_populated_ledger_table_gets_a_json_file_with_the_real_row_count(self, tmp_path) -> None:
        paper_store = tmp_path / "paper_store"
        out_dir = tmp_path / "backup"
        _seed_one_decision_record(paper_store)

        module = _load_module()
        row_counts = module.export_paper_store_backup(paper_store, out_dir)

        assert row_counts["decisions"] == 1
        assert (out_dir / "decisions.json").is_file()
        records = json.loads((out_dir / "decisions.json").read_text())
        assert len(records) == 1
        assert records[0]["security_id"] == "AAA"

    def test_a_datetime_column_round_trips_as_a_real_iso_string(self, tmp_path) -> None:
        paper_store = tmp_path / "paper_store"
        out_dir = tmp_path / "backup"
        _seed_one_decision_record(paper_store)

        module = _load_module()
        module.export_paper_store_backup(paper_store, out_dir)

        records = json.loads((out_dir / "decisions.json").read_text())
        # decision_time must be a real, parseable ISO-8601 string -- never
        # a repr()'d Python datetime or an epoch integer.
        datetime.fromisoformat(records[0]["decision_time"])

    def test_rerunning_overwrites_rather_than_accumulates(self, tmp_path) -> None:
        paper_store = tmp_path / "paper_store"
        out_dir = tmp_path / "backup"
        _seed_one_decision_record(paper_store)

        module = _load_module()
        module.export_paper_store_backup(paper_store, out_dir)
        module.export_paper_store_backup(paper_store, out_dir)  # second run, same store

        records = json.loads((out_dir / "decisions.json").read_text())
        assert len(records) == 1  # not doubled

    def test_a_fresh_store_with_no_tables_yet_backs_up_nothing_without_crashing(self, tmp_path) -> None:
        paper_store = tmp_path / "paper_store"
        out_dir = tmp_path / "backup"
        engine = StorageEngine(StorageConfig(root_dir=paper_store))  # initializes schema, no rows
        engine.close()

        module = _load_module()
        row_counts = module.export_paper_store_backup(paper_store, out_dir)
        assert all(count == 0 for count in row_counts.values())

    def test_a_non_ledger_table_is_never_backed_up_even_if_populated(self, tmp_path) -> None:
        """ADR-0156: risk_assessments (and the rest of the Learning
        Engine/telemetry tables) are real production data, but caused
        this backup's git push to fail atomically on GitHub's 100 MB
        file limit -- deliberately excluded now, regardless of how
        populated they are."""
        paper_store = tmp_path / "paper_store"
        out_dir = tmp_path / "backup"
        _seed_one_risk_record(paper_store)

        module = _load_module()
        row_counts = module.export_paper_store_backup(paper_store, out_dir)

        assert "risk_assessments" not in row_counts
        assert not (out_dir / "risk_assessments.json").exists()

    def test_a_table_whose_json_exceeds_the_size_cap_is_skipped_with_a_warning(self, tmp_path, capsys, monkeypatch) -> None:
        paper_store = tmp_path / "paper_store"
        out_dir = tmp_path / "backup"
        _seed_one_decision_record(paper_store)

        module = _load_module()
        monkeypatch.setattr(module, "_MAX_TABLE_JSON_BYTES", 1)  # any real row now "exceeds" this
        row_counts = module.export_paper_store_backup(paper_store, out_dir)

        assert "decisions" not in row_counts
        assert not (out_dir / "decisions.json").exists()
        stderr = capsys.readouterr().err
        assert "WARNING" in stderr
        assert "decisions.json exceeds" in stderr


class TestCLI:
    def test_main_returns_zero_and_prints_a_summary(self, tmp_path, capsys) -> None:
        paper_store = tmp_path / "paper_store"
        out_dir = tmp_path / "backup"
        _seed_one_decision_record(paper_store)

        module = _load_module()
        rc = module.main(["--paper-store", str(paper_store), "--out-dir", str(out_dir)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "decisions" in out

    def test_missing_paper_store_fails_loudly(self, tmp_path, capsys) -> None:
        module = _load_module()
        rc = module.main(["--paper-store", str(tmp_path / "does_not_exist"), "--out-dir", str(tmp_path / "backup")])
        assert rc == 1
        assert "FATAL" in capsys.readouterr().err
