#!/usr/bin/env python3
"""Read-only recon probes for two free, non-US exchange archive candidates
raised while looking for a new, US-lock-independent test window:
NSE (India) daily bhavcopy archives, and a TWSE (Taiwan) delisting dataset
on data.gov.tw. Prints what each source actually returns.

    python3 scripts/recon_overseas_exchanges.py nse_bhavcopy|twse_delisted
"""

from __future__ import annotations

import argparse
import io
import sys
import urllib.request
import zipfile


def recon_nse_bhavcopy() -> None:
    url = "https://archives.nseindia.com/content/historical/EQUITIES/2005/JAN/cm03JAN2005bhav.csv.zip"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            print("NSE bhavcopy status", resp.status, "bytes", len(raw))
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                names = zf.namelist()
                print("zip entries:", names)
                with zf.open(names[0]) as f:
                    lines = f.read().decode("utf-8", "replace").splitlines()
                    print("rows:", len(lines))
                    print("header:", lines[0])
                    print("sample:", lines[1:6])
    except Exception as exc:  # noqa: BLE001
        print("NSE bhavcopy ERROR", type(exc).__name__, exc)


def recon_twse_delisted() -> None:
    url = "https://data.gov.tw/api/v2/rest/dataset/11543"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            text = resp.read().decode("utf-8", "replace")
            print("data.gov.tw dataset 11543 status", resp.status, "len", len(text))
            print(text[:1500])
    except Exception as exc:  # noqa: BLE001
        print("data.gov.tw ERROR", type(exc).__name__, exc)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", choices=["nse_bhavcopy", "twse_delisted"])
    args = parser.parse_args()
    {"nse_bhavcopy": recon_nse_bhavcopy, "twse_delisted": recon_twse_delisted}[args.target]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
