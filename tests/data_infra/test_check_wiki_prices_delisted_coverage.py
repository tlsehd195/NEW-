"""Real, executable tests for `scripts/check_wiki_prices_delisted_
coverage.py` (Session 37 continued, ADR-0126 follow-up).

Makes no network call -- reads two local files only -- so `main()` is
run here end to end against real-shaped fixtures (the same DELL/AAPL
rows this session verified by hand) and a small S&P 500 interval
fixture."""

from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "check_wiki_prices_delisted_coverage.py"
_WIKI_COLUMNS = (
    "ticker", "date", "open", "high", "low", "close", "volume",
    "ex-dividend", "split_ratio", "adj_open", "adj_high", "adj_low", "adj_close", "adj_volume",
)


def _load_script():
    spec = importlib.util.spec_from_file_location("check_wiki_prices_delisted_coverage", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_intervals_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=("ticker", "start_date", "end_date"))
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_wiki_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_WIKI_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _wiki_row(ticker: str, date: str, volume: str, close: str = "10.0") -> dict:
    return {
        "ticker": ticker, "date": date, "open": close, "high": close, "low": close, "close": close,
        "volume": volume, "ex-dividend": "0.0", "split_ratio": "1.0", "adj_open": close, "adj_high": close,
        "adj_low": close, "adj_close": close, "adj_volume": volume,
    }


