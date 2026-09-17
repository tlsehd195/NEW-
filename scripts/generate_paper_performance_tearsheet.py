#!/usr/bin/env python3
"""Generates a real HTML performance tearsheet (via `quantstats`) from
a real Paper Trading run's own equity curve (Session 38, one of the
account owner's own uploaded evaluation reports' recommendations --
see docs/decisions/ADR-0138-quantstats-tearsheet-for-paper-trading.md).

**Optional dependency, never imported by src/.** Install with
`pip install -e '.[reporting]'`. Deliberately `quantstats`, NOT the
"actively maintained" `quantstats-reloaded` fork an external evaluation
report recommended -- direct testing (ADR-0138) found quantstats-
reloaded==0.1.0's own `reports.html()` crashes with a real, reproducible
`ValueError` on the single-strategy/no-benchmark case, which is exactly
this project's own case (no real S&P 500 data has been ingested,
ADR-0005) -- while the original quantstats==0.0.81 does not.

The real, durable equity curve this reads comes from the SAME source
`scripts/run_paper_trading_cycle.py`'s own `_equity_history()` already
established (ADR-0136): `RiskCheckedPosition.as_of_time`/`.risk_state.
portfolio_value`, one real snapshot per checkpoint, across every past
`--resume` invocation this `--paper-store` has ever recorded -- never
`PortfolioAccounting.value_series` (real only within one process, see
that ADR's own Decision 2).

Usage (against a real --paper-store scripts/run_paper_trading_cycle.py
already wrote to):
    pip install -e '.[reporting]'
    python3 scripts/generate_paper_performance_tearsheet.py \\
        --paper-store ./data/paper_trading_store \\
        --security-id AAPL \\
        --out paper_performance_tearsheet.html
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from storage.config import StorageConfig  # noqa: E402
from storage.engine import StorageEngine  # noqa: E402
from storage.risk_repository import DuckDBRiskRepository  # noqa: E402


def _equity_history(risk_repository, representative_security_id: str) -> list[tuple[datetime, float]]:
    """Same real, durable source `scripts/run_paper_trading_cycle.py`'s
    own `_equity_history()` uses (ADR-0136) -- one real snapshot per
    checkpoint, in chronological order, never fabricated for a
    checkpoint whose `risk_state` is unexpectedly absent."""
    records = risk_repository.list_all(security_id=representative_security_id)
    return sorted(
        ((r.as_of_time, r.risk_state.portfolio_value) for r in records if r.risk_state is not None),
        key=lambda pair: pair[0],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--paper-store", required=True, type=Path, help="A real --paper-store directory scripts/run_paper_trading_cycle.py already wrote to")
    parser.add_argument("--security-id", required=True, type=str, help="Any security this --paper-store's own universe includes -- used the same way scripts/run_paper_trading_cycle.py's own _equity_history() is, as a representative proxy for this run's shared per-checkpoint portfolio value (see that script's own docstring)")
    parser.add_argument("--out", required=True, type=Path, help="Where to write the HTML tearsheet")
    parser.add_argument("--title", type=str, default=None, help="Tearsheet title (default: derived from --security-id)")
    args = parser.parse_args(argv)

    try:
        import pandas as pd
    except ImportError:
        print("FATAL: pandas is required -- install with: pip install -e '.[reporting]'", file=sys.stderr)
        return 1

    try:
        import quantstats as qs
    except ImportError:
        print("FATAL: quantstats is required -- install with: pip install -e '.[reporting]'", file=sys.stderr)
        return 1

    if not args.paper_store.is_dir():
        print(f"FATAL: {args.paper_store} does not exist or is not a directory", file=sys.stderr)
        return 1

    engine = StorageEngine(StorageConfig(root_dir=args.paper_store))
    risk_repository = DuckDBRiskRepository(engine)
    equity_history = _equity_history(risk_repository, args.security_id)
    engine.close()

    if len(equity_history) < 2:
        print(
            f"FATAL: only {len(equity_history)} real portfolio-value checkpoint(s) found for "
            f"--security-id {args.security_id!r} in {args.paper_store} -- need at least 2 to "
            "compute even one real return. Never fabricated a synthetic point instead.",
            file=sys.stderr,
        )
        return 1

    timestamps, values = zip(*equity_history)
    prices = pd.Series(values, index=pd.DatetimeIndex(timestamps)).sort_index()
    returns = prices.pct_change().dropna()

    if returns.empty:
        print("FATAL: no real return could be computed from this --paper-store's own equity history", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    title = args.title or f"Paper Trading Performance Tearsheet -- {args.security_id}"
    qs.reports.html(returns, output=str(args.out), title=title)

    print(f"Real checkpoints used: {len(equity_history)} ({len(returns)} real return(s))")
    print(f"Tearsheet written to: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
