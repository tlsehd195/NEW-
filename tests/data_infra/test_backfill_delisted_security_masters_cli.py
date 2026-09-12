"""Real, executable tests for `scripts/backfill_delisted_security_
masters.py`. Makes no network call -- reads/writes only a local DuckDB
catalog -- so it is run end to end against a real on-disk catalog
populated via the existing, unmodified `scripts/import_external_
market_data.py` pipeline, the same discipline `test_report_
survivorship_price_coverage_cli.py` already established."""

from __future__ import annotations

import csv
import importlib.util
from datetime import datetime, timezone
from pathlib import Path


def _load_script(name: str, filename: str):
    path = Path(__file__).resolve().parents[2] / "scripts" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_price_csv(path: Path, rows: list[dict]) -> None:
    columns = ("date", "open", "high", "low", "close", "volume", "adj_close")
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _populate_real_db(tmp_path: Path) -> Path:
    import_module = _load_script("import_external_market_data", "import_external_market_data.py")
    data_dir = tmp_path / "csvs"
    data_dir.mkdir()
    _write_price_csv(
        data_dir / "DELL.csv",
        [
            {"date": "2013-10-28", "open": "13.84", "high": "13.85", "low": "13.82", "close": "13.83", "volume": "130524200", "adj_close": "13.83"},
            {"date": "2013-10-29", "open": "13.85", "high": "13.87", "low": "13.83", "close": "13.86", "volume": "65719400", "adj_close": "13.86"},
        ],
    )
    db_path = tmp_path / "db"
    exit_code = import_module.main(
        ["--source-name", "test_source", "--data-dir", str(data_dir), "--symbols", "DELL", "--start", "2013-01-01", "--end", "2013-12-31", "--db-path", str(db_path)]
    )
    assert exit_code == 0
    return db_path


class TestBackfillDelistedSecurityMastersCli:
    def test_backfills_a_real_security_master_from_real_bars(self, tmp_path) -> None:
        db_path = _populate_real_db(tmp_path)
        module = _load_script("backfill_delisted_security_masters", "backfill_delisted_security_masters.py")

        exit_code = module.main(["--db-path", str(db_path), "--symbols", "DELL", "--as-of", "2026-01-01"])
        assert exit_code == 0

        # Verify the record is actually queryable now via get_security -- the exact gap this closes.
        from storage.config import StorageConfig
        from storage.data_repository import DuckDBDataRepository
        from storage.engine import StorageEngine

        engine = StorageEngine(StorageConfig(root_dir=db_path))
        try:
            repository = DuckDBDataRepository(engine)
            security = repository.get_security("DELL", datetime(2013, 10, 29, tzinfo=timezone.utc))
            assert security is not None
            assert security.status.name == "DELISTED"
        finally:
            engine.close()

    def test_symbol_with_no_real_bars_is_skipped_and_fatal_if_all_skipped(self, tmp_path) -> None:
        db_path = _populate_real_db(tmp_path)
        module = _load_script("backfill_delisted_security_masters", "backfill_delisted_security_masters.py")

        exit_code = module.main(["--db-path", str(db_path), "--symbols", "NOSUCHTICKER", "--as-of", "2026-01-01"])
        assert exit_code == 1

    def test_one_missing_symbol_among_several_does_not_fail_the_whole_run(self, tmp_path) -> None:
        db_path = _populate_real_db(tmp_path)
        module = _load_script("backfill_delisted_security_masters", "backfill_delisted_security_masters.py")

        exit_code = module.main(["--db-path", str(db_path), "--symbols", "DELL", "NOSUCHTICKER", "--as-of", "2026-01-01"])
        assert exit_code == 0

    def test_missing_db_path_fails_with_nonzero_exit(self, tmp_path) -> None:
        module = _load_script("backfill_delisted_security_masters", "backfill_delisted_security_masters.py")
        exit_code = module.main(["--db-path", str(tmp_path / "nope"), "--symbols", "DELL", "--as-of", "2026-01-01"])
        assert exit_code == 1

    def test_no_network_module_is_imported_by_this_script(self) -> None:
        source = (Path(__file__).resolve().parents[2] / "scripts" / "backfill_delisted_security_masters.py").read_text()
        for forbidden in ("import requests", "urllib.request", "http.client"):
            assert forbidden not in source, f"{forbidden!r} must not appear in a script that claims to make no network call"
