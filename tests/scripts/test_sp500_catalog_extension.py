"""sp500_catalog_extension.py (ADR-0224) against a real on-disk catalog."""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backtest"))

from backtest_helpers import make_bars, trading_days  # noqa: E402

from storage.config import StorageConfig  # noqa: E402
from storage.data_repository import DuckDBDataRepository  # noqa: E402
from storage.engine import StorageEngine  # noqa: E402

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "sp500_catalog_extension.py"


def _load():
    spec = importlib.util.spec_from_file_location("sp500_catalog_extension", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _catalog(tmp_path: Path) -> Path:
    db = tmp_path / "catalog"
    repo = DuckDBDataRepository(StorageEngine(StorageConfig(root_dir=db)))
    days = trading_days(date(2008, 1, 2), date(2008, 2, 1))
    repo.append_bars(make_bars("HAVE", days, [10.0] * len(days)))
    return db


def test_missing_keeps_only_symbols_without_bars(tmp_path: Path, capsys) -> None:
    db = _catalog(tmp_path)
    symbols = tmp_path / "symbols.txt"
    symbols.write_text("GONE\nHAVE\n\nNEW\n")
    out = tmp_path / "todo.txt"
    assert _load().main([
        "missing", "--db-path", str(db), "--symbols-file", str(symbols), "--out", str(out),
        "--start", "2000-01-01", "--end", "2016-07-11",
    ]) == 0
    assert out.read_text().split() == ["GONE", "NEW"]
    assert "1 already in the catalog" in capsys.readouterr().out


def test_coverage_reports_members_with_data(tmp_path: Path, capsys) -> None:
    db = _catalog(tmp_path)
    intervals = tmp_path / "sp500.csv"
    intervals.write_text("ticker,start_date,end_date\nHAVE,1996-01-02,\nGONE,1996-01-02,2012-01-01\n")
    renames = tmp_path / "renames.csv"
    renames.write_text("old_ticker,new_ticker,rename_date,note\n")
    assert _load().main([
        "coverage", "--db-path", str(db), "--sp500-intervals-csv", str(intervals), "--renames-csv", str(renames),
        "--start", "2008-01-01", "--end", "2009-12-31",
    ]) == 0
    printed = capsys.readouterr().out
    assert '"members": 2' in printed and '"with_price_data": 1' in printed
