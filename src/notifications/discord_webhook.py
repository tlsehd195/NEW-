"""Discord webhook delivery for this project's scheduled reports
(Session 38, account owner's own request: "페이퍼 트레이딩 데일리 사이클
이거 클로드앱으로 보내는게 아니라 디스코드로도 보낼 수 있으면 좋겠어 ...
다른 보고 같은거 전부 디스코드로 받을 수 있게 만들고 싶어" -- the daily
cycle report currently only reaches the account owner through this
conversation, and every other report should eventually reach Discord the
same way).

Formatting (`format_*`, pure, one function per report shape) is kept
separate from the one real network call (`send_discord_message`) so a
future report type only needs a new formatter here plus a `--report-type`
case in `scripts/send_discord_notification.py` -- never a new network
path. Only `format_paper_trading_cycle_report` exists today because
`scripts/run_paper_trading_cycle.py` is the only report this repository
currently produces on an unattended schedule
(`.github/workflows/paper_trading_cycle.yml`); every other report this
session's brainstorm mentioned (paper performance, weekly evaluation,
learning cycle) still runs interactively today, not on its own schedule,
so there is no report file yet for a formatter to read.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

# Discord's own documented hard limit for a webhook message's `content`
# field -- exceeding it is a real HTTP 400 from Discord's API, not a
# style preference this module invented.
_DISCORD_CONTENT_LIMIT = 2000
_TRUNCATION_SUFFIX = "\n... (truncated)"

_MAX_POSITIONS_TO_LIST = 15


def format_paper_trading_cycle_report(report: dict) -> str:
    """`report` -- exactly the dict `scripts/run_paper_trading_cycle.py`
    itself writes to `--out`: either the full-run shape, or its
    "nothing new to process" early-exit shape (fewer keys -- see that
    script's own `--resume` early-return branch). Every field is read
    with `.get()` and its line skipped entirely when absent -- never
    defaulted to `0`/`"unknown"`, matching this project's own "never
    fabricate a value that wasn't really computed" rule."""
    lines = ["**\U0001f4c8 Paper Trading Daily Cycle**"]

    universe = report.get("universe")
    if universe is not None:
        lines.append(f"Universe: {universe}")

    start, end = report.get("start"), report.get("end")
    if start and end:
        lines.append(f"Period: {start} -> {end}")

    checkpoints_run = report.get("checkpoints_run")
    if checkpoints_run is not None:
        lines.append(f"Checkpoints run: {checkpoints_run}")

    submitted = report.get("total_orders_submitted")
    if submitted is not None:
        filled = report.get("total_orders_with_a_fill")
        fill_note = f" (filled: {filled})" if filled is not None else ""
        lines.append(f"Orders submitted: {submitted}{fill_note}")

    final_cash = report.get("final_cash")
    if final_cash is not None:
        lines.append(f"Final cash: {final_cash:,.2f}")

    positions = report.get("final_positions")
    if positions is not None:
        if not positions:
            lines.append("Open positions: none")
        elif len(positions) <= _MAX_POSITIONS_TO_LIST:
            position_list = ", ".join(f"{sid}: {qty}" for sid, qty in sorted(positions.items()))
            lines.append(f"Open positions ({len(positions)}): {position_list}")
        else:
            lines.append(f"Open positions: {len(positions)} (too many to list)")

    note = report.get("note")
    if note:
        lines.append(f"_{note}_")

    return "\n".join(lines)


def truncate_for_discord(content: str, *, limit: int = _DISCORD_CONTENT_LIMIT) -> str:
    """Pure. Discord's webhook API rejects (HTTP 400) any `content` over
    `limit` characters -- truncate rather than let a long report crash
    the send outright."""
    if len(content) <= limit:
        return content
    return content[: limit - len(_TRUNCATION_SUFFIX)] + _TRUNCATION_SUFFIX


def send_discord_message(webhook_url: str, content: str, *, timeout: float = 10.0) -> None:
    """The one real network call this module makes: a POST to a real
    Discord webhook URL (the account owner's own, created via Discord's
    "Integrations -> Webhooks" UI -- never guessed or hardcoded here).
    Raises `urllib.error.URLError`/`RuntimeError` on any transport error
    or unexpected response rather than swallowing it -- a failed
    notification is a real, visible failure for the caller to report,
    never silently dropped."""
    body = json.dumps({"content": truncate_for_discord(content)}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url, data=body, method="POST", headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        if response.status not in (200, 204):
            raise RuntimeError(f"Discord webhook returned unexpected HTTP {response.status}")
