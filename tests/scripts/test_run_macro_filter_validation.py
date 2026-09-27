"""Category: end-to-end smoke test of scripts/run_macro_filter_validation.py
on small synthetic stores (ADR-0220): every pre-registered rule is run,
the report carries PBO/DSR and a grade per rule, and a range touching a
locked TEST window is refused."""

from __future__ import annotations

import importlib.util
import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from backtest_helpers import make_bars, trading_days

from data_infra.providers.fred import FredVintageObservation, vintage_to_macro_record
from storage.config import StorageConfig
from storage.data_repository import DuckDBDataRepository
from storage.engine import StorageEngine
from storage.macro_repository import DuckDBMacroRepository

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "run_macro_filter_validation.py"
_NOW = datetime(2026, 9, 27, tzinfo=timezone.utc)


def _load():
    spec = importlib.util.spec_from_file_location("run_macro_filter_validation", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _stores(tmp_path: Path) -> tuple[Path, Path]:
    price_dir, macro_dir = tmp_path / "price", tmp_path / "macro"
    days = trading_days(date(1999, 6, 1), date(2001, 6, 29))
    spy = [100.0 * (1 + 0.1 * math.sin(i / 20)) for i in range(len(days))]
    gld = [50.0 * (1 + 0.1 * math.cos(i / 25)) for i in range(len(days))]
    engine = StorageEngine(StorageConfig(root_dir=price_dir))
    DuckDBDataRepository(engine).append_bars(make_bars("SPY", days, spy) + make_bars("GLD", days, gld))
    engine.close()

    engine = StorageEngine(StorageConfig(root_dir=macro_dir))
    records = []
    d = date(1999, 1, 1)
    i = 0
    while d <= date(2001, 6, 29):
        vix = 20.0 + 15.0 * math.sin(i / 30)
        records.append(vintage_to_macro_record(FredVintageObservation("VIXCLS", d, vix, d, None, _NOW), ingestion_time=_NOW))
        d += timedelta(days=1)
        i += 1
    DuckDBMacroRepository(engine).add_macro_observations(records)
    engine.close()
    return price_dir, macro_dir


def test_runs_every_rule_and_grades_them(tmp_path) -> None:
    price_dir, macro_dir = _stores(tmp_path)
    report_path = tmp_path / "report.json"
    rc = _load().main([
        "--price-db-path", str(price_dir), "--macro-db-path", str(macro_dir),
        "--start", "2000-01-03", "--end", "2001-06-29",
        "--train-window-months", "1", "--test-window-months", "1", "--step-months", "1",
        "--report-json", str(report_path),
    ])
    assert rc == 0
    report = json.loads(report_path.read_text())
    assert len(report["continuous"]) == 12
    assert report["trial_count"] == 11
    assert report["continuous"]["no_filter"]["fills"] == 1
    assert report["continuous"]["only_vix_high"]["share_de_risked"] > 0
    assert report["signal_availability"]["vix_high"]["share_available"] > 0.9
    assert report["signal_availability"]["sahm_rule"]["share_available"] == 0.0
    assert report["walk_forward"]["pbo"] is not None
    assert set(report["grades"]) == set(report["continuous"]) - {"no_filter"}
    assert all(g["grade"] in ("CANDIDATE", "INCONCLUSIVE") for g in report["grades"].values())


def test_refuses_a_locked_window(tmp_path) -> None:
    rc = _load().main([
        "--price-db-path", str(tmp_path / "p"), "--macro-db-path", str(tmp_path / "m"),
        "--start", "2019-01-01", "--end", "2021-01-01", "--report-json", str(tmp_path / "r.json"),
    ])
    assert rc == 2
