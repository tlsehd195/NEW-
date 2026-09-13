#!/usr/bin/env python3
"""Converts one or more real SEC Form 13F Information Table XML files
(one per filer, already downloaded by the account owner -- this
script makes no network call to fetch them) into this project's
`--combined-csv` schema for `scripts/ingest_institutional_holdings.py`
(`security_id,quarter_end,institutional_shares,num_institutions`) --
resolving each real CUSIP to a real US-listed ticker via OpenFIGI's
free `/v3/mapping` endpoint along the way.

This is the two-stage aggregation `data_infra.institutional_holding_
models`'s own module docstring describes: stage one (within one
filer's filing, summing every line item sharing a CUSIP --
`data_infra.providers.sec_13f_infotable_parser.aggregate_shares_by_
cusip`) happens per input file; stage two (summing across every filer
that reported a position, and counting how many did) happens across
all the input files given to this one run.

**Makes ONE real network call type**: a batched POST to `https://api.
openfigi.com/v3/mapping` (free, no API key required for the volumes
this project needs -- 100 CUSIPs per request, 5,000 requests/day) to
resolve every distinct CUSIP found across all input filings. It never
fetches the 13F filings themselves -- those must already be downloaded
locally (mirroring `scripts/convert_finra_short_interest_response.py`/
`scripts/convert_quandl_wiki_prices_to_file_import_csv.py`'s own
"acquisition is the user's job, this script only normalizes" split).

**`--quarter-end` must be supplied explicitly.** A 13F Information
Table XML itself carries no period-of-report field (that lives in the
filing's separate cover-page document, `primary_doc.xml`, which this
script does not parse) -- never guessed or defaulted to today's date.

Usage:
    python3 scripts/convert_sec_13f_filings_to_combined_csv.py \\
        berkshire_infotable.xml other_filer_infotable.xml ... \\
        --quarter-end 2026-06-30 \\
        --out combined_13f.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from data_infra.providers.openfigi_cusip_resolution import (  # noqa: E402
    build_mapping_request,
    parse_mapping_response,
)
from data_infra.providers.sec_13f_infotable_parser import (  # noqa: E402
    aggregate_shares_by_cusip,
    parse_13f_infotable_xml,
)

_OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"

# Session 37 (ADR-0131 follow-up): the no-API-key tier's real batch
# limit is NOT the 100-per-request figure secondary documentation
# suggested. Confirmed directly: a real 29-CUSIP request returned
# HTTP 413 with the real, exact response body "Request may only
# contain 10 mapping jobs." -- the true anonymous-tier limit is 10,
# not 100. The response also carried `ratelimit-limit: 25` (per
# 60-second window) -- a separate request-RATE cap, not a per-request
# item-count cap. Exposed as --batch-size (not just hardcoded) so it
# can still be tuned if OpenFIGI's real limit changes again.
_DEFAULT_BATCH_SIZE = 10


def _resolve_cusips(cusips: list[str], *, batch_size: int, timeout: float) -> dict[str, str | None]:
    resolved: dict[str, str | None] = {}
    for start in range(0, len(cusips), batch_size):
        batch = cusips[start : start + batch_size]
        body = json.dumps(build_mapping_request(batch)).encode("utf-8")
        req = urllib.request.Request(
            _OPENFIGI_URL, data=body, method="POST", headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                response_json = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            print(f"FATAL: OpenFIGI request failed with HTTP {exc.code} for batch {batch}: {error_body}", file=sys.stderr)
            return {}
        except urllib.error.URLError as exc:
            print(f"FATAL: OpenFIGI request failed: {exc.reason}", file=sys.stderr)
            return {}
        resolved.update(parse_mapping_response(batch, response_json))
    return resolved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("infotable_files", nargs="+", type=Path, help="One real 13F Information Table XML file per filer")
    parser.add_argument("--quarter-end", required=True, type=str, help="YYYY-MM-DD, the filing period this quarter's 13F reports cover (not parsed from the XML itself)")
    parser.add_argument("--out", required=True, type=Path, help="Where to write the combined CSV")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout in seconds for the OpenFIGI request")
    parser.add_argument("--batch-size", type=int, default=_DEFAULT_BATCH_SIZE, help=f"CUSIPs per OpenFIGI request (default: {_DEFAULT_BATCH_SIZE}; lower if you see HTTP 413)")
    args = parser.parse_args(argv)

    per_filer_totals: list[dict[str, int]] = []
    for path in args.infotable_files:
        if not path.is_file():
            print(f"FATAL: {path} does not exist", file=sys.stderr)
            return 1
        try:
            records = parse_13f_infotable_xml(path.read_bytes())
        except ValueError as exc:
            print(f"FATAL: {path}: {exc}", file=sys.stderr)
            return 1
        per_filer_totals.append(aggregate_shares_by_cusip(records))

    all_cusips = sorted({cusip for totals in per_filer_totals for cusip in totals})
    if not all_cusips:
        print("FATAL: no CUSIPs found across the given input file(s)", file=sys.stderr)
        return 1

    ticker_by_cusip = _resolve_cusips(all_cusips, batch_size=args.batch_size, timeout=args.timeout)
    if not ticker_by_cusip:
        return 1

    aggregate_shares: dict[str, int] = {}
    filer_count: dict[str, int] = {}
    unresolved_cusips: set[str] = set()
    for totals in per_filer_totals:
        for cusip, shares in totals.items():
            ticker = ticker_by_cusip.get(cusip)
            if not ticker:
                unresolved_cusips.add(cusip)
                continue
            aggregate_shares[ticker] = aggregate_shares.get(ticker, 0) + shares
            filer_count[ticker] = filer_count.get(ticker, 0) + 1

    if unresolved_cusips:
        print(f"WARNING: {len(unresolved_cusips)} CUSIP(s) could not be resolved to a US ticker, excluded: {sorted(unresolved_cusips)}", file=sys.stderr)

    if not aggregate_shares:
        print("FATAL: no CUSIPs resolved to a real US ticker -- nothing to write", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["security_id", "quarter_end", "institutional_shares", "num_institutions"])
        writer.writeheader()
        for ticker in sorted(aggregate_shares):
            writer.writerow(
                {
                    "security_id": ticker,
                    "quarter_end": args.quarter_end,
                    "institutional_shares": aggregate_shares[ticker],
                    "num_institutions": filer_count[ticker],
                }
            )

    print(f"Wrote {len(aggregate_shares)} security(ies) from {len(args.infotable_files)} filer(s) to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
