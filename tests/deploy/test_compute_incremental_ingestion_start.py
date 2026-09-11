"""ADR-0085: scripts/compute_incremental_ingestion_start.py must never
re-request the full historical range once a catalog already has real
bars -- the real bug this exists to fix (Tiingo rate-limit exhaustion
partway through 88 symbols' ~2.5-year history, leaving SPY and 9
others with zero bars) recurred every single scheduled run precisely
because the old workflow always requested the full range regardless of
what the catalog already held.

ADR-0115: the original implementation computed a single catalog-wide
MAX(timestamp) across every symbol, not per symbol requested by this
run -- so a symbol left with ZERO bars by a prior partial-failure run
(the exact scenario this script exists to auto-heal) never widened the
computed start date backward, since it contributed no rows at all, and
its true gap was silently never re-requested on any later run. This
file's tests were updated accordingly (one, `test_takes_the_global_
max...`, was itself pinning that exact bug as intended behavior --
rewritten below to prove the fix instead)."""
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
    assert compute_start_date(empty_db_path, "2024-01-02", ["AAPL"]) == "2024-01-02"


def test_existing_bars_shift_start_forward_by_the_overlap_window(tmp_path) -> None:
    engine = new_engine(tmp_path)
    repo = DuckDBDataRepository(engine)
    days = _trading_days(date(2024, 1, 2), 200)
    repo.append_bars(make_bars("AAPL", days, [100.0 + i for i in range(len(days))]))

    result = compute_start_date(engine.config.root_dir, "2024-01-02", ["AAPL"])

    expected = (days[-1] - timedelta(days=_OVERLAP_DAYS)).isoformat()
    assert result == expected
    assert result != "2024-01-02"  # the whole point: not the full-range fallback


def test_takes_the_minimum_across_requested_symbols_not_the_global_max(tmp_path) -> None:
    # ADR-0115: the least-caught-up REQUESTED symbol must drive the
    # start date, not whichever symbol happens to have the most recent
    # bars -- otherwise a symbol lagging behind the rest of the catalog
    # never gets its own real gap re-requested.
    engine = new_engine(tmp_path)
    repo = DuckDBDataRepository(engine)
    older_days = _trading_days(date(2024, 1, 2), 50)
    newer_days = _trading_days(date(2024, 6, 1), 50)
    repo.append_bars(make_bars("SLOW_TO_UPDATE", older_days, [100.0] * len(older_days)))
    repo.append_bars(make_bars("RECENTLY_UPDATED", newer_days, [200.0] * len(newer_days)))

    result = compute_start_date(
        engine.config.root_dir, "2024-01-02", ["SLOW_TO_UPDATE", "RECENTLY_UPDATED"],
    )

    expected = (older_days[-1] - timedelta(days=_OVERLAP_DAYS)).isoformat()
    assert result == expected


def test_a_symbol_absent_from_the_catalog_entirely_forces_the_full_fallback(tmp_path) -> None:
    # The exact bug scenario this script exists to auto-heal: a prior
    # run's rate-limit exhaustion left one requested symbol with ZERO
    # bars. Even though most of the catalog is recently updated, that
    # one missing symbol's true gap spans back to the fallback start,
    # and must not be silently skipped just because it contributes no
    # rows to the MAX(timestamp) query.
    engine = new_engine(tmp_path)
    repo = DuckDBDataRepository(engine)
    recent_days = _trading_days(date(2024, 6, 1), 50)
    repo.append_bars(make_bars("MOSTLY_FINE", recent_days, [200.0] * len(recent_days)))

    result = compute_start_date(
        engine.config.root_dir, "2024-01-02", ["MOSTLY_FINE", "GOT_ZERO_BARS_LAST_RUN"],
    )

    assert result == "2024-01-02"


def test_a_symbol_not_requested_this_run_does_not_affect_the_result(tmp_path) -> None:
    # Only the symbols actually passed in `symbols` should matter --
    # an old, unrelated symbol's stale bars in the same catalog must
    # not drag the start date backward for a run that isn't requesting it.
    engine = new_engine(tmp_path)
    repo = DuckDBDataRepository(engine)
    old_unrelated_days = _trading_days(date(2020, 1, 2), 10)
    requested_days = _trading_days(date(2024, 6, 1), 50)
    repo.append_bars(make_bars("NOT_REQUESTED_THIS_RUN", old_unrelated_days, [50.0] * len(old_unrelated_days)))
    repo.append_bars(make_bars("REQUESTED", requested_days, [200.0] * len(requested_days)))

    result = compute_start_date(engine.config.root_dir, "2024-01-02", ["REQUESTED"])

    expected = (requested_days[-1] - timedelta(days=_OVERLAP_DAYS)).isoformat()
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

    result = compute_start_date(engine.config.root_dir, "2024-01-02", ["OLD_ONLY"])

    assert result == "2024-01-02"


def test_cli_prints_the_same_value_the_function_computes(tmp_path) -> None:
    engine = new_engine(tmp_path)
    repo = DuckDBDataRepository(engine)
    days = _trading_days(date(2024, 3, 1), 30)
    repo.append_bars(make_bars("AAPL", days, [150.0] * len(days)))
    expected = compute_start_date(engine.config.root_dir, "2024-01-02", ["AAPL"])

    result = subprocess.run(
        [
            sys.executable, str(SCRIPT_PATH),
            "--db-path", str(engine.config.root_dir),
            "--fallback-start", "2024-01-02",
            "--symbols", "AAPL",
        ],
        capture_output=True, text=True, check=True,
    )

    assert result.stdout.strip() == expected


def test_cli_default_universe_resolves_to_a_real_symbol_list(tmp_path) -> None:
    # Without --symbols, the CLI falls back to --universe (default
    # PILOT_UNIVERSE) plus the benchmark symbol -- matching
    # ingest_real_market_data.py's own resolution, so the two scripts
    # agree on which symbols this run actually covers.
    empty_db_path = tmp_path / "brand_new_catalog"
    result = subprocess.run(
        [
            sys.executable, str(SCRIPT_PATH),
            "--db-path", str(empty_db_path),
            "--fallback-start", "2024-01-02",
        ],
        capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == "2024-01-02"
