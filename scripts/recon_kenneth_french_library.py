#!/usr/bin/env python3
"""One-shot reconnaissance for the "Kenneth French Data Library" backlog
item (docs/PROJECT_STATUS.md, 2026-09-17 entry #7: "SEC Financial
Statement Data Sets / Kenneth French Data Library ... 둘 다 이 세션
egress에서 403 차단 확인됨"). This session's own egress blocks
`mba.tuck.dartmouth.edu` outright, so nothing about it can be verified
from here.

Kenneth French's own library is a well-known, free, public academic
data source (Fama-French factor returns -- market/size/value/momentum
etc.) this project's own factor research already has an interest in
(several existing factors, e.g. `low_beta_score`/`size`-style
candidates, are literature-motivated the same way). This script makes
NO assumption about whether the download actually works from GitHub
Actions -- it just requests the data library's own index page and one
well-known CSV zip download link and prints the real HTTP status +
content-type + byte count, nothing more. The actual ingestion approach
should be decided from what this reconnaissance run actually shows.

Makes real network calls -- meant to run where egress is NOT blocked
(this project's GitHub Actions runners; unverified from this session).

Usage:
    python3 scripts/recon_kenneth_french_library.py
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_MAX_BODY_PREVIEW_BYTES = 500

_CANDIDATE_URLS = [
    "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html",
    # The canonical Fama-French 3-factor CSV zip -- widely referenced
    # by academic tooling under this exact path.
    "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_CSV.zip",
]


def _fetch(url: str) -> tuple[int | None, str, int]:
    """Returns (status, content_type, body_length_seen). Reads at most
    `_MAX_BODY_PREVIEW_BYTES` -- for a binary zip this is just enough
    to confirm it looks like a real zip (`PK` magic bytes), never
    meant to validate the whole archive."""
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read(_MAX_BODY_PREVIEW_BYTES)
            content_type = response.headers.get("Content-Type", "unknown")
            return response.status, content_type, len(body)
    except urllib.error.HTTPError as exc:
        body = exc.read(_MAX_BODY_PREVIEW_BYTES)
        return exc.code, exc.headers.get("Content-Type", "unknown") if exc.headers else "unknown", len(body)
    except urllib.error.URLError as exc:
        return None, f"URLError: {exc.reason}", 0


def main() -> int:
    for url in _CANDIDATE_URLS:
        print(f"=== {url} ===")
        status, content_type, body_len = _fetch(url)
        print(f"status: {status}")
        print(f"content-type: {content_type}")
        print(f"bytes read (preview cap {_MAX_BODY_PREVIEW_BYTES}): {body_len}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
