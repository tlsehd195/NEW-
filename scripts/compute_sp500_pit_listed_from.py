#!/usr/bin/env python3
"""Real S&P 500 point-in-time membership -> `listed_from` computation
CLI (Session 36, ADR-0061).

`data_infra.providers.sp500_pit_membership` (ADR-0037) already parses
and reconstructs membership intervals from the real, MIT-licensed
`hanshof/sp500_constituents` scrape
(https://github.com/hanshof/sp500_constituents) -- verified there, not
re-verified here. That ADR's own "Consequences" section deliberately
left wiring its output into an actual `UniverseDefinition`'s
`SymbolMetadata.listed_from`/`listed_to` as a separate, future step.
This script is that step's data-computation half.

**Why a script, not an inline one-off**: the source CSV
(`sp_500_historical_components.csv`, ~6.7MB) is deliberately NOT
committed to this repository (ADR-0037 Decision 4/Consequences,
matching the `LocalFileDataProvider` external-acquisition pattern) --
a caller supplies its local path at run time. This script makes the
computation reproducible against a fresh copy of that file (e.g. after
the upstream scraper adds more recent snapshots) rather than being a
throwaway calculation whose provenance is lost.

**Deliberately does NOT write into `src/data_infra/universe.py`.**
Same division of responsibility `fetch_sector_classifications.py`
(ADR-0058) already established: this script writes its real findings
to a JSON report; applying them to `universe.py`'s `SymbolMetadata`
literals is a deliberate manual follow-up step.

**Only `listed_from` is ever proposed here, never `listed_to`.** Every
symbol in this project's own universes was selected because it is a
CURRENT large-cap holding -- if the real data shows it is still an
S&P 500 member as of the source file's last snapshot
(`right_censored=True`), setting `listed_to` would be fabricating a
delisting/removal that never happened. A symbol found to have
genuinely LEFT the index before the last snapshot (`right_censored=
False`) is reported but flagged `left_the_index=True` for a human to
review by hand -- not auto-converted to a `listed_to` value, since
that would need the *removal* date's own uncertainty window read
correctly by a human, not silently encoded as if exact.

**Known, honestly-disclosed limitation carried over from ADR-0037,
restated here at the point of consumption**: this dataset (and this
project's own `security_id == ticker` model) tracks TICKER STRINGS,
not durable corporate identity. A ticker's `first_seen` date in the
S&P 500 reflects when THAT TICKER STRING first appeared in a snapshot
-- for a company that changed its ticker (a rename), was created by a
spinoff, or emerged from a merger under a new or reused ticker, this
can differ from "when this business first became part of the S&P
500" in a way this dataset cannot itself distinguish (same class of
gap `audit_survivorship`'s own "permanent identity is not yet distinct
from ticker" finding already documents). This script does not attempt
to classify which of the 87 Stage 4 symbols fall into that category --
doing so from background knowledge instead of a verified source would
itself be exactly the kind of fabrication this project's discipline
forbids. Every `left_censored=False` result is reported with its own
`added_uncertainty_days`; a human applying this data should read that
caveat, not treat any date here as a clean IPO/addition date.

Usage:
    python3 scripts/compute_sp500_pit_listed_from.py \\
        --csv-path /path/to/sp_500_historical_components.csv \\
        --universe RESEARCH_UNIVERSE \\
        --out ./data/sp500_pit_listed_from.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from data_infra.providers.sp500_pit_membership import parse_snapshots, reconstruct_intervals  # noqa: E402
from data_infra.universe import PILOT_UNIVERSE_V1, RESEARCH_UNIVERSE_STAGE4  # noqa: E402
from data_infra.versioning import compute_data_version  # noqa: E402

_UNIVERSES = {"PILOT_UNIVERSE": PILOT_UNIVERSE_V1, "RESEARCH_UNIVERSE": RESEARCH_UNIVERSE_STAGE4}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv-path", required=True, type=Path, help="Local path to hanshof/sp500_constituents' sp_500_historical_components.csv (not committed to this repo)")
    parser.add_argument("--universe", choices=sorted(_UNIVERSES) + ["ALL"], default="ALL", help="Named universe from src/data_infra/universe.py, or ALL for both (default: ALL)")
    parser.add_argument("--symbols", nargs="+", default=None, help="Explicit symbol list, overriding --universe entirely (advanced/ad-hoc use)")
    parser.add_argument("--out", required=True, type=Path, help="Where to write the JSON report of findings")
    args = parser.parse_args(argv)

    if not args.csv_path.exists():
        print(f"FATAL: --csv-path {args.csv_path} does not exist", file=sys.stderr)
        return 1

    if args.symbols is not None:
        symbols = sorted(set(args.symbols))
    elif args.universe == "ALL":
        symbols = sorted({s for u in _UNIVERSES.values() for s in u.symbol_ids})
    else:
        symbols = sorted(_UNIVERSES[args.universe].symbol_ids)

    print(f"Parsing {args.csv_path} ...", flush=True)
    snapshots = parse_snapshots(args.csv_path)
    print(f"Parsed {len(snapshots)} snapshots, {snapshots[0].as_of} to {snapshots[-1].as_of}. Reconstructing intervals...", flush=True)
    intervals = reconstruct_intervals(snapshots)
    by_ticker = {iv.ticker: iv for iv in intervals}
    print(f"{len(intervals)} distinct tickers ever observed. Matching {len(symbols)} requested symbol(s)...", flush=True)

    per_symbol_results = []
    for symbol in symbols:
        iv = by_ticker.get(symbol)
        if iv is None:
            per_symbol_results.append({
                "security_id": symbol, "found": False, "confirmable_listed_from": None,
                "left_censored": None, "added_uncertainty_days": None,
                "right_censored": None, "left_the_index": None,
            })
            continue
        confirmable_listed_from = None if iv.left_censored else iv.first_seen.isoformat()
        per_symbol_results.append({
            "security_id": symbol,
            "found": True,
            "confirmable_listed_from": confirmable_listed_from,
            "left_censored": iv.left_censored,
            "added_uncertainty_days": iv.added_uncertainty_days,
            "right_censored": iv.right_censored,
            "left_the_index": not iv.right_censored,
        })

    confirmed_count = sum(1 for r in per_symbol_results if r["confirmable_listed_from"] is not None)
    left_the_index = [r["security_id"] for r in per_symbol_results if r["left_the_index"]]

    checksum = compute_data_version({
        "symbols": symbols,
        "confirmable_listed_from": {r["security_id"]: r["confirmable_listed_from"] for r in per_symbol_results},
    })

    report = {
        "note": (
            "Real hanshof/sp500_constituents-derived S&P 500 index membership findings, "
            "one entry per requested symbol. confirmable_listed_from is null when the "
            "symbol was already present in the dataset's very first snapshot "
            "(left_censored=True -- true addition date unknown/predates the dataset) or "
            "was never found. left_the_index=true means the symbol was NOT present in the "
            "dataset's last snapshot -- flagged for human review, never auto-applied as a "
            "listed_to value. See this script's own module docstring for the ticker-vs-"
            "corporate-identity caveat that applies to every non-null confirmable_listed_from."
        ),
        "source_first_snapshot": snapshots[0].as_of.isoformat(),
        "source_last_snapshot": snapshots[-1].as_of.isoformat(),
        "symbols_requested": len(symbols),
        "confirmed_listed_from_count": confirmed_count,
        "left_the_index": left_the_index,
        "per_symbol_results": per_symbol_results,
        "content_checksum": checksum,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2))

    print(f"Symbols requested: {len(symbols)}")
    print(f"Confirmed listed_from: {confirmed_count}/{len(symbols)}")
    print(f"Left the index before last snapshot (review needed): {left_the_index}")
    print(f"Content checksum: {checksum}")
    print(f"Report written to: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
