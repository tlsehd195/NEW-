"""Real, executable tests for `scripts/import_external_market_data.py`
(Phase 31, instruction section 21).

Unlike `scripts/ingest_real_market_data.py` (never imported/executed by
the suite -- it makes a real network call), this script makes NO
network call at all (it reads local CSV files via
`LocalFileDataProvider`), so it is safe and appropriate to actually
run `main()` here, end to end, against real temp-directory CSV
fixtures and a real on-disk DuckDB catalog -- the strongest test this
project's own conventions allow for a CLI script.

These are SYNTHETIC pipeline tests: the CSV content is fabricated by
the test itself for determinism. They prove the import CLI mechanism
works correctly, not that any real external dataset has been acquired
(none has this phase; see
docs/decisions/ADR-0034-real-data-acquisition-strategy.md).
"""

from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "import_external_market_data.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("import_external_market_data", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_csv(path, rows):
    columns = ("date", "open", "high", "low", "close", "volume", "adj_close")
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


class TestImportExternalMarketDataCli:
    def test_main_runs_end_to_end_and_writes_a_manifest_with_all_required_fields(self, tmp_path) -> None:
        module = _load_script()

        data_dir = tmp_path / "external_csvs"
        data_dir.mkdir()
        for symbol in ("AAPL", "MSFT", "SPY"):
            _write_csv(
                data_dir / f"{symbol}.csv",
                [
                    {"date": "2010-01-04", "open": "10", "high": "11", "low": "9.5", "close": "10.5", "volume": "1000", "adj_close": "10.5"},
                    {"date": "2010-01-05", "open": "10.5", "high": "11.5", "low": "10", "close": "11", "volume": "1100", "adj_close": "11"},
                ],
            )

        db_path = tmp_path / "db"
        exit_code = module.main(
            [
                "--source-name", "test_external_source",
                "--data-dir", str(data_dir),
                "--symbols", "AAPL", "MSFT", "SPY",
                "--start", "2010-01-01",
                "--end", "2010-01-31",
                "--db-path", str(db_path),
            ]
        )
        assert exit_code == 0

        manifest_path = db_path / "import_manifest.json"
        assert manifest_path.is_file()
        manifest = json.loads(manifest_path.read_text())

        assert manifest["data_status"] == "REAL"
        assert manifest["source_name"] == "test_external_source"
        assert manifest["symbol_count"] == 3
        assert manifest["total_bars_persisted"] == 6
        assert manifest["missing_symbols"] == []
        assert manifest["providers_used"] == ["test_external_source"]
        assert manifest["actual_data_start"] == "2010-01-04T00:00:00+00:00"
        assert manifest["actual_data_end"] == "2010-01-05T00:00:00+00:00"
        assert manifest["requested_start"] == "2010-01-01T00:00:00+00:00"
        assert manifest["content_checksum"]
        assert manifest["data_version"] == manifest["content_checksum"]

    def test_missing_csv_for_a_requested_symbol_is_reported_not_silently_dropped(self, tmp_path) -> None:
        module = _load_script()

        data_dir = tmp_path / "external_csvs"
        data_dir.mkdir()
        _write_csv(
            data_dir / "AAPL.csv",
            [{"date": "2010-01-04", "open": "10", "high": "11", "low": "9.5", "close": "10.5", "volume": "1000", "adj_close": "10.5"}],
        )
        db_path = tmp_path / "db"
        exit_code = module.main(
            [
                "--source-name", "test_external_source",
                "--data-dir", str(data_dir),
                "--symbols", "AAPL", "NOFILE",
                "--start", "2010-01-01",
                "--end", "2010-01-31",
                "--db-path", str(db_path),
            ]
        )
        assert exit_code == 1  # PARTIAL_SUCCESS is not "SUCCESS"

        manifest = json.loads((db_path / "import_manifest.json").read_text())
        assert manifest["missing_symbols"] == ["NOFILE"]
        failed = [r for r in manifest["per_symbol_results"] if r["security_id"] == "NOFILE"]
        assert failed[0]["status"] == "FAILED"
        assert failed[0]["error"] is not None

    def test_no_network_module_is_imported_by_this_script(self) -> None:
        source = _SCRIPT_PATH.read_text()
        for forbidden in ("import requests", "urllib.request", "http.client", "TiingoHttpTransport", "StooqHttpTransport"):
            assert forbidden not in source, f"{forbidden!r} must not appear in a script that claims to make no network call"
