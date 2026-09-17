#!/usr/bin/env python3
"""Sends a real Discord webhook notification for one of this project's
scheduled report files (Session 38, account owner's own request -- see
`notifications.discord_webhook`'s own module docstring for the full
"why"). Makes ONE real network call: a POST to a real Discord webhook
URL. That URL must already exist (created by the account owner via
Discord's own channel "Integrations -> Webhooks" UI) and is supplied
here only via --webhook-url or the DISCORD_WEBHOOK_URL environment
variable -- never hardcoded or logged by this script.

Usage (report file already written by scripts/run_paper_trading_cycle.py):
    DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/... \\
        python3 scripts/send_discord_notification.py \\
        --report paper_trading_cycle_report.json \\
        --report-type paper_trading_cycle
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from notifications.discord_webhook import (  # noqa: E402
    format_paper_trading_cycle_report,
    send_discord_message,
)

# One formatter per known report shape -- add a new entry here (plus a
# new `format_*` function in notifications.discord_webhook) when another
# of this project's reports gets its own unattended schedule.
_FORMATTERS = {
    "paper_trading_cycle": format_paper_trading_cycle_report,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--report", required=True, type=Path, help="Path to the report JSON file already written by the report-producing script")
    parser.add_argument("--report-type", required=True, choices=sorted(_FORMATTERS), help="Which formatter to use for --report's contents")
    parser.add_argument("--webhook-url", default=None, help="Discord webhook URL (default: read from the DISCORD_WEBHOOK_URL environment variable)")
    args = parser.parse_args(argv)

    webhook_url = args.webhook_url or os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("FATAL: no webhook URL -- pass --webhook-url or set DISCORD_WEBHOOK_URL", file=sys.stderr)
        return 1

    if not args.report.is_file():
        print(f"FATAL: {args.report} does not exist", file=sys.stderr)
        return 1

    report = json.loads(args.report.read_text())
    content = _FORMATTERS[args.report_type](report)

    try:
        send_discord_message(webhook_url, content)
    except (urllib.error.URLError, RuntimeError) as exc:
        print(f"FATAL: Discord webhook send failed: {exc}", file=sys.stderr)
        return 1

    print("Discord notification sent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
