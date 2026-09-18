#!/usr/bin/env python3
"""Repairs the real, pre-existing `ingestion_precedes_availability`
ERROR backlog confirmed in ADR-0167/ADR-0168 (external review,
2026-09-18: a real production run found exactly one such bar per
symbol, 87 total).

**Root cause** (confirmed by code reading, not guessed): every provider
in this package stamps a `PriceBar`'s `ingestion_time` from
`data_infra.provider.clamp_ingestion_time(batch_ingestion_time,
bar_available_time(timestamp))`, which is `max(...)` -- an inversion
(`ingestion_time < available_time`) is structurally impossible for any
bar ingested through that path. ADR-0115 (Session 37) introduced this
clamp specifically to fix this exact invariant. The 87 flagged bars
are therefore not a live, ongoing bug -- they are bars ingested BEFORE
ADR-0115 existed, sitting unfixed in the append-only price_bars store
(Raw Immutability: a bar is never rewritten in place, so a pre-fix
defect persists until something explicitly corrects it).

**Fix strategy**: never touches an existing Parquet file (that would
violate this project's own "new data always means a new file"
invariant, `storage/parquet_layer.py`'s own docstring). Instead, for
every affected bar, this script appends a NEW, corrected bar through
the completely ordinary `DuckDBDataRepository.append_bars()` path --
same `open`/`high`/`low`/`close`/`volume`/`source` content, but
`ingestion_time` clamped up to `available_time` (exactly what
`clamp_ingestion_time` would have produced had the fix existed at
original ingestion time). Since the OHLCV content is unchanged, the
`provenance.data_version` content hash would otherwise be IDENTICAL to
the original bad bar's -- indistinguishable from a true accidental
duplicate to `DataQualityFramework._check_duplicates` (ADR-0168's
ERROR branch: "identical content ... indicates a real storage-layer
bug"). This script tags the corrected bar's `data_version` with an
explicit `-ingestion-time-corrected` suffix so it is correctly
classified as a legitimate revision (WARNING, not ERROR) -- the same
mechanism ADR-0085's own overlap re-fetch already relies on.

`DuckDBDataRepository.get_bars()`'s default (non-audit) view already
picks the most-recently-ingested bar per (security_id, timestamp)
(ADR-0168) -- since the corrected bar's `ingestion_time` is later than
the original bad bar's (that is the entire nature of the bug being
fixed: the original was BEFORE its own available_time), every real
consumer (Paper Trading, backtest, strategy_research, Learning Cycle)
automatically starts seeing the corrected bar once this script runs,
with no other code change needed.

**Known, accepted limitation**: the original bad physical row is never
deleted (Raw Immutability) and will keep independently failing
`_check_ingestion_precedes_availability` on every future full-history
rescan (`scripts/rescan_data_quality.py`) forever -- that check
evaluates every physical row, not just the canonical one `get_bars()`
selects. This is a diagnostic-noise trade-off, not a correctness gap:
the actual defect (a bad bar reaching a real consumer) is fixed by
this script; a future session could make that check dedup-aware too,
miroring ADR-0168's `_check_duplicates` change, if the recurring noise
becomes a real problem.

Makes NO network call -- reads and writes only the already-persisted
local DuckDB/Parquet catalog at --db-path. Idempotent: re-running after
a successful `--apply` finds nothing left to correct (the corrected
bar's own `ingestion_time` no longer precedes its `available_time`).

Usage (dry run, the default -- reports what WOULD change, writes nothing):
    python3 scripts/repair_ingestion_time_inversions.py --db-path ./market-data-catalog

Usage (actually appends the corrected bars):
    python3 scripts/repair_ingestion_time_inversions.py --db-path ./market-data-catalog --apply
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from storage.config import StorageConfig  # noqa: E402
from storage.data_repository import DuckDBDataRepository  # noqa: E402
from storage.engine import StorageEngine  # noqa: E402

_DATA_VERSION_SUFFIX = "-ingestion-time-corrected"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db-path", required=True, type=Path, help="A market-data catalog directory (e.g. the unzipped market-data-catalog artifact)")
    parser.add_argument("--apply", action="store_true", help="Actually append the corrected bars (default: dry run, reports only)")
    args = parser.parse_args(argv)

    if not args.db_path.is_dir():
        print(f"FATAL: {args.db_path} does not exist or is not a directory", file=sys.stderr)
        return 1

    engine = StorageEngine(StorageConfig(root_dir=args.db_path))
    repository = DuckDBDataRepository(engine)
    try:
        all_bars = repository.all_bars()
        inverted = [bar for bar in all_bars if bar.ingestion_time < bar.available_time]

        if not inverted:
            print("No ingestion_time/available_time inversions found -- nothing to repair.")
            return 0

        print(f"Found {len(inverted)} bar(s) with ingestion_time < available_time:")
        for bar in inverted:
            print(
                f"  {bar.security_id} @ {bar.timestamp.isoformat()} "
                f"(source={bar.provenance.source}): ingestion_time={bar.ingestion_time.isoformat()} "
                f"< available_time={bar.available_time.isoformat()}"
            )

        corrected = [
            dataclasses.replace(
                bar,
                ingestion_time=max(bar.ingestion_time, bar.available_time),
                provenance=dataclasses.replace(
                    bar.provenance, data_version=bar.provenance.data_version + _DATA_VERSION_SUFFIX
                ),
            )
            for bar in inverted
        ]

        if not args.apply:
            print(f"\nDry run only -- would append {len(corrected)} corrected bar(s). Re-run with --apply to write them.")
            return 0

        written = repository.append_bars(corrected)
        print(f"\nAppended {written} corrected bar(s) (of {len(corrected)} candidates -- "
              "fewer than expected means this repair already ran before).")
        return 0
    finally:
        engine.close()


if __name__ == "__main__":
    sys.exit(main())
