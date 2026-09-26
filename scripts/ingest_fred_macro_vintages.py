#!/usr/bin/env python3
"""Ingests point-in-time (ALFRED vintage) FRED macro series into a
DuckDB store's `macro_observation_vintages` table (ADR-0217), and
prints a per-series coverage report of what the real data actually
looks like: how far back the archived vintages go, the typical release
lag, and how often values were revised.

The coverage report is the point of the first real run: the macro-
filter design in ADR-0217 depends on facts only real ALFRED data can
confirm (e.g. whether a daily series' archived vintages reach back to
2000, or only a few years).

Makes REAL network calls to api.stlouisfed.org -- this project's
development sandbox cannot reach it, a GitHub Actions runner can
(`ingest_fred_macro_vintages.yml`). The key is read only from the
`FRED_API_KEY` environment variable.

Usage:
    export FRED_API_KEY=...
    python3 scripts/ingest_fred_macro_vintages.py --db-path macro-store \\
        [--start 1990-01-01] [--end 2026-09-26] [--series CPIAUCSL,PAYEMS] \\
        [--summary-json macro_coverage.json]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from data_infra.macro_models import MACRO_SERIES_BY_ID, MACRO_SERIES_CATALOG  # noqa: E402
from data_infra.provider import ProviderError  # noqa: E402
from data_infra.providers.fred import (  # noqa: E402
    FredMacroProvider,
    FredVintageObservation,
    vintage_to_macro_record,
)
from data_infra.providers.fred_config import DEFAULT_FRED_CONFIG  # noqa: E402
from data_infra.providers.fred_transport import FredHttpTransport  # noqa: E402
from storage.config import StorageConfig  # noqa: E402
from storage.engine import StorageEngine  # noqa: E402
from storage.macro_repository import DuckDBMacroRepository  # noqa: E402


def coverage_summary(series_id: str, observations: list[FredVintageObservation]) -> dict:
    """Facts about one series' real vintages; pure, so it is tested
    without the network."""
    by_date: dict[date, list[FredVintageObservation]] = defaultdict(list)
    for obs in observations:
        by_date[obs.observation_date].append(obs)
    if not by_date:
        return {"series_id": series_id, "vintage_rows": 0}

    first_vintage = min(o.realtime_start for o in observations)
    release_lags: list[int] = []
    revised = 0
    stamped_with_first_vintage = 0
    for obs_date, rows in by_date.items():
        first_seen = min(r.realtime_start for r in rows)
        # Observations older than the first archived vintage all show
        # that vintage as their start; their "lag" says nothing about
        # the real release schedule.
        if first_seen > first_vintage:
            release_lags.append((first_seen - obs_date).days)
        else:
            stamped_with_first_vintage += 1
        if len({r.value for r in rows if r.value is not None}) > 1:
            revised += 1

    return {
        "series_id": series_id,
        "vintage_rows": len(observations),
        "observation_dates": len(by_date),
        "first_observation_date": min(by_date).isoformat(),
        "last_observation_date": max(by_date).isoformat(),
        "first_vintage_date": first_vintage.isoformat(),
        "distinct_vintages": len({o.realtime_start for o in observations}),
        "observations_stamped_with_first_vintage": stamped_with_first_vintage,
        "median_release_lag_days": statistics.median(release_lags) if release_lags else None,
        "max_release_lag_days": max(release_lags) if release_lags else None,
        "revised_observation_share": round(revised / len(by_date), 4),
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db-path", required=True, help="storage root directory (catalog.duckdb is created inside)")
    parser.add_argument("--start", default="1990-01-01", help="first observation date (default 1990-01-01)")
    parser.add_argument("--end", default=None, help="last observation date (default today)")
    parser.add_argument("--series", default="", help="comma-separated series ids (default: the whole catalog)")
    parser.add_argument("--summary-json", default=None)
    args = parser.parse_args(argv)

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end) if args.end else date.today()
    if args.series:
        series_ids = [s.strip() for s in args.series.split(",") if s.strip()]
        unknown = [s for s in series_ids if s not in MACRO_SERIES_BY_ID]
        if unknown:
            print(f"unknown series (not in MACRO_SERIES_CATALOG): {unknown}", file=sys.stderr)
            return 2
    else:
        series_ids = [spec.series_id for spec in MACRO_SERIES_CATALOG]

    config = DEFAULT_FRED_CONFIG
    provider = FredMacroProvider(config, FredHttpTransport(config.base_url))
    engine = StorageEngine(StorageConfig(root_dir=args.db_path))
    repo = DuckDBMacroRepository(engine)

    summaries: list[dict] = []
    failed: list[str] = []
    try:
        for series_id in series_ids:
            try:
                observations = provider.fetch_series_vintages(series_id, start, end)
            except ProviderError as exc:
                print(f"{series_id}: FAILED {type(exc).__name__}: {exc}", file=sys.stderr)
                failed.append(series_id)
                continue
            ingestion_time = datetime.now(timezone.utc)
            repo.add_macro_observations([vintage_to_macro_record(o, ingestion_time=ingestion_time) for o in observations])
            summary = coverage_summary(series_id, observations)
            summaries.append(summary)
            print(json.dumps(summary, sort_keys=True))
    finally:
        engine.close()

    if args.summary_json:
        Path(args.summary_json).write_text(
            json.dumps({"start": start.isoformat(), "end": end.isoformat(), "series": summaries, "failed": failed}, indent=2)
        )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
