"""Real, executable tests for `scripts/rescan_data_quality.py` (Session
37, ADR-0144).

Like `scripts/import_external_market_data.py`, this script makes NO
network call -- it only reads an already-persisted local DuckDB/Parquet
catalog -- so it is safe and appropriate to actually run `main()` here
end to end, against a real on-disk catalog built directly through
`DuckDBDataRepository.append_bars()` (the same real persistence path
`scripts/ingest_real_market_data.py` itself writes through).
"""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path

from test_data_repository_persistence import make_bar

from storage.config import StorageConfig
from storage.data_repository import DuckDBDataRepository
from storage.engine import StorageEngine

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "rescan_data_quality.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("rescan_data_quality", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestRescanDataQualityCli:
    def test_a_pre_existing_critical_bar_is_flagged_and_excluded_after_rescan(self, tmp_path) -> None:
        db_path = tmp_path / "catalog"
        engine = StorageEngine(StorageConfig(db_path))
        repo = DuckDBDataRepository(engine)
        good = make_bar("AAA", date(2024, 1, 2), 100.0)
        bad = dataclasses.replace(make_bar("AAA", date(2024, 1, 3), 100.0), close=math.nan)
        repo.append_bars([good, bad])
        # Simulates the real gap this rescan closes: the bad bar was
        # persisted by an earlier (pre-ADR-0143) run and never quality
        # checked -- get_bars() still returns it, unfiltered, right now.
        before = repo.get_bars("AAA", datetime(2024, 1, 1, tzinfo=timezone.utc), datetime(2024, 1, 31, tzinfo=timezone.utc), as_of_time=datetime(2024, 1, 31, tzinfo=timezone.utc))
        assert len(before) == 2
        engine.close()

        module = _load_script()
        out_path = tmp_path / "report.json"
        exit_code = module.main(["--db-path", str(db_path), "--out", str(out_path)])
        assert exit_code == 1

        report = json.loads(out_path.read_text())
        assert report["bars_scanned"] == 2
        assert report["data_quality_status"] == "CRITICAL_FAILURE"
        assert report["data_quality_severity_counts"]["CRITICAL"] >= 1
        assert report["data_quality_flags_persisted"] >= 1

        engine2 = StorageEngine(StorageConfig(db_path))
        repo2 = DuckDBDataRepository(engine2)
        after = repo2.get_bars("AAA", datetime(2024, 1, 1, tzinfo=timezone.utc), datetime(2024, 1, 31, tzinfo=timezone.utc), as_of_time=datetime(2024, 1, 31, tzinfo=timezone.utc))
        assert [b.timestamp.day for b in after] == [2]
        engine2.close()

    def test_an_empty_catalog_is_a_clean_no_op(self, tmp_path) -> None:
        db_path = tmp_path / "catalog"
        engine = StorageEngine(StorageConfig(db_path))
        engine.close()

        module = _load_script()
        out_path = tmp_path / "report.json"
        exit_code = module.main(["--db-path", str(db_path), "--out", str(out_path)])
        assert exit_code == 0

        report = json.loads(out_path.read_text())
        assert report["bars_scanned"] == 0

    def test_only_warning_or_error_findings_do_not_fail_the_run(self, tmp_path) -> None:
        db_path = tmp_path / "catalog"
        engine = StorageEngine(StorageConfig(db_path))
        repo = DuckDBDataRepository(engine)
        # Same (security_id, timestamp, source), different data_version --
        # a provider revision (ADR-0085's overlap re-fetch), WARNING
        # severity as of ADR-0168, not CRITICAL.
        dupe_a = make_bar("AAA", date(2024, 1, 3), 100.0, source="s1", data_version="v1")
        dupe_b = make_bar("AAA", date(2024, 1, 3), 101.0, source="s1", data_version="v2")
        repo.append_bars([dupe_a, dupe_b])
        engine.close()

        module = _load_script()
        out_path = tmp_path / "report.json"
        exit_code = module.main(["--db-path", str(db_path), "--out", str(out_path)])
        assert exit_code == 0

        report = json.loads(out_path.read_text())
        assert report["data_quality_status"] == "PASSED_WITH_WARNINGS"
        assert report["data_quality_severity_counts"]["CRITICAL"] == 0

    def test_running_the_rescan_twice_is_idempotent(self, tmp_path) -> None:
        db_path = tmp_path / "catalog"
        engine = StorageEngine(StorageConfig(db_path))
        repo = DuckDBDataRepository(engine)
        bad = dataclasses.replace(make_bar("AAA", date(2024, 1, 3), 100.0), close=math.nan)
        repo.append_bars([bad])
        engine.close()

        module = _load_script()
        out_path = tmp_path / "report.json"
        first = module.main(["--db-path", str(db_path), "--out", str(out_path)])
        second = module.main(["--db-path", str(db_path), "--out", str(out_path)])
        assert first == second == 1

        report = json.loads(out_path.read_text())
        assert report["data_quality_flags_persisted"] >= 1

    def test_no_network_module_is_imported_by_this_script(self) -> None:
        source = _SCRIPT_PATH.read_text()
        for forbidden in ("import requests", "urllib.request", "http.client", "TiingoHttpTransport", "StooqHttpTransport"):
            assert forbidden not in source, f"{forbidden!r} must not appear in a script that claims to make no network call"
