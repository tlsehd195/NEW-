#!/usr/bin/env python3
"""Print (never send) the SPY order plan implied by the latest SMA reading (ADR-0239).

Reads the last line of the observe-only log; makes no network call and
imports no broker code. The price defaults to the logged month-end close,
which is an estimate, not an order price.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from macro_filter.order_plan import build_order_plan  # noqa: E402


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--log", type=Path, default=Path("docs/research/macro_observations/sma_10m.jsonl"))
    p.add_argument("--capital-krw", type=float, required=True)
    p.add_argument("--fx", type=float, required=True, help="KRW per USD (an assumption, check the real rate)")
    p.add_argument("--held-shares", type=float, default=0.0)
    p.add_argument("--price", type=float, help="USD; default = logged month-end close")
    p.add_argument("--max-order-usd", type=float, default=1200.0)
    p.add_argument("--fractional", action="store_true")
    args = p.parse_args(argv)

    lines = [l for l in args.log.read_text().splitlines() if l.strip()] if args.log.exists() else []
    if not lines:
        print("no observation in log", file=sys.stderr)
        return 1
    entry = json.loads(lines[-1])
    price = args.price or entry["last_month_end_close"]
    plan = build_order_plan(
        target_exposure=entry["implied_exposure"],
        capital_usd=args.capital_krw / args.fx,
        price_usd=price,
        held_shares=args.held_shares,
        max_order_notional_usd=args.max_order_usd,
        fractional=args.fractional,
    )
    print(f"[DRY RUN - nothing is sent] decision_month={entry['decision_month']} exposure={entry['implied_exposure']}")
    print(json.dumps({**plan.__dict__, "chunks": list(plan.chunks), "fx_krw_per_usd": args.fx}, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
