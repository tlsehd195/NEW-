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

    def test_a_critical_data_quality_finding_fails_the_run_and_excludes_the_bar(self, tmp_path) -> None:
        """Session 37 (real-data DQ gap, ADR-0143): a non-finite close
        (e.g. a malformed export) is a CRITICAL-severity `non_finite_value`
        finding -- the run must now fail loudly (previously this script's
        exit code ignored quality_run.status entirely), and the affected
        bar must be excluded from get_bars() for every later reader of
        this same catalog by default."""
        module = _load_script()

        data_dir = tmp_path / "external_csvs"
        data_dir.mkdir()
        _write_csv(
            data_dir / "AAPL.csv",
            [
                {"date": "2010-01-04", "open": "10", "high": "11", "low": "9.5", "close": "10.5", "volume": "1000", "adj_close": "10.5"},
                {"date": "2010-01-05", "open": "10.5", "high": "11.5", "low": "10", "close": "nan", "volume": "1100", "adj_close": "11"},
            ],
        )
        db_path = tmp_path / "db"
        exit_code = module.main(
            [
                "--source-name", "test_external_source",
                "--data-dir", str(data_dir),
                "--symbols", "AAPL",
                "--start", "2010-01-01",
                "--end", "2010-01-31",
                "--db-path", str(db_path),
            ]
        )
        assert exit_code == 1

        manifest = json.loads((db_path / "import_manifest.json").read_text())
        assert manifest["data_quality_status"] == "CRITICAL_FAILURE"
        assert manifest["data_quality_severity_counts"]["CRITICAL"] >= 1
        # The manifest itself still reports everything actually persisted
        # (include_quality_rejected=True at the fetch site) -- it must
        # never silently under-count because of the very rejection this
        # run just recorded.
        assert manifest["total_bars_persisted"] == 2

        from storage.config import StorageConfig
        from storage.data_repository import DuckDBDataRepository
        from storage.engine import StorageEngine

        engine = StorageEngine(StorageConfig(db_path))
        repository = DuckDBDataRepository(engine)
        from datetime import datetime, timezone

        visible = repository.get_bars(
            "AAPL", datetime(2010, 1, 1, tzinfo=timezone.utc), datetime(2010, 1, 31, tzinfo=timezone.utc),
            as_of_time=datetime(2010, 1, 31, tzinfo=timezone.utc),
        )
        assert [b.timestamp.day for b in visible] == [4]
        engine.close()

    def test_a_bar_dated_exactly_on_end_is_no_longer_silently_excluded_or_flagged(self, tmp_path) -> None:
        """ADR-0167 identified a related bug but deliberately deferred
        fixing it (an independent audit later confirmed it was still
        present). `data_infra.provider.bar_available_time` stamps a
        bar's `available_time` at 20:00 UTC of its own calendar date,
        but `--end` parses to MIDNIGHT UTC. Before this fix, BOTH
        `get_bars`'s own `as_of_time` AND `quality.run()`'s `as_of_now`
        used the unshifted `args.end` -- which meant a bar dated exactly
        on `--end` (the single most common, entirely legitimate case for
        a daily ingestion run) was ALREADY excluded from `all_bars` by
        `get_bars` itself, silently under-reporting `total_bars_
        persisted`/`actual_data_end` by one real, already-persisted day,
        every run (verified directly against this exact scenario before
        the fix: `total_bars_persisted` was 1, not 2, and `actual_data_
        end` was one day behind the CSV's own real last row). Fixed by
        using `args.end + 1 day` for both call sites. This test's `--end`
        is deliberately the SAME calendar date as the CSV's last real
        row -- the exact case that previously always under-reported."""
        module = _load_script()

        data_dir = tmp_path / "external_csvs"
        data_dir.mkdir()
        _write_csv(
            data_dir / "AAPL.csv",
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
                "--symbols", "AAPL",
                "--start", "2010-01-01",
                "--end", "2010-01-05",  # exactly the last real bar's own date
                "--db-path", str(db_path),
            ]
        )
        assert exit_code == 0

        manifest = json.loads((db_path / "import_manifest.json").read_text())
        assert manifest["total_bars_persisted"] == 2  # was 1 before this fix
        assert manifest["actual_data_end"] == "2010-01-05T00:00:00+00:00"  # was 2010-01-04 before this fix
        assert manifest["data_quality_status"] == "PASSED"
        assert manifest["data_quality_issue_count"] == 0
        assert not any(i["check"] == "future_dated" for i in manifest["data_quality_issues"])

    def test_every_symbol_producing_zero_bars_fails_the_run_not_a_silent_success(self, tmp_path) -> None:
        """External audit finding (2026-09-24): IngestionRunner.run()
        marks a symbol SUCCESS whenever fetch/normalize/append raised no
        exception, even when the provider genuinely returned zero
        records for it -- legitimate for a single already-up-to-date
        symbol mid-run, but when EVERY requested symbol ends up with
        zero real bars persisted, that means nothing was ever ingested
        for anyone (a bad --source-name/--data-dir, or CSVs that were
        never actually produced) and must not report exit 0. Each CSV
        here exists (so no PermanentProviderError/FAILED status) but has
        only a header row -- the "clean but empty" case, not a missing-
        file case (already covered by the sibling test above)."""
        module = _load_script()

        data_dir = tmp_path / "external_csvs"
        data_dir.mkdir()
        _write_csv(data_dir / "AAPL.csv", [])
        _write_csv(data_dir / "MSFT.csv", [])

        db_path = tmp_path / "db"
        exit_code = module.main(
            [
                "--source-name", "test_external_source",
                "--data-dir", str(data_dir),
                "--symbols", "AAPL", "MSFT",
                "--start", "2010-01-01",
                "--end", "2010-01-31",
                "--db-path", str(db_path),
            ]
        )
        assert exit_code == 1

        manifest = json.loads((db_path / "import_manifest.json").read_text())
        assert manifest["missing_symbols"] == ["AAPL", "MSFT"]
        assert manifest["total_bars_persisted"] == 0

    def test_no_network_module_is_imported_by_this_script(self) -> None:
        source = _SCRIPT_PATH.read_text()
        for forbidden in ("import requests", "urllib.request", "http.client", "TiingoHttpTransport", "StooqHttpTransport"):
            assert forbidden not in source, f"{forbidden!r} must not appear in a script that claims to make no network call"
