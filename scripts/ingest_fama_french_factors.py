#!/usr/bin/env python3
"""Real ingestion of Kenneth French Data Library 3-factor (Mkt-RF,
SMB, HML, RF) return series -- the backlog item docs/PROJECT_STATUS.md
tracked as "SEC Financial Statement Data Sets / Kenneth French Data
Library" (2026-09-17 entry #7), and the concrete real motivation
`strategy_research.factor_scores.idiosyncratic_volatility_score`'s own
docstring already names: that factor's real implementation skips the
original paper's SMB/HML control specifically because "this project's
universe ... has no independently-constructed SMB/HML series to
regress against" for a trailing ONE MONTH window of DAILY returns.

This session's own egress blocks `mba.tuck.dartmouth.edu` outright
(confirmed by direct `curl`). `recon_kenneth_french_library.py`
confirmed for real that a GitHub Actions runner's own (separate,
broader) egress reaches it with real HTTP 200s, and
`recon_kenneth_french_csv_format.py` then confirmed, for real, the
exact CSV layout inside both the daily and monthly 3-factor zips this
script parses (never assumed):

- A short preamble of free-text lines, then a blank line.
- A header line, always exactly ``,Mkt-RF,SMB,HML,RF``.
- Data rows ``PERIOD,Mkt-RF,SMB,HML,RF`` (values in PERCENT, e.g.
  ``0.09`` means +0.09%): ``PERIOD`` is ``YYYYMMDD`` in the daily file,
  ``YYYYMM`` in the monthly file's first (monthly) section.
- A blank line terminates that section (the daily file has no further
  sections; the monthly file's real second section, at YEARLY
  granularity, follows -- this script deliberately stops at the first
  blank line after the header, so it only ever ingests the section
  matching the requested --frequency, never the monthly file's annual
  rows).
- A trailing copyright/legal footer line.

**Storage, deliberately reusing existing infra rather than a new
table**: each of the 4 factor series is stored as its own
`BenchmarkPoint` series (`benchmark_points` table, the same one
`backtest.total_return.build_total_return_benchmark_points` already
populates for SPY) -- a synthetic TOTAL_RETURN cumulative index
(`base_level=100.0`, compounding the real percent returns day over
day), NOT a new schema. `benchmark_id` is frequency-scoped
(``FF_DAILY_MKT_RF``/``FF_DAILY_SMB``/``FF_DAILY_HML``/``FF_DAILY_RF``
or the ``FF_MONTHLY_*`` equivalents) so daily and monthly series never
collide if both are ever ingested into the same catalog.

**Deliberate non-goal, RULE 0.8**: this script only makes the real
factor-return data available for a future consumer to read via the
existing `DuckDBDataRepository.get_benchmark` API -- it does NOT wire
`idiosyncratic_volatility_score` (or any other factor) to actually USE
this data. Whether/how to add a real SMB/HML regression control is a
separate, deliberate strategy-formula decision this script's own
addition does not make, matching this project's own established
two-step discipline (e.g. SEC 13F institutional-ownership data was
ingested and stored, ADR-0131, before any score was wired to read it,
ADR-0134).

Makes REAL network calls -- run this only where egress reaches
`mba.tuck.dartmouth.edu` (confirmed for GitHub Actions runners, NOT
this project's own development sandbox).

Usage:
    python3 scripts/ingest_fama_french_factors.py \\
        --frequency daily \\
        --as-of 2026-09-19 \\
        --db-path ./data/fama_french_factors
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from data_infra.enums import BenchmarkReturnType  # noqa: E402
from data_infra.models import BenchmarkPoint, Provenance  # noqa: E402
from data_infra.versioning import compute_data_version  # noqa: E402
from storage.config import StorageConfig  # noqa: E402
from storage.data_repository import DuckDBDataRepository  # noqa: E402
from storage.engine import StorageEngine  # noqa: E402

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_URLS = {
    "daily": "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_daily_CSV.zip",
    "monthly": "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_CSV.zip",
}
_HEADER_LINE = ",Mkt-RF,SMB,HML,RF"
_FACTOR_NAMES = ("mkt_rf", "smb", "hml", "rf")


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def fetch_zip_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def _parse_period(period: str) -> datetime:
    """``YYYYMMDD`` (daily) or ``YYYYMM`` (monthly, first-of-month)."""
    period = period.strip()
    if len(period) == 8:
        return datetime.strptime(period, "%Y%m%d").replace(tzinfo=timezone.utc)
    if len(period) == 6:
        return datetime.strptime(period + "01", "%Y%m%d").replace(tzinfo=timezone.utc)
    raise ValueError(f"unrecognized Fama-French period string: {period!r}")


def parse_ff_three_factor_csv(csv_text: str) -> list[dict]:
    """Extracts ONLY the data section immediately following the real,
    confirmed ``,Mkt-RF,SMB,HML,RF`` header line, stopping at the first
    blank line after it -- for the daily file this is the whole (only)
    data section; for the monthly file this is specifically the
    MONTHLY section, never the trailing annual one. Values are
    converted from percent (Kenneth French's own convention) to a
    fraction (``0.09`` -> ``0.0009``). Raises ``ValueError`` if the
    expected header line is never found (fail loudly rather than
    silently returning nothing for a real-format-drift case)."""
    lines = csv_text.splitlines()
    try:
        header_index = lines.index(_HEADER_LINE)
    except ValueError as exc:
        raise ValueError(f"expected header line {_HEADER_LINE!r} not found in CSV") from exc

    rows: list[dict] = []
    for line in lines[header_index + 1:]:
        if line.strip() == "":
            break
        fields = [f.strip() for f in line.split(",")]
        if len(fields) != 5:
            raise ValueError(f"expected 5 comma-separated fields, got {len(fields)}: {line!r}")
        period_str, *values = fields
        rows.append({
            "date": _parse_period(period_str),
            "mkt_rf": float(values[0]) / 100.0,
            "smb": float(values[1]) / 100.0,
            "hml": float(values[2]) / 100.0,
            "rf": float(values[3]) / 100.0,
        })
    return rows


def build_factor_benchmark_points(
    benchmark_id: str, rows: list[dict], factor_name: str, *, as_of_time: datetime,
    base_level: float = 100.0, source: str = "kenneth_french_data_library",
) -> list[BenchmarkPoint]:
    """Same base_level=100.0/compounding convention as
    `backtest.total_return.build_total_return_benchmark_points` -- the
    first row's level IS base_level (its own real return is not
    separately applied, mirroring that function's `i == 0` skip
    exactly), every later row compounds the prior level by
    ``(1 + that day's real fractional return)``."""
    points: list[BenchmarkPoint] = []
    level = base_level
    for i, row in enumerate(rows):
        if i > 0:
            level = level * (1.0 + row[factor_name])
        points.append(
            BenchmarkPoint(
                benchmark_id=benchmark_id,
                timestamp=row["date"],
                level=level,
                return_type=BenchmarkReturnType.TOTAL_RETURN,
                currency="USD",
                available_time=as_of_time,
                ingestion_time=as_of_time,
                provenance=Provenance(
                    source=source,
                    source_dataset=f"{source}_{benchmark_id}",
                    source_record_id=f"{benchmark_id}:{row['date'].isoformat()}",
                    retrieved_at=as_of_time,
                    data_version=compute_data_version(
                        {"benchmark_id": benchmark_id, "date": row["date"], "level": level}
                    ),
                ),
            )
        )
    return points


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--frequency", choices=sorted(_URLS), default="daily", help="Which real Kenneth French 3-factor file to ingest (default: daily -- the file idiosyncratic_volatility_score's own real gap needs)")
    parser.add_argument("--as-of", required=True, type=_parse_date, help="YYYY-MM-DD, stands in for this run's real-world timestamp (retrieved_at/ingestion_time/available_time) -- never derived from wall-clock time")
    parser.add_argument("--db-path", required=True, type=Path, help="Directory for the DuckDB catalog (created if it does not exist)")
    parser.add_argument("--manifest-out", type=Path, default=None, help="Where to write the JSON reproducibility manifest (default: <db-path>/fama_french_ingestion_manifest.json)")
    args = parser.parse_args(argv)

    manifest_path = args.manifest_out or (args.db_path / "fama_french_ingestion_manifest.json")
    url = _URLS[args.frequency]
    benchmark_prefix = f"FF_{args.frequency.upper()}_"

    print(f"Fetching {url} ...", flush=True)
    try:
        raw_zip = fetch_zip_bytes(url)
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        print(f"FATAL: could not fetch Kenneth French {args.frequency} 3-factor zip: {exc}", file=sys.stderr)
        return 1
    print(f"Fetched {len(raw_zip)} byte(s). Extracting CSV...", flush=True)

    with zipfile.ZipFile(io.BytesIO(raw_zip)) as zf:
        csv_name = zf.namelist()[0]
        csv_text = zf.read(csv_name).decode("utf-8", errors="replace")

    try:
        rows = parse_ff_three_factor_csv(csv_text)
    except ValueError as exc:
        print(f"FATAL: could not parse {csv_name}: {exc}", file=sys.stderr)
        return 1
    print(f"Parsed {len(rows)} real {args.frequency} row(s), {rows[0]['date'].date()} through {rows[-1]['date'].date()}.", flush=True)

    engine = StorageEngine(StorageConfig(root_dir=args.db_path))
    repository = DuckDBDataRepository(engine)
    try:
        benchmark_ids = {}
        for factor_name in _FACTOR_NAMES:
            benchmark_id = f"{benchmark_prefix}{factor_name.upper()}"
            points = build_factor_benchmark_points(benchmark_id, rows, factor_name, as_of_time=args.as_of)
            for point in points:
                repository.add_benchmark_point(point)
            benchmark_ids[factor_name] = benchmark_id
            print(f"  {benchmark_id}: {len(points)} point(s) persisted", flush=True)

        checksum = compute_data_version({
            "frequency": args.frequency,
            "row_count": len(rows),
            "start_date": rows[0]["date"].date().isoformat(),
            "end_date": rows[-1]["date"].date().isoformat(),
        })
        manifest = {
            "note": (
                "This manifest describes a real ingestion run against the "
                "Kenneth French Data Library's live 3-factor CSV. Values "
                "reflect whatever that file actually contained at run "
                "time -- NOT reproduced or asserted by this repository's "
                "own test suite, which never makes real network calls. "
                "This data is stored for a future consumer to read; no "
                "existing factor score is wired to use it yet (see this "
                "script's own module docstring, RULE 0.8)."
            ),
            "data_status": "REAL",
            "provider": "kenneth_french_data_library",
            "source_url": url,
            "frequency": args.frequency,
            "row_count": len(rows),
            "start_date": rows[0]["date"].date().isoformat(),
            "end_date": rows[-1]["date"].date().isoformat(),
            "benchmark_ids": benchmark_ids,
            "as_of": args.as_of.isoformat(),
            "db_path": str(args.db_path),
            "content_checksum": checksum,
            "data_version": checksum,
        }
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2, default=str))
        print(f"Manifest written to: {manifest_path}")
        return 0
    finally:
        engine.close()


if __name__ == "__main__":
    sys.exit(main())
