"""Real, executable tests for `scripts/convert_quandl_wiki_prices_to_
file_import_csv.py` (Session 37 continued, ADR-0126).

This script makes NO network call -- it only transforms a WIKI_PRICES.csv
file already downloaded locally -- so it is safe to run `main()` here
end to end, against fixture rows shaped exactly like the REAL Quandl
WIKI/PRICES export the account owner downloaded this session (header
and DELL row values are not invented; see that ADR for the real
grep/awk output they were taken from)."""

from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "convert_quandl_wiki_prices_to_file_import_csv.py"
_SOURCE_COLUMNS = (
    "ticker", "date", "open", "high", "low", "close", "volume",
    "ex-dividend", "split_ratio", "adj_open", "adj_high", "adj_low", "adj_close", "adj_volume",
)


def _load_script():
    spec = importlib.util.spec_from_file_location("convert_quandl_wiki_prices_to_file_import_csv", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_source_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_SOURCE_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _real_dell_rows() -> list[dict]:
    """Real rows this session's account owner reported from the actual
    downloaded WIKI_PRICES.csv -- last real trades (volume > 0) right up
    through the real 2013-10-29 Dell LBO close, then the dummy flat-fill
    tail that starts immediately after."""
    return [
        {"ticker": "DELL", "date": "2013-10-28", "open": "13.84", "high": "13.85", "low": "13.82", "close": "13.83",
         "volume": "130524200.0", "ex-dividend": "0.0", "split_ratio": "1.0", "adj_open": "13.84", "adj_high": "13.85",
         "adj_low": "13.82", "adj_close": "13.83", "adj_volume": "130524200.0"},
        {"ticker": "DELL", "date": "2013-10-29", "open": "13.85", "high": "13.87", "low": "13.83", "close": "13.86",
         "volume": "65719400.0", "ex-dividend": "0.0", "split_ratio": "1.0", "adj_open": "13.85", "adj_high": "13.87",
         "adj_low": "13.83", "adj_close": "13.86", "adj_volume": "65719400.0"},
        {"ticker": "DELL", "date": "2014-04-16", "open": "31.3", "high": "31.3", "low": "31.3", "close": "31.3",
         "volume": "0.0", "ex-dividend": "0.0", "split_ratio": "1.0", "adj_open": "31.3", "adj_high": "31.3",
         "adj_low": "31.3", "adj_close": "31.3", "adj_volume": "0.0"},
        {"ticker": "DELL", "date": "2014-04-21", "open": "31.3", "high": "31.3", "low": "31.3", "close": "31.3",
         "volume": "0.0", "ex-dividend": "0.0", "split_ratio": "1.0", "adj_open": "31.3", "adj_high": "31.3",
         "adj_low": "31.3", "adj_close": "31.3", "adj_volume": "0.0"},
    ]


def _real_aapl_row() -> dict:
    return {
        "ticker": "AAPL", "date": "2013-10-29", "open": "525.0", "high": "530.0", "low": "524.0", "close": "528.0",
        "volume": "9000000.0", "ex-dividend": "0.0", "split_ratio": "1.0", "adj_open": "70.5", "adj_high": "71.1",
        "adj_low": "70.4", "adj_close": "70.9", "adj_volume": "9000000.0",
    }


class TestConvertQuandlWikiPricesToFileImportCsv:
    def test_dummy_zero_volume_tail_is_dropped(self, tmp_path) -> None:
        module = _load_script()
        source = tmp_path / "WIKI_PRICES.csv"
        _write_source_csv(source, _real_dell_rows())
        out_dir = tmp_path / "out"

        exit_code = module.main(["--wiki-prices-csv", str(source), "--symbols", "DELL", "--out-dir", str(out_dir)])
        assert exit_code == 0

        with (out_dir / "DELL.csv").open(newline="") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 2
        assert {r["date"] for r in rows} == {"2013-10-28", "2013-10-29"}

    def test_real_last_row_matches_the_actual_delisting_date(self, tmp_path) -> None:
        """The real evidence this ADR is based on: DELL's last real
        trading row is 2013-10-29, matching the actual LBO close date."""
        module = _load_script()
        source = tmp_path / "WIKI_PRICES.csv"
        _write_source_csv(source, _real_dell_rows())
        out_dir = tmp_path / "out"

        module.main(["--wiki-prices-csv", str(source), "--symbols", "DELL", "--out-dir", str(out_dir)])

        with (out_dir / "DELL.csv").open(newline="") as f:
            rows = list(csv.DictReader(f))
        assert rows[-1]["date"] == "2013-10-29"
        assert rows[-1]["close"] == "13.86"

    def test_output_columns_map_raw_and_adjusted_fields_correctly(self, tmp_path) -> None:
        module = _load_script()
        source = tmp_path / "WIKI_PRICES.csv"
        _write_source_csv(source, [_real_aapl_row()])
        out_dir = tmp_path / "out"

        module.main(["--wiki-prices-csv", str(source), "--symbols", "AAPL", "--out-dir", str(out_dir)])

        with (out_dir / "AAPL.csv").open(newline="") as f:
            rows = list(csv.DictReader(f))
        assert rows[0]["open"] == "525.0"
        assert rows[0]["close"] == "528.0"
        assert rows[0]["adj_close"] == "70.9"
        assert rows[0]["adj_high"] == "71.1"
        assert rows[0]["adj_low"] == "70.4"
        assert "adj_open" not in rows[0]
        assert "adj_volume" not in rows[0]

    def test_only_requested_tickers_are_extracted(self, tmp_path) -> None:
        module = _load_script()
        source = tmp_path / "WIKI_PRICES.csv"
        _write_source_csv(source, _real_dell_rows() + [_real_aapl_row()])
        out_dir = tmp_path / "out"

        module.main(["--wiki-prices-csv", str(source), "--symbols", "AAPL", "--out-dir", str(out_dir)])

        assert (out_dir / "AAPL.csv").is_file()
        assert not (out_dir / "DELL.csv").is_file()

    def test_symbol_with_zero_real_rows_is_skipped_not_written(self, tmp_path) -> None:
        module = _load_script()
        source = tmp_path / "WIKI_PRICES.csv"
        # Only dummy (volume == 0) rows for this symbol.
        rows = [dict(r, ticker="ZZZZ") for r in _real_dell_rows() if r["volume"] == "0.0"]
        _write_source_csv(source, rows)
        out_dir = tmp_path / "out"

        exit_code = module.main(["--wiki-prices-csv", str(source), "--symbols", "ZZZZ", "--out-dir", str(out_dir)])
        assert exit_code == 1  # the only requested symbol had zero real rows
        assert not (out_dir / "ZZZZ.csv").is_file()

    def test_one_missing_symbol_among_several_does_not_fail_the_whole_run(self, tmp_path) -> None:
        module = _load_script()
        source = tmp_path / "WIKI_PRICES.csv"
        _write_source_csv(source, _real_dell_rows() + [_real_aapl_row()])
        out_dir = tmp_path / "out"

        exit_code = module.main(
            ["--wiki-prices-csv", str(source), "--symbols", "AAPL", "NOSUCHTICKER", "--out-dir", str(out_dir)]
        )
        assert exit_code == 0
        assert (out_dir / "AAPL.csv").is_file()
        assert not (out_dir / "NOSUCHTICKER.csv").is_file()

    def test_missing_source_file_fails_with_nonzero_exit(self, tmp_path) -> None:
        module = _load_script()
        exit_code = module.main(
            ["--wiki-prices-csv", str(tmp_path / "nope.csv"), "--symbols", "DELL", "--out-dir", str(tmp_path / "out")]
        )
        assert exit_code == 1

    def test_source_missing_required_column_fails_with_nonzero_exit(self, tmp_path) -> None:
        module = _load_script()
        source = tmp_path / "WIKI_PRICES.csv"
        with source.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=("ticker", "date", "close"))
            writer.writeheader()
            writer.writerow({"ticker": "DELL", "date": "2013-10-29", "close": "13.86"})

        exit_code = module.main(["--wiki-prices-csv", str(source), "--symbols", "DELL", "--out-dir", str(tmp_path / "out")])
        assert exit_code == 1

    def test_rows_are_written_sorted_by_date(self, tmp_path) -> None:
        module = _load_script()
        source = tmp_path / "WIKI_PRICES.csv"
        real_rows = [r for r in _real_dell_rows() if r["volume"] != "0.0"]
        _write_source_csv(source, list(reversed(real_rows)))  # out of order on disk
        out_dir = tmp_path / "out"

        module.main(["--wiki-prices-csv", str(source), "--symbols", "DELL", "--out-dir", str(out_dir)])

        with (out_dir / "DELL.csv").open(newline="") as f:
            rows = list(csv.DictReader(f))
        assert [r["date"] for r in rows] == ["2013-10-28", "2013-10-29"]

    def test_output_is_directly_consumable_by_local_file_data_provider(self, tmp_path) -> None:
        """End-to-end: convert real-shaped rows, then feed the result
        straight into the existing external-import pipeline
        (scripts/import_external_market_data.py) -- proves the two
        scripts' schemas actually agree, not just that each parses in
        isolation."""
        convert_module = _load_script()
        source = tmp_path / "WIKI_PRICES.csv"
        _write_source_csv(source, _real_dell_rows())
        data_dir = tmp_path / "converted"
        assert convert_module.main(["--wiki-prices-csv", str(source), "--symbols", "DELL", "--out-dir", str(data_dir)]) == 0

        import_script_path = Path(__file__).resolve().parents[2] / "scripts" / "import_external_market_data.py"
        spec = importlib.util.spec_from_file_location("import_external_market_data", import_script_path)
        import_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(import_module)

        db_path = tmp_path / "db"
        exit_code = import_module.main(
            [
                "--source-name", "quandl_wiki_prices_kaggle_mirror",
                "--data-dir", str(data_dir),
                "--symbols", "DELL",
                "--start", "2013-01-01",
                "--end", "2013-12-31",
                "--db-path", str(db_path),
            ]
        )
        assert exit_code == 0

    def test_no_network_module_is_imported_by_this_script(self) -> None:
        source = _SCRIPT_PATH.read_text()
        for forbidden in ("import requests", "urllib.request", "http.client"):
            assert forbidden not in source, f"{forbidden!r} must not appear in a script that claims to make no network call"
