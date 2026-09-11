"""Real, executable tests for `scripts/ingest_short_interest_data.py`
(Session 36 continued, ADR-0099).

Mirrors `test_import_external_market_data_cli.py`'s own reasoning
exactly: this script makes NO network call at all (it reads local CSV
files via `data_infra.providers.short_interest_file_import`), so it is
safe and appropriate to actually run `main()` here, end to end, against
real temp-directory CSV fixtures and a real on-disk DuckDB catalog.

These are SYNTHETIC pipeline tests: the CSV content is fabricated by
the test itself for determinism. They prove the import CLI mechanism
works correctly, not that any real FINRA short interest data has been
acquired (none has -- see `data_infra.short_interest_models`'s own
module docstring for why)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "ingest_short_interest_data.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("ingest_short_interest_data", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_csv(data_dir: Path, security_id: str, rows: list[str]) -> None:
    header = "settlement_date,short_interest_quantity,average_daily_volume,days_to_cover\n"
    (data_dir / f"{security_id}.csv").write_text(header + "\n".join(rows) + "\n")


class TestIngestShortInterestDataCli:
    def test_main_runs_end_to_end_and_writes_a_manifest_with_all_required_fields(self, tmp_path) -> None:
        module = _load_script()

        data_dir = tmp_path / "short_interest_csvs"
        data_dir.mkdir()
        _write_csv(data_dir, "AAA", ["2026-07-31,80000,40000,2.0", "2026-08-15,100000,50000,2.0"])
        _write_csv(data_dir, "BBB", ["2026-08-15,200000,100000,2.0"])

        db_path = tmp_path / "db"
        exit_code = module.main(
            [
                "--source-name", "finra_manual_export",
                "--data-dir", str(data_dir),
                "--symbols", "AAA", "BBB",
                "--as-of", "2026-09-03",
                "--db-path", str(db_path),
            ]
        )
        assert exit_code == 0

        manifest_path = db_path / "short_interest_ingestion_manifest.json"
        assert manifest_path.is_file()
        manifest = json.loads(manifest_path.read_text())

        assert manifest["data_status"] == "REAL"
        assert manifest["source_name"] == "finra_manual_export"
        assert manifest["symbol_count"] == 2
        assert manifest["total_records_persisted"] == 3
        assert manifest["missing_symbols"] == []
        assert manifest["content_checksum"]
        assert manifest["data_version"] == manifest["content_checksum"]

        from storage.config import StorageConfig
        from storage.engine import StorageEngine
        from storage.short_interest_repository import DuckDBShortInterestRepository
        from helpers import utc

        engine = StorageEngine(StorageConfig(root_dir=db_path))
        repository = DuckDBShortInterestRepository(engine)
        latest = repository.get_latest_short_interest("AAA", utc(2026, 12, 31))
        assert latest is not None
        assert latest.short_interest_quantity == 100000.0
        engine.close()

    def test_missing_csv_for_a_requested_symbol_is_reported_not_silently_dropped(self, tmp_path) -> None:
        module = _load_script()

        data_dir = tmp_path / "short_interest_csvs"
        data_dir.mkdir()
        _write_csv(data_dir, "AAA", ["2026-08-15,100000,50000,2.0"])

        db_path = tmp_path / "db"
        exit_code = module.main(
            [
                "--source-name", "finra_manual_export",
                "--data-dir", str(data_dir),
                "--symbols", "AAA", "NOFILE",
                "--as-of", "2026-09-03",
                "--db-path", str(db_path),
            ]
        )
        assert exit_code == 1

        manifest = json.loads((db_path / "short_interest_ingestion_manifest.json").read_text())
        assert manifest["missing_symbols"] == ["NOFILE"]
        failed = [r for r in manifest["per_symbol_results"] if r["security_id"] == "NOFILE"]
        assert failed[0]["records_persisted"] == 0
        assert failed[0]["error"] is not None

    def test_no_network_module_is_imported_by_this_script(self) -> None:
        source = _SCRIPT_PATH.read_text()
        for forbidden in ("import requests", "urllib.request", "http.client"):
            assert forbidden not in source, f"{forbidden!r} must not appear in a script that claims to make no network call"


class TestIngestShortInterestDataCliCombinedCsv:
    def _write_combined_csv(self, tmp_path: Path, rows: list[str]) -> Path:
        header = "security_id,settlement_date,short_interest_quantity,average_daily_volume,days_to_cover\n"
        path = tmp_path / "combined.csv"
        path.write_text(header + "\n".join(rows) + "\n")
        return path

    def test_combined_csv_runs_end_to_end_without_per_symbol_files(self, tmp_path) -> None:
        module = _load_script()
        combined_csv = self._write_combined_csv(
            tmp_path,
            ["AAA,2026-07-31,80000,40000,2.0", "AAA,2026-08-15,100000,50000,2.0", "BBB,2026-08-15,200000,100000,2.0"],
        )

        db_path = tmp_path / "db"
        exit_code = module.main(
            [
                "--source-name", "finra_manual_export",
                "--combined-csv", str(combined_csv),
                "--symbols", "AAA", "BBB",
                "--as-of", "2026-09-03",
                "--db-path", str(db_path),
            ]
        )
        assert exit_code == 0

        manifest = json.loads((db_path / "short_interest_ingestion_manifest.json").read_text())
        assert manifest["combined_csv"] == str(combined_csv)
        assert manifest["data_dir"] is None
        assert manifest["total_records_persisted"] == 3
        assert manifest["missing_symbols"] == []

    def test_symbol_absent_from_combined_csv_is_reported_as_missing(self, tmp_path) -> None:
        module = _load_script()
        combined_csv = self._write_combined_csv(tmp_path, ["AAA,2026-08-15,100000,50000,2.0"])

        db_path = tmp_path / "db"
        exit_code = module.main(
            [
                "--source-name", "finra_manual_export",
                "--combined-csv", str(combined_csv),
                "--symbols", "AAA", "NOFILE",
                "--as-of", "2026-09-03",
                "--db-path", str(db_path),
            ]
        )
        assert exit_code == 1

        manifest = json.loads((db_path / "short_interest_ingestion_manifest.json").read_text())
        assert manifest["missing_symbols"] == ["NOFILE"]

    def test_neither_data_dir_nor_combined_csv_is_rejected(self, tmp_path) -> None:
        module = _load_script()
        exit_code = module.main(
            [
                "--source-name", "finra_manual_export",
                "--symbols", "AAA",
                "--as-of", "2026-09-03",
                "--db-path", str(tmp_path / "db"),
            ]
        )
        assert exit_code == 1

    def test_both_data_dir_and_combined_csv_is_rejected(self, tmp_path) -> None:
        module = _load_script()
        data_dir = tmp_path / "csvs"
        data_dir.mkdir()
        combined_csv = self._write_combined_csv(tmp_path, ["AAA,2026-08-15,100000,50000,2.0"])
        exit_code = module.main(
            [
                "--source-name", "finra_manual_export",
                "--data-dir", str(data_dir),
                "--combined-csv", str(combined_csv),
                "--symbols", "AAA",
                "--as-of", "2026-09-03",
                "--db-path", str(tmp_path / "db"),
            ]
        )
        assert exit_code == 1
