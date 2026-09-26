#!/usr/bin/env python3
"""Real, multi-quarter institutional-ownership backfill from SEC's bulk
Form 13F structured data sets -- produces the `security_id,quarter_end,
institutional_shares,num_institutions` combined CSV
`scripts/ingest_institutional_holdings.py --combined-csv` already
consumes unchanged (`ADR-0131`'s own existing pipeline, previously only
ever fed from ONE filer's own filing).

**Prerequisite**: `scripts/build_institutional_ownership_cusip_map.py`
must already have produced a real, doubly-confirmed `{ticker: cusip}`
JSON map (`--cusip-map`) -- this script never resolves a CUSIP itself.

**Two-pass design, not one window at a time in isolation** -- a
`13F-HR/A` amendment for one filing period can legitimately land in a
LATER window file than the period's own original submission
(`data_infra.providers.sec_13f_bulk_dataset`'s own docstring, point 2,
real-confirmed). Deciding the winning submission window-by-window would
silently miss a later amendment that supersedes an earlier window's
data. This script therefore:

    Pass 1 (one download per window): accumulate EVERY real 13F-HR/
    13F-HR/A submission record across ALL requested windows, and every
    real INFOTABLE row already filtered down to this run's own known
    CUSIPs (a tiny fraction of a window's real several-million rows,
    so this stays cheap in memory across dozens of windows).

    Pass 2 (after every window is downloaded): `latest_submission_
    per_period` runs ONCE across the GLOBAL accumulated submissions
    (not per-window), then `aggregate_holdings` runs ONCE across the
    GLOBAL accumulated, already-filtered INFOTABLE rows.

A window this run requests but SEC never published (this script does
not itself know how far back SEC's real archive goes) is skipped with
a loud warning, never silently treated as zero real data -- the run's
own summary reports exactly which windows were skipped.

Usage:
    python3 scripts/backfill_institutional_holdings_from_sec_bulk.py \\
        --cusip-map cusip_map.json \\
        --start-year 2010 --through-date 2023-04-28 \\
        --out combined_institutional_holdings.csv
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import urllib.error
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from data_infra.institutional_holding_models import THIRTEEN_F_FILING_DEADLINE_DAYS  # noqa: E402
from data_infra.providers.sec_13f_bulk_dataset import (  # noqa: E402
    SubmissionRecord,
    aggregate_holdings,
    dedupe_infotable_rows,
    generate_filing_windows,
    latest_submission_per_period,
    parse_submission_rows,
)


_KEPT_INFOTABLE_COLUMNS = ("ACCESSION_NUMBER", "INFOTABLE_SK", "CUSIP", "SSHPRNAMT", "SSHPRNAMTTYPE", "PUTCALL")


def _download_zip(url: str, *, user_agent: str) -> Optional[bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(req, timeout=180) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None  # this window was never published -- not a real error
        raise


def _read_tsv_from_zip(zf: zipfile.ZipFile, filename_upper: str) -> list[dict]:
    candidates = [n for n in zf.namelist() if Path(n).name.upper() == filename_upper]
    if not candidates:
        raise FileNotFoundError(f"{filename_upper} not found in archive; real entries: {zf.namelist()}")
    with zf.open(candidates[0]) as fh:
        text = io.TextIOWrapper(fh, encoding="utf-8", errors="replace")
        return list(csv.DictReader(text, delimiter="\t"))


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--user-agent", required=True, help="SEC fair-access contact string (real, reachable identifier)")
    parser.add_argument("--cusip-map", required=True, type=Path, help="JSON {ticker: cusip} from build_institutional_ownership_cusip_map.py")
    parser.add_argument("--start-year", required=True, type=int, help="Earliest calendar year to request filing windows for (windows are generated from 01mar of this year)")
    parser.add_argument("--through-date", required=True, type=str, help="YYYY-MM-DD -- generate windows up through whichever window covers this date")
    parser.add_argument("--out", required=True, type=Path, help="Where to write the combined CSV (security_id,quarter_end,institutional_shares,num_institutions)")
    args = parser.parse_args(argv)

    cusip_to_ticker: dict[str, str] = {v: k for k, v in json.loads(args.cusip_map.read_text()).items()}
    if not cusip_to_ticker:
        print(f"FATAL: {args.cusip_map} contains no entries", file=sys.stderr)
        return 1
    print(f"Loaded {len(cusip_to_ticker)} confirmed ticker/CUSIP pairs.")

    through_date = datetime.strptime(args.through_date, "%Y-%m-%d").date()
    windows = generate_filing_windows(args.start_year, through_date)
    print(f"Requesting {len(windows)} real filing windows: {windows[0].start} .. {windows[-1].end}")

    all_submissions: list[SubmissionRecord] = []
    all_filtered_infotable_rows: list[dict] = []
    skipped_windows: list[str] = []

    for i, window in enumerate(windows, start=1):
        print(f"[{i}/{len(windows)}] {window.url} ...", flush=True)
        try:
            raw_zip = _download_zip(window.url, user_agent=args.user_agent)
        except (urllib.error.URLError, urllib.error.HTTPError) as exc:
            print(f"  WARNING: real download failure (not a 404) for this window -- skipped: {exc}", file=sys.stderr)
            skipped_windows.append(window.url)
            continue
        if raw_zip is None:
            print("  Not published by SEC (real 404) -- skipped, not treated as zero data.", file=sys.stderr)
            skipped_windows.append(window.url)
            continue

        with zipfile.ZipFile(io.BytesIO(raw_zip)) as zf:
            submission_rows = _read_tsv_from_zip(zf, "SUBMISSION.TSV")
            infotable_rows = _read_tsv_from_zip(zf, "INFOTABLE.TSV")

        window_submissions = parse_submission_rows(submission_rows)
        all_submissions.extend(window_submissions)

        kept = 0
        for row in infotable_rows:
            if row.get("CUSIP", "").strip() in cusip_to_ticker:
                # Only the columns aggregation/dedup read -- dozens of
                # windows' matched rows are held at once (pass 2).
                all_filtered_infotable_rows.append({k: row.get(k) for k in _KEPT_INFOTABLE_COLUMNS if k in row})
                kept += 1
        infotable_row_count = len(infotable_rows)
        del infotable_rows
        print(f"  {len(submission_rows)} submissions ({len(window_submissions)} real 13F-HR/13F-HR/A), {infotable_row_count} infotable rows ({kept} matched a known CUSIP).")

    if skipped_windows:
        print(f"\n{len(skipped_windows)} window(s) skipped (not published, or a real download failure): {skipped_windows}")

    print(f"\nTotal accumulated: {len(all_submissions)} real submissions, {len(all_filtered_infotable_rows)} matched infotable rows across {len(windows) - len(skipped_windows)} real windows.")

    before = len(all_filtered_infotable_rows)
    all_filtered_infotable_rows = dedupe_infotable_rows(all_filtered_infotable_rows)
    print(f"Dropped {before - len(all_filtered_infotable_rows)} duplicate infotable rows (same accession in two overlapping files).")

    winning_period_by_accession = latest_submission_per_period(
        all_submissions, max_filing_lag_days=THIRTEEN_F_FILING_DEADLINE_DAYS,
    )
    print(
        f"Real, deduplicated (latest-amendment-wins, filed within {THIRTEEN_F_FILING_DEADLINE_DAYS} days "
        f"of period end) winning submissions: {len(winning_period_by_accession)}."
    )

    aggregated = aggregate_holdings(all_filtered_infotable_rows, winning_period_by_accession, cusip_to_ticker)
    print(f"Real aggregated (security_id, quarter_end) rows: {len(aggregated)}.")
    if not aggregated:
        print("FATAL: zero aggregated holdings produced -- check the CUSIP map and window range.", file=sys.stderr)
        return 1

    with args.out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["security_id", "quarter_end", "institutional_shares", "num_institutions"])
        for holding in sorted(aggregated, key=lambda h: (h.security_id, h.quarter_end)):
            writer.writerow([holding.security_id, holding.quarter_end.isoformat(), holding.institutional_shares, holding.num_institutions])
    print(f"Wrote {args.out} ({len(aggregated)} rows).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
