"""Real, executable tests for `scripts/report_survivorship_price_
coverage.py` (Session 37 continued, "완전 해결" follow-up: wiring
ADR-0126/ADR-0128's real delisted-price data into an actual, queryable
coverage measurement instead of leaving it as isolated CSVs).

Makes no network call (reads a local CSV, queries a local DuckDB) --
run end to end against a real on-disk DuckDB catalog populated via the
existing, unmodified `scripts/import_external_market_data.py` pipeline,
the same "real executable test" discipline `test_import_external_
market_data_cli.py` already established."""

from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path


def _load_script(name: str, filename: str):
    path = Path(__file__).resolve().parents[2] / "scripts" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_intervals_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=("ticker", "start_date", "end_date"))
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_price_csv(path: Path, rows: list[dict]) -> None:
    columns = ("date", "open", "high", "low", "close", "volume", "adj_close")
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


class TestReportSurvivorshipPriceCoverageCli:
    def test_end_to_end_against_a_real_duckdb_populated_via_the_existing_import_pipeline(self, tmp_path) -> None:
        # 1. Populate a real DuckDB catalog with real bars for ONE of two removed tickers,
        #    using the existing, unmodified external-import pipeline (ADR-0126/ADR-0128's own path).
        import_module = _load_script("import_external_market_data", "import_external_market_data.py")

        data_dir = tmp_path / "csvs"
        data_dir.mkdir()
        _write_price_csv(
            data_dir / "DELL.csv",
            [{"date": "2013-10-29", "open": "13.85", "high": "13.87", "low": "13.83", "close": "13.86", "volume": "65719400", "adj_close": "13.86"}],
        )

        db_path = tmp_path / "db"
        exit_code = import_module.main(
            [
                "--source-name", "test_source",
                "--data-dir", str(data_dir),
                "--symbols", "DELL",
                "--start", "2013-01-01",
                "--end", "2013-12-31",
                "--db-path", str(db_path),
            ]
        )
        assert exit_code == 0

        # 2. A real S&P 500 interval file naming TWO removed tickers -- only one (DELL) has real bars.
        intervals_csv = tmp_path / "sp500_ticker_start_end.csv"
        _write_intervals_csv(
            intervals_csv,
            [
                {"ticker": "DELL", "start_date": "1988-08-17", "end_date": "2013-10-29"},
                {"ticker": "LEH", "start_date": "1996-01-02", "end_date": "2008-09-15"},
            ],
        )

        # 3. Run the new coverage-report script against the real DuckDB.
        coverage_module = _load_script("report_survivorship_price_coverage", "report_survivorship_price_coverage.py")
        out_path = tmp_path / "coverage_report.json"
        exit_code = coverage_module.main(
            [
                "--sp500-intervals-csv", str(intervals_csv),
                "--db-path", str(db_path),
                "--since", "2000-01-01",
                "--as-of", "2026-01-01",
                "--out", str(out_path),
            ]
        )
        assert exit_code == 0

        report = json.loads(out_path.read_text())
        assert report["checked_ticker_count"] == 2
        assert report["covered_ticker_count"] == 1
        assert report["not_covered_ticker_count"] == 1
        assert report["covered_tickers"] == ["DELL"]
        assert report["not_covered_tickers"] == ["LEH"]
        assert report["coverage_percentage"] == 50.0

    def test_missing_intervals_file_fails_with_nonzero_exit(self, tmp_path) -> None:
        module = _load_script("report_survivorship_price_coverage", "report_survivorship_price_coverage.py")
        exit_code = module.main(
            [
                "--sp500-intervals-csv", str(tmp_path / "nope.csv"),
                "--db-path", str(tmp_path / "db"),
                "--since", "2000-01-01",
                "--as-of", "2026-01-01",
                "--out", str(tmp_path / "out.json"),
            ]
        )
        assert exit_code == 1

    def test_missing_db_path_fails_with_nonzero_exit(self, tmp_path) -> None:
        module = _load_script("report_survivorship_price_coverage", "report_survivorship_price_coverage.py")
        intervals_csv = tmp_path / "sp500_ticker_start_end.csv"
        _write_intervals_csv(intervals_csv, [{"ticker": "DELL", "start_date": "1988-08-17", "end_date": "2013-10-29"}])

        exit_code = module.main(
            [
                "--sp500-intervals-csv", str(intervals_csv),
                "--db-path", str(tmp_path / "nonexistent_db"),
                "--since", "2000-01-01",
                "--as-of", "2026-01-01",
                "--out", str(tmp_path / "out.json"),
            ]
        )
        assert exit_code == 1

    def test_no_qualifying_removed_tickers_fails_with_nonzero_exit(self, tmp_path) -> None:
        module = _load_script("report_survivorship_price_coverage", "report_survivorship_price_coverage.py")
        intervals_csv = tmp_path / "sp500_ticker_start_end.csv"
        # Only a still-current member (end_date empty) -- nothing qualifies for --since.
        _write_intervals_csv(intervals_csv, [{"ticker": "AAPL", "start_date": "1996-01-02", "end_date": ""}])

        db_path = tmp_path / "db"
        import_module = _load_script("import_external_market_data", "import_external_market_data.py")
        data_dir = tmp_path / "csvs"
        data_dir.mkdir()
        _write_price_csv(
            data_dir / "AAPL.csv",
            [{"date": "2020-01-02", "open": "1", "high": "1", "low": "1", "close": "1", "volume": "100", "adj_close": "1"}],
        )
        import_module.main(
            ["--source-name", "t", "--data-dir", str(data_dir), "--symbols", "AAPL", "--start", "2020-01-01", "--end", "2020-01-31", "--db-path", str(db_path)]
        )

        exit_code = module.main(
            [
                "--sp500-intervals-csv", str(intervals_csv),
                "--db-path", str(db_path),
                "--since", "2000-01-01",
                "--as-of", "2026-01-01",
                "--out", str(tmp_path / "out.json"),
            ]
        )
        assert exit_code == 1

    def test_no_network_module_is_imported_by_this_script(self) -> None:
        source = (Path(__file__).resolve().parents[2] / "scripts" / "report_survivorship_price_coverage.py").read_text()
        for forbidden in ("import requests", "urllib.request", "http.client"):
            assert forbidden not in source, f"{forbidden!r} must not appear in a script that claims to make no network call"
