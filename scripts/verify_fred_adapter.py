#!/usr/bin/env python3
"""Verifies `data_infra.providers.fred.FredMacroProvider` against a real
FRED API call -- one `fred/series/observations` request/response round
trip (account owner's own `FRED_API_KEY`, `workflow_dispatch`/manual
verification tool -- same pattern as `scripts/verify_gemini_adapter.py`).

Fetches a small, recent window of `DGS3MO` (3-Month Treasury Constant
Maturity Rate) -- a real, always-available public series, chosen only to
prove the real request/response shape works, not because this project
consumes it anywhere yet (see `data_infra.providers.fred`'s own
docstring on why no call site exists yet).

Credentials are read only from the `FRED_API_KEY` environment variable
(never a CLI flag, so a real secret is never visible in a process list or
shell history).

Usage:
    export FRED_API_KEY=...
    python3 scripts/verify_fred_adapter.py [--series-id DGS3MO]
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from data_infra.provider import ProviderError  # noqa: E402
from data_infra.providers.fred import FredMacroProvider  # noqa: E402
from data_infra.providers.fred_config import DEFAULT_FRED_CONFIG  # noqa: E402
from data_infra.providers.fred_transport import FredHttpTransport  # noqa: E402


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--series-id", default="DGS3MO", help="FRED series id to fetch (default: DGS3MO)")
    args = parser.parse_args(argv)

    config = DEFAULT_FRED_CONFIG
    provider = FredMacroProvider(config, FredHttpTransport(config.base_url))

    end = date.today()
    start = end - timedelta(days=14)

    try:
        observations = provider.fetch_series(args.series_id, start, end)
    except ProviderError as exc:
        print(f"FRED call FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"series_id: {args.series_id}")
    print(f"requested window: {start.isoformat()} .. {end.isoformat()}")
    print(f"observation_count: {len(observations)}")
    for obs in observations:
        print(f"  {obs.observation_date.isoformat()}: {obs.value}")

    if not observations:
        print("FRED returned zero observations for this window -- unexpected for a 14-day window of DGS3MO", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
