"""ADR-0085: scripts/compute_incremental_ingestion_start.py must never
re-request the full historical range once a catalog already has real
bars -- the real bug this exists to fix (Tiingo rate-limit exhaustion
partway through 88 symbols' ~2.5-year history, leaving SPY and 9
others with zero bars) recurred every single scheduled run precisely
because the old workflow always requested the full range regardless of
what the catalog already held."""
from __future__ import annotations

import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

from backtest_helpers import make_bars
from storage_helpers import new_engine

from storage.data_repository import DuckDBDataRepository

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from compute_incremental_ingestion_start import _OVERLAP_DAYS, compute_start_date  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "compute_incremental_ingestion_start.py"


def _trading_days(start: date, count: int) -> list[date]:
    days = []
    current = start
    while len(days) < count:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def test_fresh_catalog_with_no_parquet_files_returns_the_fallback(tmp_path) -> None:
    empty_db_path = tmp_path / "brand_new_catalog"
    assert compute_start_date(empty_db_path, "2024-01-02") == "2024-01-02"


def test_existing_bars_shift_start_forward_by_the_overlap_window(tmp_path) -> None:
    engine = new_engine(tmp_path)
    repo = DuckDBDataRepository(engine)
    days = _trading_days(date(2024, 1, 2), 200)
    repo.append_bars(make_bars("AAPL", days, [100.0 + i for i in range(len(days))]))

    result = compute_start_date(engine.config.root_dir, "2024-01-02")

    expected = (days[-1] - timedelta(days=_OVERLAP_DAYS)).isoformat()
    assert result == expected
    assert result != "2024-01-02"  # the whole point: not the full-range fallback


def test_takes_the_global_max_across_every_security_not_per_security(tmp_path) -> None:
    engine = new_engine(tmp_path)
    repo = DuckDBDataRepository(engine)
    older_days = _trading_days(date(2024, 1, 2), 50)
    newer_days = _trading_days(date(2024, 6, 1), 50)
    repo.append_bars(make_bars("SLOW_TO_UPDATE", older_days, [100.0] * len(older_days)))
    repo.append_bars(make_bars("RECENTLY_UPDATED", newer_days, [200.0] * len(newer_days)))

    result = compute_start_date(engine.config.root_dir, "2024-01-02")

    expected = (newer_days[-1] - timedelta(days=_OVERLAP_DAYS)).isoformat()
    assert result == expected


def test_never_returns_a_date_earlier_than_the_fallback(tmp_path) -> None:
    # A catalog whose only known bars are themselves older than the
    # fallback start (e.g. a stale/partial artifact restore) must not
    # push the request further into the past than the fallback says is
    # ever needed.
    engine = new_engine(tmp_path)
    repo = DuckDBDataRepository(engine)
    days = _trading_days(date(2020, 1, 2), 10)
    repo.append_bars(make_bars("OLD_ONLY", days, [50.0] * len(days)))

    result = compute_start_date(engine.config.root_dir, "2024-01-02")

    assert result == "2024-01-02"


def test_cli_prints_the_same_value_the_function_computes(tmp_path) -> None:
    engine = new_engine(tmp_path)
    repo = DuckDBDataRepository(engine)
    days = _trading_days(date(2024, 3, 1), 30)
    repo.append_bars(make_bars("AAPL", days, [150.0] * len(days)))
    expected = compute_start_date(engine.config.root_dir, "2024-01-02")

    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--db-path", str(engine.config.root_dir), "--fallback-start", "2024-01-02"],
        capture_output=True, text=True, check=True,
    )

    assert result.stdout.strip() == expected
