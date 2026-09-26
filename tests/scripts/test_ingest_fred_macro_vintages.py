"""Category: coverage report of `scripts/ingest_fred_macro_vintages.py`
(ADR-0217) -- pure summary logic, no network."""

from __future__ import annotations

import importlib.util
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from data_infra.providers.fred import FredVintageObservation

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "ingest_fred_macro_vintages.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("ingest_fred_macro_vintages", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _obs(obs, value, start):
    return FredVintageObservation("CPIAUCSL", obs, value, start, None, datetime(2026, 9, 26, tzinfo=timezone.utc))


def test_coverage_summary_separates_pre_archive_rows_from_real_release_lags() -> None:
    module = _load_module()
    rows = [
        # Before the first archived vintage: all stamped 2000-01-14.
        _obs(date(1999, 11, 1), 1.0, date(2000, 1, 14)),
        _obs(date(1999, 12, 1), 2.0, date(2000, 1, 14)),
        # Real releases after that, one revised.
        _obs(date(2000, 1, 1), 3.0, date(2000, 2, 15)),
        _obs(date(2000, 1, 1), 3.1, date(2000, 3, 16)),
        _obs(date(2000, 2, 1), 4.0, date(2000, 3, 16)),
    ]
    summary = module.coverage_summary("CPIAUCSL", rows)
    assert summary["first_vintage_date"] == "2000-01-14"
    assert summary["observations_stamped_with_first_vintage"] == 2
    assert summary["median_release_lag_days"] == 44.5  # 45 and 44 days
    assert summary["revised_observation_share"] == 0.25
    assert summary["distinct_vintages"] == 3


def test_coverage_summary_of_empty_series() -> None:
    assert _load_module().coverage_summary("X", []) == {"series_id": "X", "vintage_rows": 0}
