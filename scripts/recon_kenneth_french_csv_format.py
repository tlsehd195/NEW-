#!/usr/bin/env python3
"""One-shot follow-up to `recon_kenneth_french_library.py`: that script
only confirmed the zip download itself returns HTTP 200 from a GitHub
Actions runner (this session's own egress cannot reach
`mba.tuck.dartmouth.edu` at all). It never looked inside the zip.

Before writing any real CSV parser for this data, this script
downloads the real zip(s), extracts the real CSV, and prints its
actual first/last lines verbatim -- Kenneth French's own CSV files are
well-known to mix a header preamble, blank-line-separated
monthly/annual sections, and a trailing legal/description footer, but
the EXACT real layout must be seen, not assumed, before a parser is
trusted (same "verify against one real symbol before trusting it"
discipline `ingest_insider_transactions.py`'s own docstring already
applies to a different real data source).

Checks BOTH the monthly and the DAILY 3-factor file: this project's
own `strategy_research.factor_scores.idiosyncratic_volatility_score`
docstring explicitly says it skips its own paper's real SMB/HML control
because "this project's universe ... has no independently-constructed
SMB/HML series to regress against" for a TRAILING ONE MONTH window of
DAILY returns -- the monthly file alone cannot fill that specific real
gap, only the daily one can.

Makes real network calls -- meant to run only where egress reaches
`mba.tuck.dartmouth.edu` (confirmed for GitHub Actions runners by
`recon_kenneth_french_library.py`; NOT this session's own sandbox).

Usage:
    python3 scripts/recon_kenneth_french_csv_format.py
"""

from __future__ import annotations

import io
import sys
import urllib.request
import zipfile

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_CANDIDATE_URLS = [
    "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_CSV.zip",
    "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_daily_CSV.zip",
]


def _inspect(url: str) -> None:
    print(f"=== {url} ===")
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        raw_zip = response.read()
    print(f"zip size: {len(raw_zip)} bytes")

    with zipfile.ZipFile(io.BytesIO(raw_zip)) as zf:
        names = zf.namelist()
        print(f"zip contents: {names}")
        csv_name = names[0]
        csv_text = zf.read(csv_name).decode("utf-8", errors="replace")

    lines = csv_text.splitlines()
    print(f"total lines: {len(lines)}")
    print("--- first 20 lines ---")
    for line in lines[:20]:
        print(repr(line))
    print("--- last 15 lines ---")
    for line in lines[-15:]:
        print(repr(line))

    # Kenneth French's files often have a second (annual) section after
    # a blank line -- find and print around the first blank line too,
    # so the monthly/annual boundary is visible for real, not guessed.
    blank_indices = [i for i, line in enumerate(lines) if line.strip() == ""]
    print(f"blank line indices (first 5): {blank_indices[:5]}")
    if blank_indices:
        first_blank = blank_indices[0]
        print(f"--- 5 lines around first blank line (index {first_blank}) ---")
        for line in lines[max(0, first_blank - 2):first_blank + 8]:
            print(repr(line))
    print()


def main() -> int:
    for url in _CANDIDATE_URLS:
        _inspect(url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
