"""Category: `scripts/merge_macro_stores.py` (ADR-0217) combines the
per-series matrix stores and coverage reports into one."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from data_infra.providers.fred import FredVintageObservation, vintage_to_macro_record

from storage.config import StorageConfig
from storage.engine import StorageEngine
from storage.macro_repository import DuckDBMacroRepository

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "merge_macro_stores.py"
_NOW = datetime(2026, 9, 26, tzinfo=timezone.utc)


def _load_module():
    spec = importlib.util.spec_from_file_location("merge_macro_stores", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_part(root: Path, series_id: str) -> None:
    engine = StorageEngine(StorageConfig(root_dir=root / "macro-store"))
    obs = FredVintageObservation(series_id, date(2024, 1, 1), 1.0, date(2024, 2, 2), None, _NOW)
    DuckDBMacroRepository(engine).add_macro_observations([vintage_to_macro_record(obs, ingestion_time=_NOW)])
    engine.close()
    (root / "macro_coverage.json").write_text(json.dumps({"series": [{"series_id": series_id}], "failed": []}))


def test_merge_combines_parts_idempotently(tmp_path) -> None:
    _write_part(tmp_path / "a", "PAYEMS")
    _write_part(tmp_path / "b", "UNRATE")
    (tmp_path / "c").mkdir()
    (tmp_path / "c" / "macro_coverage.json").write_text(json.dumps({"series": [], "failed": ["DFF"]}))
    module = _load_module()
    parts = [tmp_path / "a", tmp_path / "b", tmp_path / "c"]
    result = module.merge(str(tmp_path / "out"), parts)
    module.merge(str(tmp_path / "out"), parts)
    assert [s["series_id"] for s in result["series"]] == ["PAYEMS", "UNRATE"]
    assert result["failed"] == ["DFF"]
    engine = StorageEngine(StorageConfig(root_dir=tmp_path / "out"))
    repo = DuckDBMacroRepository(engine)
    assert repo.list_series_ids() == ["PAYEMS", "UNRATE"]
    assert len(repo.get_all_vintages("PAYEMS")) == 1
