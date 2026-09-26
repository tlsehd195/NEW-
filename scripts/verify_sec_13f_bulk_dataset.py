#!/usr/bin/env python3
"""Verifies the real, downloadable SEC Form 13F BULK structured data
set (one ZIP covering EVERY institutional filer's Information Table
for a ~3-month filing window, https://www.sec.gov/data-research/
sec-markets-data/form-13f-data-sets) against a handful of known,
publicly verifiable real facts -- before any full historical backfill
pipeline is built on top of it.

**Why this exists (real gap found 2026-09-26)**: `ADR-0131`'s real,
verified SEC 13F pipeline (`sec_13f_infotable_parser.py`,
`openfigi_cusip_resolution.py`, `convert_sec_13f_filings_to_combined_
csv.py`) has only ever been exercised against ONE filer's own filing
(Berkshire Hathaway) -- real, but market-coverage of ~28 securities,
not this project's full 87-symbol RESEARCH_UNIVERSE, and not a genuine
cross-filer "institutional ownership" aggregate. The bulk data set
(ALL filers' Information Tables in one file per window) is the real,
free path to that -- but this project has never downloaded one, never
confirmed its real column names/format, and never confirmed whether
this project's own already-real-verified CUSIP->ticker OpenFIGI
resolver (the ONLY direction ADR-0131 actually tested) is enough to
build a ticker-keyed filter, without needing an unverified ticker->CUSIP
direction at all.

**The approach this script verifies, avoiding any new unverified
OpenFIGI capability**: the bulk INFOTABLE.tsv itself carries BOTH
`NAMEOFISSUER` (free text) and `CUSIP` side by side for every row.
Instead of asking OpenFIGI "what is AAPL's CUSIP" (untested, and
CUSIP is rarely returned as an OUTPUT field by free identifier services
due to CUSIP Global Services licensing), this script:
    1. name-matches NAMEOFISSUER against a small set of known real
       company names for a handful of test tickers,
    2. takes the CANDIDATE CUSIP(s) that name-match,
    3. confirms each candidate via the EXISTING, already-real-verified
       CUSIP->ticker direction (`openfigi_cusip_resolution`) -- keeping
       only the CUSIP that actually resolves back to the expected
       ticker, so a coincidental/partial name match cannot silently
       mislabel the wrong CUSIP as the right one.

Real network calls: one to `www.sec.gov` (the ZIP itself), and (only if
name-matching finds a real candidate) a handful to `api.openfigi.com`
to confirm it -- the exact same call shape `convert_sec_13f_filings_
to_combined_csv.py` already makes for real, batched via the same real
10-CUSIPs-per-request limit `ADR-0131` confirmed.

Usage:
    python3 scripts/verify_sec_13f_bulk_dataset.py \\
        --window-url https://www.sec.gov/files/structureddata/data/form-13f-data-sets/01jun2025-31aug2025_form13f.zip
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import time
import urllib.error
import urllib.request
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from data_infra.providers.openfigi_cusip_resolution import build_mapping_request, parse_mapping_response  # noqa: E402

_DEFAULT_WINDOW_URL = "https://www.sec.gov/files/structureddata/data/form-13f-data-sets/01jun2025-31aug2025_form13f.zip"

# Small, deliberately conservative set: normalized (uppercase, no
# punctuation) SUBSTRINGS that should appear in a real 13F filer's
# NAMEOFISSUER field for this company's common stock -- real company
# names as they appear on SEC filings vary in suffix (INC/CORP/CO,
# CLASS A/B, COM/COMMON STOCK), so this matches on the distinctive
# leading words only, never a full-string match that would miss real
# variants.
_TEST_TICKERS: dict[str, str] = {
    "AAPL": "APPLE INC",
    "KO": "COCA COLA CO",
    "MSFT": "MICROSOFT CORP",
}

_OPENFIGI_BATCH_SIZE = 10  # ADR-0131's own real, confirmed no-API-key limit


def _normalize(text: str) -> str:
    return "".join(ch for ch in text.upper() if ch.isalnum() or ch.isspace()).strip()


def _download_zip(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "NEW- sdh08060900@gmail.com"})
    with urllib.request.urlopen(req, timeout=120) as response:
        return response.read()


def _read_tsv_from_zip(zf: zipfile.ZipFile, filename_upper: str) -> list[dict]:
    # Real bulk archives have shown inconsistent casing/nesting across
    # SEC's own quarterly releases in the wild -- match case-insensitively
    # against the basename rather than assuming an exact path.
    candidates = [n for n in zf.namelist() if Path(n).name.upper() == filename_upper]
    if not candidates:
        raise FileNotFoundError(f"{filename_upper} not found in archive; real entries: {zf.namelist()}")
    with zf.open(candidates[0]) as fh:
        text = io.TextIOWrapper(fh, encoding="utf-8", errors="replace")
        return list(csv.DictReader(text, delimiter="\t"))


def _resolve_cusips_via_openfigi(cusips: list[str]) -> dict[str, Optional[str]]:
    resolved: dict[str, Optional[str]] = {}
    for i in range(0, len(cusips), _OPENFIGI_BATCH_SIZE):
        batch = cusips[i : i + _OPENFIGI_BATCH_SIZE]
        body = json.dumps(build_mapping_request(batch)).encode("utf-8")
        req = urllib.request.Request(
            "https://api.openfigi.com/v3/mapping", data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            response_json = json.loads(response.read().decode("utf-8"))
        resolved.update(parse_mapping_response(batch, response_json))
        if i + _OPENFIGI_BATCH_SIZE < len(cusips):
            time.sleep(2.5)  # real confirmed cap is 25 req/60s -- stay well under it
    return resolved


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--window-url", default=_DEFAULT_WINDOW_URL, help="Real SEC 13F bulk data set ZIP URL for one ~3-month filing window")
    args = parser.parse_args(argv)

    print(f"Downloading {args.window_url} ...")
    try:
        raw_zip = _download_zip(args.window_url)
    except (urllib.error.URLError, urllib.error.HTTPError) as exc:
        print(f"FATAL: could not download the bulk data set: {exc}", file=sys.stderr)
        return 1
    print(f"Downloaded {len(raw_zip):,} bytes.")

    with zipfile.ZipFile(io.BytesIO(raw_zip)) as zf:
        print(f"Archive contains {len(zf.namelist())} entries: {zf.namelist()}")
        submissions = _read_tsv_from_zip(zf, "SUBMISSION.TSV")
        infotable = _read_tsv_from_zip(zf, "INFOTABLE.TSV")

    print(f"SUBMISSION.tsv: {len(submissions)} rows. Real columns: {list(submissions[0].keys()) if submissions else '(empty)'}")
    print(f"INFOTABLE.tsv: {len(infotable)} rows. Real columns: {list(infotable[0].keys()) if infotable else '(empty)'}")

    period_of_report_by_accession = {
        row["ACCESSION_NUMBER"]: row.get("PERIODOFREPORT") for row in submissions
        if row.get("SUBMISSIONTYPE", "").startswith("13F-HR")
    }
    print(f"Real distinct PERIODOFREPORT values in this window (13F-HR only): {sorted(set(period_of_report_by_accession.values()))}")

    # Step 1+2: name-match candidates per test ticker.
    candidates_by_ticker: dict[str, set[str]] = defaultdict(set)
    for row in infotable:
        if row["ACCESSION_NUMBER"] not in period_of_report_by_accession:
            continue  # not a 13F-HR (holdings report) submission
        name = _normalize(row.get("NAMEOFISSUER", ""))
        cusip = row.get("CUSIP", "").strip()
        if not cusip:
            continue
        for ticker, expected_name in _TEST_TICKERS.items():
            if expected_name in name:
                candidates_by_ticker[ticker].add(cusip)

    all_candidate_cusips = sorted({c for cusips in candidates_by_ticker.values() for c in cusips})
    print(f"\nCandidate CUSIPs found by name-matching ({len(all_candidate_cusips)} distinct): {all_candidate_cusips}")

    if not all_candidate_cusips:
        print("FATAL: no candidate CUSIPs found for any test ticker -- name-matching logic or NAMEOFISSUER format assumption is wrong.", file=sys.stderr)
        return 1

    # Step 3: confirm each candidate via the ALREADY-real-verified CUSIP->ticker direction.
    try:
        resolved = _resolve_cusips_via_openfigi(all_candidate_cusips)
    except (urllib.error.URLError, urllib.error.HTTPError) as exc:
        print(f"FATAL: OpenFIGI confirmation call failed: {exc}", file=sys.stderr)
        return 1

    confirmed_cusip_by_ticker: dict[str, str] = {}
    for ticker, candidate_cusips in candidates_by_ticker.items():
        matches = [c for c in candidate_cusips if resolved.get(c) == ticker]
        print(f"  {ticker}: name-matched candidates={sorted(candidate_cusips)}, OpenFIGI-confirmed={matches}")
        if len(matches) == 1:
            confirmed_cusip_by_ticker[ticker] = matches[0]
        elif len(matches) > 1:
            print(f"  WARNING: {ticker} has MULTIPLE OpenFIGI-confirmed CUSIPs -- ambiguous, not auto-resolved: {matches}", file=sys.stderr)

    print(f"\nReal, doubly-confirmed ticker -> CUSIP mapping: {confirmed_cusip_by_ticker}")
    if not confirmed_cusip_by_ticker:
        print("FATAL: zero test tickers reached a doubly-confirmed CUSIP.", file=sys.stderr)
        return 1

    # Sanity aggregate: real institutional share totals for whichever
    # tickers got a confirmed CUSIP, per real PERIODOFREPORT found.
    for ticker, cusip in confirmed_cusip_by_ticker.items():
        totals: dict[str, dict[str, float]] = defaultdict(lambda: {"shares": 0.0, "filers": set()})
        for row in infotable:
            if row.get("CUSIP", "").strip() != cusip:
                continue
            accession = row["ACCESSION_NUMBER"]
            period = period_of_report_by_accession.get(accession)
            if period is None:
                continue
            try:
                shares = float(row.get("SSHPRNAMT", 0) or 0)
            except ValueError:
                continue
            totals[period]["shares"] += shares
            totals[period]["filers"].add(accession)
        for period, agg in sorted(totals.items()):
            print(f"  {ticker} ({cusip}) period={period}: total_shares={agg['shares']:,.0f}, distinct_filers={len(agg['filers'])}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
