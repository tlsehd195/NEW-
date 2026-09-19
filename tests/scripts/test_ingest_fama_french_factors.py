"""Real, executable tests for `scripts/ingest_fama_french_factors.py`.

The real network fetch (`fetch_zip_bytes`) is mocked -- this project
never makes real network calls from its own test suite (same
discipline as `ingest_insider_transactions.py`/
`ingest_real_market_data.py`) -- but everything downstream (CSV
parsing, benchmark-point construction, real DuckDB persistence via
`DuckDBDataRepository.add_benchmark_point`/`get_benchmark`, the
manifest) is exercised directly and for real, mirroring
`test_merge_insider_transaction_catalogs.py`'s "import the script,
call main() against a real temp catalog" pattern."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from helpers import utc

from storage.config import StorageConfig
from storage.data_repository import DuckDBDataRepository
from storage.engine import StorageEngine

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "ingest_fama_french_factors.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("ingest_fama_french_factors", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# Real, confirmed-for-real (recon run 35435103799) layout, trimmed to a
# handful of rows -- same header/blank-line structure the real file has.
_REAL_DAILY_SAMPLE = """This file was created using the 202607 CRSP database.
The Tbill return is the simple daily rate that, over the number of trading days
compounds to 1-month TBill rate. Some other footnote line.

,Mkt-RF,SMB,HML,RF
19260701,    0.09,   -0.23,   -0.28,    0.01
19260702,    0.45,   -0.34,   -0.03,    0.01
19260706,    0.17,    0.29,   -0.38,    0.01

Copyright 2026 Eugene F. Fama and Kenneth R. French
"""

_REAL_MONTHLY_SAMPLE = """This file was created using the 202607 CRSP database.
The 1-month TBill rate data until 202405 are from Ibbotson Associates.
The annual TBill return is compounded from the monthly T-bill rates.

,Mkt-RF,SMB,HML,RF
192607,   2.89,  -2.42,  -2.75,   0.22
192608,   2.64,  -1.44,   4.13,   0.25

,Mkt-RF,SMB,HML,RF
1926,  10.05,  -6.65,  -3.31,   2.90
1927,  30.30,  -8.32,  -3.36,   3.05

