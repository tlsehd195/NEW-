#!/usr/bin/env python3
"""Merges the per-series macro stores written by the matrix jobs of
`ingest_fred_macro_vintages.yml` (one `ingest_fred_macro_vintages.py`
run per FRED series, ADR-0217) into one store, and their coverage
reports into one JSON file. Inserts are idempotent on the natural key,
so re-merging the same inputs changes nothing.

Usage:
    python3 scripts/merge_macro_stores.py --out-db-path macro-store \\
        --summary-json macro_coverage.json parts/*/
where each input directory holds `macro-store/catalog.duckdb` and
optionally `macro_coverage.json`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from storage.config import StorageConfig  # noqa: E402
from storage.engine import StorageEngine  # noqa: E402
from storage.macro_repository import DuckDBMacroRepository  # noqa: E402


def merge(out_db_path: str, inputs: list[Path]) -> dict:
    out_engine = StorageEngine(StorageConfig(root_dir=out_db_path))
    out_repo = DuckDBMacroRepository(out_engine)
    series: list[dict] = []
    failed: list[str] = []
    try:
        for part in inputs:
            store = part / "macro-store"
            if (store / "catalog.duckdb").exists():
                engine = StorageEngine(StorageConfig(root_dir=store), read_only=True)
                try:
                    repo = DuckDBMacroRepository(engine)
                    for series_id in repo.list_series_ids():
                        out_repo.add_macro_observations(repo.get_all_vintages(series_id))
                finally:
                    engine.close()
            summary_path = part / "macro_coverage.json"
            if summary_path.exists():
                summary = json.loads(summary_path.read_text())
                series.extend(summary.get("series", []))
                failed.extend(summary.get("failed", []))
    finally:
        out_engine.close()
    return {"series": sorted(series, key=lambda s: s["series_id"]), "failed": sorted(failed)}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out-db-path", required=True)
    parser.add_argument("--summary-json", required=True)
    parser.add_argument("inputs", nargs="+")
    args = parser.parse_args(argv)
    result = merge(args.out_db_path, [Path(p) for p in args.inputs])
    Path(args.summary_json).write_text(json.dumps(result, indent=2))
    print(f"merged {len(result['series'])} series; failed: {result['failed']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
