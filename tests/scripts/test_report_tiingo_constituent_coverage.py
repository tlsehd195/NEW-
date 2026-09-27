"""report_tiingo_constituent_coverage.py (ADR-0224): which historical
S&P 500 members Tiingo lists, with reused tickers counted as missing."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "report_tiingo_constituent_coverage.py"


def _load():
    spec = importlib.util.spec_from_file_location("report_tiingo_constituent_coverage", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reports_listed_removed_and_reused_tickers(tmp_path: Path) -> None:
    intervals = tmp_path / "sp500.csv"
    intervals.write_text(
        "ticker,start_date,end_date\n"
        "AAPL,1996-01-02,\n"
        "BSC,1996-01-02,2008-05-30\n"
        "OLD,1996-01-02,2003-01-01\n"  # ticker later reused by another company
        "BRK.B,2010-02-16,\n"
        "LATE,2018-01-02,\n"  # joined after the window
    )
    tiingo = tmp_path / "supported_tickers.csv"
    tiingo.write_text(
        "ticker,exchange,assetType,priceCurrency,startDate,endDate\n"
        "AAPL,NASDAQ,Stock,USD,1980-12-12,2026-09-25\n"
        "BSC,NYSE,Stock,USD,1990-01-02,2008-05-30\n"
        "OLD,NYSE,Stock,USD,2012-05-01,2026-09-25\n"
        "BRK-B,NYSE,Stock,USD,1996-05-09,2026-09-25\n"
        "LATE,NYSE,Stock,USD,2000-01-01,2026-09-25\n"
    )
    output = tmp_path / "coverage.json"
    assert _load().main([
        "--sp500-intervals-csv", str(intervals), "--tiingo-supported-tickers-csv", str(tiingo),
        "--start", "2000-01-01", "--end", "2016-07-11", "--output", str(output),
    ]) == 0
    report = json.loads(output.read_text())
    assert report["constituents_in_window"] == 4
    assert report["listed"] == 3
    assert report["no_longer_member"] == 2
    assert report["no_longer_member_listed"] == 1
    assert report["not_listed"] == ["OLD"]