class TestCheckWikiPricesDelistedCoverage:
    def test_a_removed_ticker_with_real_rows_is_reported_covered(self, tmp_path) -> None:
        module = _load_script()
        intervals_csv = tmp_path / "sp500_ticker_start_end.csv"
        _write_intervals_csv(intervals_csv, [{"ticker": "DELL", "start_date": "1988-08-17", "end_date": "2013-10-29"}])
        wiki_csv = tmp_path / "WIKI_PRICES.csv"
        _write_wiki_csv(
            wiki_csv,
            [
                _wiki_row("DELL", "2013-10-28", "130524200.0"),
                _wiki_row("DELL", "2013-10-29", "65719400.0"),
                _wiki_row("DELL", "2014-04-16", "0.0"),  # dummy tail, must not count as coverage
            ],
        )
        out = tmp_path / "report.json"

        exit_code = module.main(
            ["--sp500-intervals-csv", str(intervals_csv), "--wiki-prices-csv", str(wiki_csv), "--out", str(out)]
        )
        assert exit_code == 0

        report = json.loads(out.read_text())
        assert report["covered_ticker_count"] == 1
        assert "DELL" in report["covered_tickers"]
        assert report["covered_tickers"]["DELL"]["last_real_date"] == "2013-10-29"
        assert report["covered_tickers"]["DELL"]["sp500_end_dates"] == ["2013-10-29"]
        assert report["covered_tickers"]["DELL"]["days_from_nearest_sp500_end_date"] == 0
        assert report["covered_tickers"]["DELL"]["likely_genuine_delisting"] is True
        assert report["likely_genuine_delisting_count"] == 1
        assert report["likely_still_trading_after_index_removal_count"] == 0

    def test_data_continuing_long_after_index_removal_is_not_classified_genuine(self, tmp_path) -> None:
        """A ticker removed from the S&P 500 for falling below the
        market-cap threshold, but that kept trading for years afterward,
        must not be counted as a genuine delisting -- it's already
        coverable by any ordinary current-data provider."""
        module = _load_script()
        intervals_csv = tmp_path / "sp500_ticker_start_end.csv"
        _write_intervals_csv(intervals_csv, [{"ticker": "SMALLCAP", "start_date": "2000-01-01", "end_date": "2010-01-01"}])
        wiki_csv = tmp_path / "WIKI_PRICES.csv"
        _write_wiki_csv(
            wiki_csv,
            [
                _wiki_row("SMALLCAP", "2009-12-31", "1000.0"),
                _wiki_row("SMALLCAP", "2017-06-15", "2000.0"),  # still trading, years after index removal
            ],
        )
        out = tmp_path / "report.json"

        module.main(["--sp500-intervals-csv", str(intervals_csv), "--wiki-prices-csv", str(wiki_csv), "--out", str(out)])

        report = json.loads(out.read_text())
        assert report["covered_tickers"]["SMALLCAP"]["likely_genuine_delisting"] is False
        assert report["likely_genuine_delisting_count"] == 0
        assert report["likely_still_trading_after_index_removal_count"] == 1

    def test_genuine_delisting_gap_uses_the_nearest_of_multiple_end_dates(self, tmp_path) -> None:
        """A ticker that left and re-entered the index (e.g. real AAL)
        must be matched against whichever end_date its real data's own
        end is actually close to, not just the earliest or latest one."""
        module = _load_script()
        intervals_csv = tmp_path / "sp500_ticker_start_end.csv"
        _write_intervals_csv(
            intervals_csv,
            [
                {"ticker": "AAL", "start_date": "1996-01-02", "end_date": "1997-01-15"},
                {"ticker": "AAL", "start_date": "2015-03-23", "end_date": "2024-09-23"},
            ],
        )
        wiki_csv = tmp_path / "WIKI_PRICES.csv"
        _write_wiki_csv(wiki_csv, [_wiki_row("AAL", "1997-01-20", "1000.0")])  # close to the FIRST end_date only
        out = tmp_path / "report.json"

        module.main(["--sp500-intervals-csv", str(intervals_csv), "--wiki-prices-csv", str(wiki_csv), "--out", str(out)])

        report = json.loads(out.read_text())
        assert report["covered_tickers"]["AAL"]["days_from_nearest_sp500_end_date"] == 5
        assert report["covered_tickers"]["AAL"]["likely_genuine_delisting"] is True

    def test_a_removed_ticker_with_no_real_rows_is_reported_not_covered(self, tmp_path) -> None:
        module = _load_script()
        intervals_csv = tmp_path / "sp500_ticker_start_end.csv"
        _write_intervals_csv(intervals_csv, [{"ticker": "LEH", "start_date": "1996-01-02", "end_date": "2008-09-15"}])
        wiki_csv = tmp_path / "WIKI_PRICES.csv"
        _write_wiki_csv(wiki_csv, [_wiki_row("AAPL", "2010-01-04", "1000.0")])
        out = tmp_path / "report.json"

        module.main(["--sp500-intervals-csv", str(intervals_csv), "--wiki-prices-csv", str(wiki_csv), "--out", str(out)])

        report = json.loads(out.read_text())
        assert report["covered_ticker_count"] == 0
        assert report["not_covered_tickers"] == ["LEH"]

    def test_a_ticker_still_a_current_member_end_date_none_is_not_a_candidate(self, tmp_path) -> None:
        module = _load_script()
        intervals_csv = tmp_path / "sp500_ticker_start_end.csv"
        _write_intervals_csv(
            intervals_csv,
            [
                {"ticker": "AAPL", "start_date": "1996-01-02", "end_date": ""},
                {"ticker": "DELL", "start_date": "1988-08-17", "end_date": "2013-10-29"},
            ],
        )
        wiki_csv = tmp_path / "WIKI_PRICES.csv"
        _write_wiki_csv(wiki_csv, [_wiki_row("AAPL", "2010-01-04", "1000.0"), _wiki_row("DELL", "2013-10-29", "65719400.0")])
        out = tmp_path / "report.json"

        module.main(["--sp500-intervals-csv", str(intervals_csv), "--wiki-prices-csv", str(wiki_csv), "--out", str(out)])

        report = json.loads(out.read_text())
        assert report["candidate_ticker_count"] == 1  # only DELL, AAPL still a current member
        assert "AAPL" not in report["covered_tickers"]

    def test_dummy_zero_volume_rows_never_count_as_coverage(self, tmp_path) -> None:
        module = _load_script()
        intervals_csv = tmp_path / "sp500_ticker_start_end.csv"
        _write_intervals_csv(intervals_csv, [{"ticker": "ZZZZ", "start_date": "2000-01-01", "end_date": "2010-01-01"}])
        wiki_csv = tmp_path / "WIKI_PRICES.csv"
        _write_wiki_csv(wiki_csv, [_wiki_row("ZZZZ", "2010-01-01", "0.0"), _wiki_row("ZZZZ", "2010-01-02", "0.0")])
        out = tmp_path / "report.json"

        module.main(["--sp500-intervals-csv", str(intervals_csv), "--wiki-prices-csv", str(wiki_csv), "--out", str(out)])

        report = json.loads(out.read_text())
        assert report["covered_ticker_count"] == 0
        assert report["not_covered_tickers"] == ["ZZZZ"]

    def test_a_ticker_that_re_entered_reports_all_its_end_dates(self, tmp_path) -> None:
        module = _load_script()
        intervals_csv = tmp_path / "sp500_ticker_start_end.csv"
        _write_intervals_csv(
            intervals_csv,
            [
                {"ticker": "AAL", "start_date": "1996-01-02", "end_date": "1997-01-15"},
                {"ticker": "AAL", "start_date": "2015-03-23", "end_date": "2024-09-23"},
            ],
        )
        wiki_csv = tmp_path / "WIKI_PRICES.csv"
        _write_wiki_csv(wiki_csv, [_wiki_row("AAL", "2016-01-04", "1000.0")])
        out = tmp_path / "report.json"

        module.main(["--sp500-intervals-csv", str(intervals_csv), "--wiki-prices-csv", str(wiki_csv), "--out", str(out)])

        report = json.loads(out.read_text())
        assert report["covered_tickers"]["AAL"]["sp500_end_dates"] == ["1997-01-15", "2024-09-23"]

    def test_missing_intervals_file_fails_with_nonzero_exit(self, tmp_path) -> None:
        module = _load_script()
        exit_code = module.main(
            [
                "--sp500-intervals-csv", str(tmp_path / "nope.csv"),
                "--wiki-prices-csv", str(tmp_path / "also_nope.csv"),
                "--out", str(tmp_path / "report.json"),
            ]
        )
        assert exit_code == 1

    def test_missing_wiki_file_fails_with_nonzero_exit(self, tmp_path) -> None:
        module = _load_script()
        intervals_csv = tmp_path / "sp500_ticker_start_end.csv"
        _write_intervals_csv(intervals_csv, [{"ticker": "DELL", "start_date": "1988-08-17", "end_date": "2013-10-29"}])
        exit_code = module.main(
            [
                "--sp500-intervals-csv", str(intervals_csv),
                "--wiki-prices-csv", str(tmp_path / "nope.csv"),
                "--out", str(tmp_path / "report.json"),
            ]
        )
        assert exit_code == 1

    def test_wiki_file_missing_required_column_fails_with_nonzero_exit(self, tmp_path) -> None:
        module = _load_script()
        intervals_csv = tmp_path / "sp500_ticker_start_end.csv"
        _write_intervals_csv(intervals_csv, [{"ticker": "DELL", "start_date": "1988-08-17", "end_date": "2013-10-29"}])
        wiki_csv = tmp_path / "WIKI_PRICES.csv"
        with wiki_csv.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=("ticker", "date", "close"))
            writer.writeheader()
            writer.writerow({"ticker": "DELL", "date": "2013-10-29", "close": "13.86"})

        exit_code = module.main(
            ["--sp500-intervals-csv", str(intervals_csv), "--wiki-prices-csv", str(wiki_csv), "--out", str(tmp_path / "report.json")]
        )
        assert exit_code == 1

    def test_no_removed_tickers_in_intervals_file_fails_with_nonzero_exit(self, tmp_path) -> None:
        module = _load_script()
        intervals_csv = tmp_path / "sp500_ticker_start_end.csv"
        _write_intervals_csv(intervals_csv, [{"ticker": "AAPL", "start_date": "1996-01-02", "end_date": ""}])
        wiki_csv = tmp_path / "WIKI_PRICES.csv"
        _write_wiki_csv(wiki_csv, [_wiki_row("AAPL", "2010-01-04", "1000.0")])

        exit_code = module.main(
            ["--sp500-intervals-csv", str(intervals_csv), "--wiki-prices-csv", str(wiki_csv), "--out", str(tmp_path / "report.json")]
        )
        assert exit_code == 1

    def test_no_network_module_is_imported_by_this_script(self) -> None:
        source = _SCRIPT_PATH.read_text()
        for forbidden in ("import requests", "urllib.request", "http.client"):
            assert forbidden not in source, f"{forbidden!r} must not appear in a script that claims to make no network call"
