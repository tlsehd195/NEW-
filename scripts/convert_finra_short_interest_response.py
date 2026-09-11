#!/usr/bin/env python3
"""Converts real FINRA Equity Short Interest API responses into this
project's `--combined-csv` schema for `scripts/ingest_short_interest_
data.py` (see `data_infra.providers.short_interest_file_import` module
docstring for that schema's own documentation).

Source: `https://api.finra.org/data/group/otcMarket/name/
EquityShortInterest` (OAuth2 client-credentials auth, group `otcMarket`,
dataset `EquityShortInterest`). This script makes NO network call
itself -- it only transforms JSON response files the account owner
already fetched and saved locally (the same "user's own network access,
this script only normalizes" division of responsibility every other
file-import module in this project already uses).

**Field mapping verified against a REAL response** (fetched by the
account owner this session, not guessed from documentation alone):

    issueSymbolIdentifier   -> security_id
    settlementDate          -> settlement_date
    currentShortShareNumber -> short_interest_quantity
    daysToCoverNumber       -> days_to_cover

`daysToCoverNumber`'s `999.99` is FINRA's own documented sentinel for
"undefined" (typically a security with no trading volume to divide by)
-- confirmed via FINRA's public "Short Interest" investor documentation,
never a literal 999.99-day figure. This script converts it to blank
(`None`), never passing the sentinel through as if it were a real
ratio -- the same "never fabricate/mislabel a value" discipline this
project's short-interest module already documents for
`average_daily_volume`/`days_to_cover` being optional.

**No `average_daily_volume` field exists in this real response.** The
real FINRA payload instead carries `averageShortShareNumber` -- a
DIFFERENT concept (an average SHORT POSITION over some window, not
daily TRADING volume). This script deliberately does NOT map it to
`average_daily_volume`, since that would silently mislabel one metric
as another. `average_daily_volume` is left blank for every row
(already an optional column in this project's schema).

Usage:
    python3 scripts/convert_finra_short_interest_response.py \\
        response1.json response2.json ... \\
        --out combined_short_interest.csv

Each input file must be a JSON array of records shaped like the real
API response (a list of objects with at least `issueSymbolIdentifier`,
`settlementDate`, `currentShortShareNumber`, `daysToCoverNumber`).
Multiple files are concatenated (e.g. one file per paginated request or
per settlement date) -- duplicate (security_id, settlement_date) rows
are not de-duplicated here; `scripts/ingest_short_interest_data.py`'s
own DuckDB insert is already idempotent on that exact key.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

_FINRA_UNDEFINED_DAYS_TO_COVER = 999.99


def _convert_record(record: dict) -> dict:
    days_to_cover = record.get("daysToCoverNumber")
    if days_to_cover == _FINRA_UNDEFINED_DAYS_TO_COVER:
        days_to_cover = None
    return {
        "security_id": record["issueSymbolIdentifier"],
        "settlement_date": record["settlementDate"],
        "short_interest_quantity": record["currentShortShareNumber"],
        "average_daily_volume": "",
        "days_to_cover": "" if days_to_cover is None else days_to_cover,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("inputs", nargs="+", type=Path, help="One or more JSON files, each a FINRA EquityShortInterest API response (a JSON array of records)")
    parser.add_argument("--out", required=True, type=Path, help="Where to write the combined CSV")
    args = parser.parse_args(argv)

    rows: list[dict] = []
    for input_path in args.inputs:
        if not input_path.is_file():
            print(f"FATAL: {input_path} does not exist", file=sys.stderr)
            return 1
        records = json.loads(input_path.read_text(encoding="utf-8"))
        if not isinstance(records, list):
            print(f"FATAL: {input_path} does not contain a JSON array at the top level", file=sys.stderr)
            return 1
        for record in records:
            try:
                rows.append(_convert_record(record))
            except KeyError as exc:
                print(f"FATAL: {input_path} has a record missing required field {exc}", file=sys.stderr)
                return 1

    if not rows:
        print("FATAL: no records found across the given input file(s)", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["security_id", "settlement_date", "short_interest_quantity", "average_daily_volume", "days_to_cover"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} row(s) from {len(args.inputs)} input file(s) to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
