"""Tests for `scripts/repair_corporate_action_available_time.py`
(ADR-0216): a catalog whose corporate actions were stamped with a late
backfill ingestion time gets them re-stamped at their event-date close,
so historical as-of queries see them. Network-free."""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

from data_infra.enums import CorporateActionType
from data_infra.models import CorporateAction, Provenance
from storage.config import StorageConfig
from storage.data_repository import DuckDBDataRepository
from storage.engine import StorageEngine

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "repair_corporate_action_available_time.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("repair_corporate_action_available_time", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _dt(y, m, d, h=0):
    return datetime(y, m, d, h, tzinfo=timezone.utc)


def _action(rid, source, action_type, event, details):
    return CorporateAction(
        security_id="AAPL", action_type=action_type, available_time=_dt(2026, 9, 11), ingestion_time=_dt(2026, 9, 11),
        provenance=Provenance(source=source, source_dataset="d", source_record_id=rid, retrieved_at=_dt(2026, 9, 11), data_version="v"),
        event_time=event, effective_time=event, details=details,
    )


def _seed(root: Path) -> None:
    engine = StorageEngine(StorageConfig(root_dir=root))
    try:
        repo = DuckDBDataRepository(engine)
        repo.add_corporate_action(_action("split", "tiingo", CorporateActionType.SPLIT, _dt(2014, 6, 9), {"ratio": 7.0}))
        repo.add_corporate_action(_action("div", "alphavantage", CorporateActionType.DIVIDEND, _dt(2014, 5, 8), {"amount": 3.29, "currency": "USD"}))
        repo.add_corporate_action(_action("other", "manual", CorporateActionType.SPLIT, _dt(2014, 6, 9), {"ratio": 2.0}))
    finally:
        engine.close()


def _visible_2014(root: Path) -> list[str]:
    engine = StorageEngine(StorageConfig(root_dir=root))
    try:
        actions = DuckDBDataRepository(engine).get_corporate_actions("AAPL", _dt(2014, 1, 1), _dt(2014, 12, 31), as_of_time=_dt(2014, 9, 1))
        return sorted(a.provenance.source_record_id for a in actions)
    finally:
        engine.close()


def test_dry_run_changes_nothing(tmp_path) -> None:
    _seed(tmp_path)
    assert _load_module().main(["--db-path", str(tmp_path)]) == 0
    assert _visible_2014(tmp_path) == []


def test_apply_restamps_provider_actions_at_their_event_date_close_and_is_idempotent(tmp_path, capsys) -> None:
    _seed(tmp_path)
    module = _load_module()
    assert module.main(["--db-path", str(tmp_path), "--apply"]) == 0
    assert _visible_2014(tmp_path) == ["div", "split"]  # the non-provider row is left alone
    engine = StorageEngine(StorageConfig(root_dir=tmp_path))
    try:
        [split] = [a for a in DuckDBDataRepository(engine).get_corporate_actions(
            "AAPL", _dt(2014, 1, 1), _dt(2014, 12, 31), as_of_time=_dt(2027, 1, 1)) if a.provenance.source_record_id == "split"]
    finally:
        engine.close()
    assert split.available_time == _dt(2014, 6, 9, 20)
    assert split.ingestion_time == _dt(2026, 9, 11)
    capsys.readouterr()
    assert module.main(["--db-path", str(tmp_path), "--apply"]) == 0
    assert "nothing to repair" in capsys.readouterr().out
