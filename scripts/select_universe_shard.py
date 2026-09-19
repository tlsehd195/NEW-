#!/usr/bin/env python3
"""Deterministically splits a named universe's symbols into
`--shard-count` shards for a GitHub Actions matrix job -- each shard
is meant to run `scripts/ingest_insider_transactions.py` against its
own ISOLATED `--db-path` (never a shared one: DuckDB allows only one
read/write connection to a given file at a time, `StorageEngine`'s own
docstring, so parallel matrix jobs writing to the same catalog would
corrupt it). `scripts/merge_insider_transaction_catalogs.py` combines
the resulting per-shard catalogs afterward.

Assignment is `sorted(universe)[shard_index::shard_count]` -- sorted
first so the split is deterministic and reproducible regardless of the
universe module's own declaration order; a symbol's shard never
changes as long as `--shard-count` stays the same, and changing
`--shard-count` only reshuffles which shard each symbol lands in, not
whether it's covered at all.

Prints the shard's symbols space-separated on stdout, matching
`ingest_insider_transactions.py --symbols`'s own `nargs="+"` form, so
the two compose directly:
    python3 scripts/ingest_insider_transactions.py \\
        --symbols $(python3 scripts/select_universe_shard.py \\
            --universe RESEARCH_UNIVERSE --shard-index 0 --shard-count 10) \\
        ...

Makes NO network call -- pure symbol-list arithmetic.

Usage:
    python3 scripts/select_universe_shard.py \\
        --universe RESEARCH_UNIVERSE --shard-index 0 --shard-count 10
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from data_infra.universe import PILOT_UNIVERSE_V1, RESEARCH_UNIVERSE_STAGE4  # noqa: E402

_UNIVERSES = {"PILOT_UNIVERSE": PILOT_UNIVERSE_V1, "RESEARCH_UNIVERSE": RESEARCH_UNIVERSE_STAGE4}


def select_shard(symbols, *, shard_index: int, shard_count: int) -> list[str]:
    if shard_count <= 0:
        raise ValueError(f"shard_count must be positive, got {shard_count}")
    if not (0 <= shard_index < shard_count):
        raise ValueError(f"shard_index must be in [0, {shard_count}), got {shard_index}")
    return sorted(symbols)[shard_index::shard_count]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--universe", choices=sorted(_UNIVERSES), default="RESEARCH_UNIVERSE", help="Named universe from src/data_infra/universe.py (default: RESEARCH_UNIVERSE)")
    parser.add_argument("--shard-index", type=int, required=True, help="0-based index of the shard to print")
    parser.add_argument("--shard-count", type=int, required=True, help="Total number of shards")
    args = parser.parse_args(argv)

    try:
        shard = select_shard(
            _UNIVERSES[args.universe].symbol_ids, shard_index=args.shard_index, shard_count=args.shard_count
        )
    except ValueError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 1

    if not shard:
        print(f"FATAL: shard {args.shard_index} of {args.shard_count} is empty for {args.universe} -- shard_count is larger than the universe", file=sys.stderr)
        return 1

    print(" ".join(shard))
    return 0


if __name__ == "__main__":
    sys.exit(main())
