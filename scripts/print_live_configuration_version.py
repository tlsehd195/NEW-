#!/usr/bin/env python3
"""Prints a `LiveTradingConfig`'s real `configuration_version()` hash,
so an operator can record it as the pinned reference `orchestration.
live_runner.run_cycle`'s `pinned_configuration_version` parameter
compares against (`configuration_integrity_valid`, ADR-0072/ADR-0074).

This closes the operational half of item #7 from ADR-0074's own
docstring ("Where/when does an operator set `configuration_integrity_
valid`'s pinned hash?"): the answer is -- after constructing (or
changing) a real `LiveTradingConfig`, an operator runs this script with
the exact same field values, and records BOTH the printed hash and the
full field dump it prints alongside it (so a future reader can verify
what was actually pinned, not just trust a bare hex string) in
`docs/operations/LIVE-TRADING-RUNBOOK.md`'s own "Configuration
Integrity" log. Rotating the pin means deliberately re-running this
script after a reviewed config change and recording a new entry --
never silently.

This script performs no I/O of its own beyond argument parsing and
stdout -- it does not read or write any real Live config file, does
not touch a real account, and makes no network call. It exists purely
so the hash an operator records is computed by the exact same code
(`LiveTradingConfig.configuration_version()`) that `run_cycle` itself
will later compare against, rather than a hash computed by hand or by
a different tool that could silently drift from the real one.

Usage:
    python3 scripts/print_live_configuration_version.py \\
        --live-trading-enabled --max-daily-loss 100.0 \\
        --max-order-frequency-per-hour 6 --max-consecutive-failures 5
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from broker.live.config import LiveTradingConfig  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--broker-id", default="toss")
    parser.add_argument("--live-trading-enabled", action="store_true")
    parser.add_argument("--reconciliation-tolerance", type=float, default=0.01)
    parser.add_argument("--max-daily-loss", type=float, default=None)
    parser.add_argument("--max-order-frequency-per-hour", type=int, default=None)
    parser.add_argument("--max-consecutive-failures", type=int, default=None)
    parser.add_argument("--no-auto-cancel-on-kill-switch", action="store_true", help="Disable the default True")
    args = parser.parse_args(argv)

    config = LiveTradingConfig(
        broker_id=args.broker_id,
        live_trading_enabled=args.live_trading_enabled,
        reconciliation_tolerance=args.reconciliation_tolerance,
        max_daily_loss=args.max_daily_loss,
        max_order_frequency_per_hour=args.max_order_frequency_per_hour,
        max_consecutive_failures=args.max_consecutive_failures,
        auto_cancel_on_kill_switch=not args.no_auto_cancel_on_kill_switch,
    )

    print(json.dumps(asdict(config), indent=2))
    print(f"configuration_version: {config.configuration_version()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
