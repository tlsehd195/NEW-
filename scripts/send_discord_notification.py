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
        # ADR-0165: an earlier upstream step (e.g. "Ingest latest market
        # data") can fail and cause the report-producing step to be
        # skipped, so `--report` never gets written -- this is not a
        # rare edge case, it already happened in production (run #33,
        # 2026-09-18). Previously this branch only printed to stderr and
        # exited, so the one channel this whole feature exists for
        # (Discord -- see this module's own docstring) stayed completely
        # silent on exactly the days something went wrong. Best-effort
        # notify Discord of the failure itself before still returning 1
        # -- the workflow step's own red X (already caused by the
        # earlier failed step) is not duplicated or hidden by this,
        # just no longer the ONLY place the account owner would see it.
        failure_note = (
            f"**⚠️ {args.report_type} 리포트가 생성되지 않았습니다** "
            "-- 워크플로의 이전 단계가 실패했거나 건너뛰어졌습니다. "
            "GitHub Actions 실행 로그를 확인해주세요."
        )
        try:
            send_discord_message(webhook_url, failure_note)
        except (urllib.error.URLError, RuntimeError) as exc:
            print(f"FATAL: {args.report} does not exist, and the Discord failure notification also failed to send: {exc}", file=sys.stderr)
            return 1
        print(f"FATAL: {args.report} does not exist -- sent a failure notification to Discord instead", file=sys.stderr)
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