Copyright 2026 Eugene F. Fama and Kenneth R. French
"""


def _fake_zip(csv_name: str, csv_text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr(csv_name, csv_text)
    return buffer.getvalue()


class TestParsePeriod:
    def test_parses_eight_digit_daily_period(self) -> None:
        module = _load_module()
        assert module._parse_period("19260701") == datetime(1926, 7, 1, tzinfo=timezone.utc)

    def test_parses_six_digit_monthly_period_as_first_of_month(self) -> None:
        module = _load_module()
        assert module._parse_period("192607") == datetime(1926, 7, 1, tzinfo=timezone.utc)

    def test_rejects_unrecognized_length(self) -> None:
        module = _load_module()
        with pytest.raises(ValueError, match="unrecognized"):
            module._parse_period("1926")


class TestParseFFThreeFactorCSV:
    def test_parses_the_real_daily_layout_stopping_at_the_first_blank_line(self) -> None:
        module = _load_module()
        rows = module.parse_ff_three_factor_csv(_REAL_DAILY_SAMPLE)
        assert len(rows) == 3
        assert rows[0]["date"] == datetime(1926, 7, 1, tzinfo=timezone.utc)
        assert rows[0]["mkt_rf"] == pytest.approx(0.0009)
        assert rows[0]["smb"] == pytest.approx(-0.0023)
        assert rows[0]["hml"] == pytest.approx(-0.0028)
        assert rows[0]["rf"] == pytest.approx(0.0001)

    def test_parses_only_the_monthly_section_not_the_trailing_annual_one(self) -> None:
        module = _load_module()
        rows = module.parse_ff_three_factor_csv(_REAL_MONTHLY_SAMPLE)
        assert len(rows) == 2
        assert rows[0]["date"] == datetime(1926, 7, 1, tzinfo=timezone.utc)
        assert rows[1]["date"] == datetime(1926, 8, 1, tzinfo=timezone.utc)

    def test_missing_header_line_raises(self) -> None:
        module = _load_module()
        with pytest.raises(ValueError, match="header line"):
            module.parse_ff_three_factor_csv("no header here\n\nsome data\n")

    def test_malformed_row_raises(self) -> None:
        module = _load_module()
        bad = ",Mkt-RF,SMB,HML,RF\n19260701,0.09,-0.23\n"
        with pytest.raises(ValueError, match="5 comma-separated fields"):
            module.parse_ff_three_factor_csv(bad)


class TestBuildFactorBenchmarkPoints:
    def test_first_point_is_exactly_base_level_later_points_compound(self) -> None:
        module = _load_module()
        rows = [
            {"date": utc(2026, 1, 1), "mkt_rf": 0.01, "smb": 0.0, "hml": 0.0, "rf": 0.0},
            {"date": utc(2026, 1, 2), "mkt_rf": 0.02, "smb": 0.0, "hml": 0.0, "rf": 0.0},
        ]
        points = module.build_factor_benchmark_points("FF_DAILY_MKT_RF", rows, "mkt_rf", as_of_time=utc(2026, 9, 19))
        assert points[0].level == pytest.approx(100.0)
        assert points[1].level == pytest.approx(100.0 * 1.02)

    def test_provenance_source_record_id_is_unique_per_point(self) -> None:
        module = _load_module()
        rows = [
            {"date": utc(2026, 1, 1), "mkt_rf": 0.01, "smb": 0.0, "hml": 0.0, "rf": 0.0},
            {"date": utc(2026, 1, 2), "mkt_rf": 0.02, "smb": 0.0, "hml": 0.0, "rf": 0.0},
        ]
        points = module.build_factor_benchmark_points("FF_DAILY_MKT_RF", rows, "mkt_rf", as_of_time=utc(2026, 9, 19))
        ids = {p.provenance.source_record_id for p in points}
        assert len(ids) == 2


class TestMainEndToEnd:
    def _patch_fetch(self, monkeypatch, module, csv_name: str, csv_text: str) -> None:
        zip_bytes = _fake_zip(csv_name, csv_text)
        monkeypatch.setattr(module, "fetch_zip_bytes", lambda url: zip_bytes)

    def test_ingests_all_four_real_factor_series_into_a_real_catalog(self, tmp_path, monkeypatch, capsys) -> None:
        module = _load_module()
        self._patch_fetch(monkeypatch, module, "F-F_Research_Data_Factors_daily.CSV", _REAL_DAILY_SAMPLE)
        db_path = tmp_path / "ff_catalog"

        exit_code = module.main([
            "--frequency", "daily", "--as-of", "2026-09-19", "--db-path", str(db_path),
        ])
        assert exit_code == 0

        engine = StorageEngine(StorageConfig(root_dir=db_path))
        repository = DuckDBDataRepository(engine)
        points = repository.get_benchmark("FF_DAILY_SMB", utc(1900, 1, 1), utc(2100, 1, 1), as_of_time=utc(2100, 1, 1))
        assert len(points) == 3
        assert points[0].level == pytest.approx(100.0)
        engine.close()

        manifest = json.loads((db_path / "fama_french_ingestion_manifest.json").read_text())
        assert manifest["row_count"] == 3
        assert manifest["frequency"] == "daily"
        assert manifest["benchmark_ids"]["smb"] == "FF_DAILY_SMB"

    def test_running_twice_is_idempotent(self, tmp_path, monkeypatch) -> None:
        module = _load_module()
        self._patch_fetch(monkeypatch, module, "data.CSV", _REAL_DAILY_SAMPLE)
        db_path = tmp_path / "ff_catalog"

        module.main(["--frequency", "daily", "--as-of", "2026-09-19", "--db-path", str(db_path)])
        module.main(["--frequency", "daily", "--as-of", "2026-09-19", "--db-path", str(db_path)])

        engine = StorageEngine(StorageConfig(root_dir=db_path))
        repository = DuckDBDataRepository(engine)
        points = repository.get_benchmark("FF_DAILY_MKT_RF", utc(1900, 1, 1), utc(2100, 1, 1), as_of_time=utc(2100, 1, 1))
        assert len(points) == 3  # not duplicated
        engine.close()

    def test_monthly_frequency_uses_its_own_benchmark_ids(self, tmp_path, monkeypatch) -> None:
        module = _load_module()
        self._patch_fetch(monkeypatch, module, "data.CSV", _REAL_MONTHLY_SAMPLE)
        db_path = tmp_path / "ff_catalog"

        exit_code = module.main(["--frequency", "monthly", "--as-of", "2026-09-19", "--db-path", str(db_path)])
        assert exit_code == 0

        engine = StorageEngine(StorageConfig(root_dir=db_path))
        repository = DuckDBDataRepository(engine)
        monthly_points = repository.get_benchmark("FF_MONTHLY_HML", utc(1900, 1, 1), utc(2100, 1, 1), as_of_time=utc(2100, 1, 1))
        daily_points = repository.get_benchmark("FF_DAILY_HML", utc(1900, 1, 1), utc(2100, 1, 1), as_of_time=utc(2100, 1, 1))
        assert len(monthly_points) == 2
        assert len(daily_points) == 0
        engine.close()

    def test_fetch_failure_is_fatal_not_silent(self, tmp_path, monkeypatch, capsys) -> None:
        module = _load_module()

        def _raise(url):
            raise module.urllib.error.URLError("egress blocked")

        monkeypatch.setattr(module, "fetch_zip_bytes", _raise)
        exit_code = module.main(["--as-of", "2026-09-19", "--db-path", str(tmp_path / "ff_catalog")])
        assert exit_code == 1
        assert "FATAL" in capsys.readouterr().err

    def test_parse_failure_is_fatal_not_silent(self, tmp_path, monkeypatch, capsys) -> None:
        module = _load_module()
        self._patch_fetch(monkeypatch, module, "data.CSV", "no header at all\n\njunk\n")
        exit_code = module.main(["--as-of", "2026-09-19", "--db-path", str(tmp_path / "ff_catalog")])
        assert exit_code == 1
        assert "FATAL" in capsys.readouterr().err
