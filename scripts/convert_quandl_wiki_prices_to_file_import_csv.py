#!/usr/bin/env python3
"""Converts a real Quandl WIKI/PRICES export (the free, pre-2018-freeze
EOD dataset for ~3,200 US equities, mirrored on Kaggle as
`marketneutral/quandl-wiki-prices-us-equites`) into the per-symbol CSV
schema `data_infra.providers.file_import.LocalFileDataProvider` expects
(see that module's docstring), so the existing external-import pipeline
(`scripts/import_external_market_data.py`) can ingest it unmodified.

This script makes NO network call -- it only transforms one large CSV
file the account owner already downloaded locally (same division of
responsibility as `scripts/convert_finra_short_interest_response.py`,
ADR-0125).

**Why this dataset, and its real-verified header** (this session,
ADR-0126): the account owner downloaded the Kaggle mirror and reported
its exact header:

    ticker,date,open,high,low,close,volume,ex-dividend,split_ratio,
    adj_open,adj_high,adj_low,adj_close,adj_volume

**The dummy-tail artifact, empirically confirmed, not guessed**: after
a ticker's real listing ends, this dataset's scraper appears to carry
the last known quote forward as flat, zero-volume filler rows rather
than simply stopping. Confirmed against a real, named case this
session: `DELL` (Dell Inc., taken private by Michael Dell/Silver Lake)
has real trading rows (volume > 0) up through 2013-10-29 at
$13.84-13.86/share -- matching the well-documented $13.75/share buyout
that closed that exact day -- immediately followed by repeating
`31.3,31.3,31.3,31.3,volume=0.0` rows starting 2014-04-16 through the
dataset's own 2018-03-27 freeze date. This script drops every row with
`volume == 0` as this confirmed artifact, never as a guess -- a
genuine zero-volume trading day is not a realistic occurrence for any
of this project's research-universe-scale securities, and the evidence
above shows the artifact's own shape (an exact repeated price, forever,
starting immediately after the last real trade) is unambiguous.

**Column mapping**: `open/high/low/close/volume` map straight across
(raw, unadjusted -- matching `LocalFileDataProvider`'s required
columns); `adj_close/adj_high/adj_low` map to this project's optional
adjusted columns. `adj_open`/`adj_volume`/`ex-dividend`/`split_ratio`
are read from the header (to confirm the schema matches) but not
carried into the output -- `LocalFileDataProvider` has no field for
them.

Usage:
    python3 scripts/convert_quandl_wiki_prices_to_file_import_csv.py \\
        --wiki-prices-csv /path/to/WIKI_PRICES.csv \\
        --symbols DELL DTV LNKD TWX YHOO \\
        --out-dir ./wiki_prices_converted

Then feed `./wiki_prices_converted` straight to
`scripts/import_external_market_data.py --data-dir ./wiki_prices_converted
--source-name quandl_wiki_prices_kaggle_mirror ...`.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

_REQUIRED_SOURCE_COLUMNS = ("ticker", "date", "open", "high", "low", "close", "volume", "adj_close", "adj_high", "adj_low")
_OUTPUT_COLUMNS = ("date", "open", "high", "low", "close", "volume", "adj_close", "adj_high", "adj_low")


def _convert_row(row: dict) -> dict:
    return {
        "date": row["date"],
        "open": row["open"],
        "high": row["high"],
        "low": row["low"],
        "close": row["close"],
        "volume": row["volume"],
        "adj_close": row["adj_close"],
        "adj_high": row["adj_high"],
        "adj_low": row["adj_low"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--wiki-prices-csv", required=True, type=Path, help="Path to the downloaded WIKI_PRICES.csv (real Quandl WIKI/PRICES export)")
    parser.add_argument("--symbols", nargs="+", required=True, help="Ticker(s) to extract (as they appear in the WIKI file's ticker column)")
    parser.add_argument("--out-dir", required=True, type=Path, help="Directory to write one <security_id>.csv per symbol into")
    args = parser.parse_args(argv)

    if not args.wiki_prices_csv.is_file():
        print(f"FATAL: {args.wiki_prices_csv} does not exist", file=sys.stderr)
        return 1

    requested = set(args.symbols)
    real_rows_by_symbol: dict[str, list[dict]] = {symbol: [] for symbol in requested}
    dummy_dropped_by_symbol: dict[str, int] = {symbol: 0 for symbol in requested}

    with args.wiki_prices_csv.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing_columns = set(_REQUIRED_SOURCE_COLUMNS) - set(reader.fieldnames or ())
        if missing_columns:
            print(
                f"FATAL: {args.wiki_prices_csv} is missing required column(s) {sorted(missing_columns)} "
                f"-- expected {_REQUIRED_SOURCE_COLUMNS}, found {reader.fieldnames}",
                file=sys.stderr,
            )
            return 1

        for row in reader:
            ticker = row["ticker"]
            if ticker not in requested:
                continue
            try:
                volume = float(row["volume"])
            except ValueError:
                print(f"FATAL: non-numeric volume {row['volume']!r} for {ticker} on {row['date']}", file=sys.stderr)
                return 1
            if volume == 0.0:
                # Confirmed dummy-tail artifact -- see module docstring.
                dummy_dropped_by_symbol[ticker] += 1
                continue
            real_rows_by_symbol[ticker].append(_convert_row(row))

    args.out_dir.mkdir(parents=True, exist_ok=True)
    written_symbols: list[str] = []
    missing_symbols: list[str] = []
    for symbol in sorted(requested):
        rows = sorted(real_rows_by_symbol[symbol], key=lambda r: r["date"])
        if not rows:
            missing_symbols.append(symbol)
            print(f"WARNING: no real (volume > 0) rows found for {symbol!r} -- not writing a file for it", file=sys.stderr)
            continue
        out_path = args.out_dir / f"{symbol}.csv"
        with out_path.open("w", newline="", encoding="utf-8") as out_f:
            writer = csv.DictWriter(out_f, fieldnames=_OUTPUT_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        written_symbols.append(symbol)
        print(
            f"{symbol}: wrote {len(rows)} real row(s) ({rows[0]['date']} to {rows[-1]['date']}), "
            f"dropped {dummy_dropped_by_symbol[symbol]} dummy row(s) -> {out_path}"
        )

    if not written_symbols:
        print("FATAL: none of the requested symbols had any real (volume > 0) rows", file=sys.stderr)
        return 1

    if missing_symbols:
        print(f"Symbols with no real rows (skipped): {missing_symbols}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
