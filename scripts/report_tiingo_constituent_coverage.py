"""How many historical S&P 500 constituents does Tiingo list? (ADR-0224)

Reads two already-downloaded files and makes no network call:

- `fja05680/sp500`'s `sp500_ticker_start_end.csv` (ADR-0120), and
- Tiingo's public `supported_tickers.csv` (from `supported_tickers.zip`,
  which costs no API request and no monthly symbol quota).

For every ticker that was an index member at some point inside
`[--start, --end]`, it reports whether Tiingo lists a stock with that
ticker whose own [startDate, endDate] overlaps the membership interval.
A reused ticker (Tiingo's only listing starts after the member left)
counts as NOT listed: fetching it by ticker would return the wrong
company.

Listed does not mean the full history is there. It only says which
names are worth spending Tiingo requests on.

    python3 scripts/report_tiingo_constituent_coverage.py \\
        --sp500-intervals-csv sp500_ticker_start_end.csv \\
        --tiingo-supported-tickers-csv supported_tickers.csv \\
        --start 2000-01-01 --end 2016-07-11 --output coverage.json
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from data_infra.providers.sp500_index_constituent_history import (  # noqa: E402
    apply_ticker_renames,
    parse_ticker_intervals,
    parse_ticker_renames,
)

_STOCK_TYPES = {"stock"}


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _tiingo_key(ticker: str) -> str:
    # fja05680 writes class shares as "BRK.B"; Tiingo writes "BRK-B".
    return ticker.upper().replace(".", "-")


def load_tiingo_listings(path: Path) -> dict[str, list[tuple[date | None, date | None, str]]]:
    listings: dict[str, list[tuple[date | None, date | None, str]]] = {}
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            if (row.get("assetType") or "").strip().lower() not in _STOCK_TYPES:
                continue
            if (row.get("priceCurrency") or "USD").strip().upper() != "USD":
                continue
            start = _parse_date(row["startDate"][:10]) if row.get("startDate") else None
            end = _parse_date(row["endDate"][:10]) if row.get("endDate") else None
            listings.setdefault(_tiingo_key(row["ticker"]), []).append((start, end, row.get("exchange") or ""))
    return listings


def coverage(intervals, listings, window_start: date, window_end: date) -> dict:
    by_ticker: dict[str, dict] = {}
    for interval in intervals:
        member_end = interval.end_date or date.max
        if interval.start_date > window_end or member_end < window_start:
            continue
        lo, hi = max(interval.start_date, window_start), min(member_end, window_end)
        entry = by_ticker.setdefault(
            interval.ticker, {"ticker": interval.ticker, "still_member": False, "listed": False, "tiingo": []}
        )
        entry["still_member"] = entry["still_member"] or interval.end_date is None
        for start, end, exchange in listings.get(_tiingo_key(interval.ticker), []):
            if (start is None or start <= hi) and (end is None or end >= lo):
                entry["listed"] = True
                entry["tiingo"].append(
                    {"start": start.isoformat() if start else None, "end": end.isoformat() if end else None, "exchange": exchange}
                )
    rows = sorted(by_ticker.values(), key=lambda r: r["ticker"])

    # Rename candidates: an unlisted ticker X leaves on day d, a ticker Y
    # joins on the same day, and Tiingo's history for Y starts no later
    # than X's own membership did. A same-day swap between two unrelated
    # companies can match too, so these are candidates to check, not a map.
    starts_by_day: dict[date, list[str]] = {}
    for interval in intervals:
        starts_by_day.setdefault(interval.start_date, []).append(interval.ticker)
    rename_candidates = []
    unlisted = {r["ticker"] for r in rows if not r["listed"]}
    for interval in intervals:
        if interval.ticker not in unlisted or interval.end_date is None:
            continue
        for new_ticker in starts_by_day.get(interval.end_date, []):
            listed_since = [start for start, _, _ in listings.get(_tiingo_key(new_ticker), []) if start is not None]
            if listed_since and min(listed_since) <= interval.start_date:
                rename_candidates.append(
                    {"old": interval.ticker, "new": new_ticker, "date": interval.end_date.isoformat()}
                )
    removed = [r for r in rows if not r["still_member"]]
    return {
        "window": [window_start.isoformat(), window_end.isoformat()],
        "constituents_in_window": len(rows),
        "listed": sum(r["listed"] for r in rows),
        "no_longer_member": len(removed),
        "no_longer_member_listed": sum(r["listed"] for r in removed),
        "not_listed": [r["ticker"] for r in rows if not r["listed"]],
        "rename_candidates": rename_candidates,
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--sp500-intervals-csv", type=Path, required=True)
    parser.add_argument("--tiingo-supported-tickers-csv", type=Path, required=True)
    parser.add_argument("--start", type=_parse_date, required=True)
    parser.add_argument("--end", type=_parse_date, required=True)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--renames-csv", type=Path, default=None,
        help="docs/research/reference/sp500_ticker_renames.csv: count a renamed member under the ticker Tiingo keeps its history under",
    )
    parser.add_argument(
        "--symbols-out", type=Path, default=None,
        help="Write the listed members, one per line, no-longer-members first (ADR-0224 ingestion order)",
    )
    args = parser.parse_args(argv)

    intervals = parse_ticker_intervals(args.sp500_intervals_csv)
    if args.renames_csv is not None:
        intervals = apply_ticker_renames(intervals, parse_ticker_renames(args.renames_csv))
    report = coverage(intervals, load_tiingo_listings(args.tiingo_supported_tickers_csv), args.start, args.end)
    if args.output:
        args.output.write_text(json.dumps(report, indent=2))
    if args.symbols_out:
        # Names that left the index first: they are the survivorship gap,
        # so they get the quota if it runs out. Class-share tickers
        # ("BRK.B") are left out; Tiingo spells them differently from the
        # catalog's security_id.
        listed = [r for r in report["rows"] if r["listed"] and "." not in r["ticker"]]
        ordered = [r["ticker"] for r in listed if not r["still_member"]] + [r["ticker"] for r in listed if r["still_member"]]
        args.symbols_out.write_text("".join(f"{t}\n" for t in ordered))
    print("not listed:", " ".join(report["not_listed"]))
    print("rename candidates:", " ".join(f"{c['old']}->{c['new']}@{c['date']}" for c in report["rename_candidates"]))
    print(json.dumps({k: v for k, v in report.items() if k not in ("rows", "not_listed", "rename_candidates")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
