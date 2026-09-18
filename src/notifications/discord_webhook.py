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

# Discord's real 2000-UTF16-code-unit content limit (truncate_for_
# discord's own hard backstop) comfortably fits far more than 15
# "TICKER: qty" entries -- raised after a real production message
# summarized away a real 37-position portfolio the account owner
# actually wanted to see (external review). Still a real cap, not
# removed outright: a genuinely huge position count (hundreds) would
# still need summarizing rather than silently relying on
# truncate_for_discord to cut it off mid-list.
_MAX_POSITIONS_TO_LIST = 60
_POSITIONS_PER_LINE = 4


def _format_quantity(qty: float) -> str:
    """Rounds a real position quantity for DISPLAY only (the persisted/
    computed value itself is never touched) -- a whole share count
    (the common case) shows with no decimals at all; a real fractional
    share (--lot-size, ADR-0140) shows up to 4 decimal places with
    trailing zeros trimmed, never the full float repr (e.g.
    3.162355322244007 -> 3.1624, 10.0 -> 10)."""
    if qty == int(qty):
        return str(int(qty))
    return f"{qty:.4f}".rstrip("0").rstrip(".")


# `note` is a small, fixed set of static boilerplate strings this
# project's own scripts generate (never free-form/user text) -- a
# direct lookup to a Korean equivalent is honest (not a guess at
# meaning) precisely because the source set is fixed and known. Any
# future/unrecognized note string falls back to being shown as-is
# (see below) rather than silently dropped or mistranslated.
_KNOWN_NOTES_KO = {
    "Nothing new to process -- every requested checkpoint was already recorded.": (
        "새로 처리할 체크포인트 없음 -- 요청한 기간이 이미 전부 처리되어 있습니다."
    ),
    (
        "Real Paper Trading cycle run against a real market-data catalog -- "
        "every checkpoint's Prediction/Regime/Decision/Sizing/Risk output and "
        "every real order/fill is persisted in --paper-store, queryable by the "
        "same repository classes this run used. Not an always-on process -- "
        "this run covers exactly [--start, --end] and then exits."
    ): "실제 시장 데이터로 진행된 페이퍼 트레이딩 사이클입니다.",
}


# A simple, disclosed rule-of-thumb bucket for the Sharpe ratio -- not
# a claim of statistical rigor, just a quick label next to the real
# number so the raw value isn't the only thing shown. Thresholds are a
# common informal convention (>=1 good, 0-1 middling, <0 poor), not
# this project's own invention or a backtested claim.
def _sharpe_label(sharpe: float) -> str:
    if sharpe >= 1.0:
        return "양호"
    if sharpe >= 0.0:
        return "보통"
    return "부진"


def format_paper_trading_cycle_report(report: dict) -> str:
    """`report` -- exactly the dict `scripts/run_paper_trading_cycle.py`
    itself writes to `--out`: either the full-run shape, or its
    "nothing new to process" early-exit shape (fewer keys -- see that
    script's own `--resume` early-return branch; `start`/`end`/
    `last_processed` were added to that shape after an external review
    found a real Discord message from it had no date at all). Every
    field is read with `.get()` and its line skipped entirely when
    absent -- never defaulted to `0`/`"모름"`, matching this project's
    own "never fabricate a value that wasn't really computed" rule."""
    lines = ["**\U0001f4c8 페이퍼 트레이딩 데일리 사이클**"]

    universe = report.get("universe")
    if universe is not None:
        lines.append(f"유니버스: {universe}")

    start, end = report.get("start"), report.get("end")
    if start and end:
        period_line = f"기간: {start[:10]} ~ {end[:10]}"
        last_processed = report.get("last_processed")
        if report.get("checkpoints_run") == 0 and last_processed:
            period_line += f" (마지막 처리일: {last_processed[:10]})"
        lines.append(period_line)

    checkpoints_run = report.get("checkpoints_run")
    if checkpoints_run is not None:
        lines.append(f"처리된 체크포인트: {checkpoints_run}개")

    submitted = report.get("total_orders_submitted")
    if submitted is not None:
        filled = report.get("total_orders_with_a_fill")
        fill_note = f" (체결: {filled}건)" if filled is not None else ""
        lines.append(f"주문 제출: {submitted}건{fill_note}")

    # External review (account owner, 2026-09-18): --initial-capital was
    # already read by the script but never surfaced in the report at
    # all -- shown next to final_cash so the two numbers are directly
    # comparable at a glance.
    initial_capital = report.get("initial_capital")
    if initial_capital is not None:
        lines.append(f"초기 자본: {initial_capital:,.2f}")

    final_cash = report.get("final_cash")
    if final_cash is not None:
        lines.append(f"최종 현금: {final_cash:,.2f}")

    positions = report.get("final_positions")
    if positions is not None:
        if not positions:
            lines.append("보유 포지션: 없음")
        elif len(positions) <= _MAX_POSITIONS_TO_LIST:
            # External review: a real 37-position message came back as
            # one giant comma-separated line of unrounded floats (e.g.
            # "AAPL: 3.162355322244007") -- unreadable. Quantities are
            # rounded for display only (never re-derived/re-computed --
            # the same real value, just fewer digits shown), and grouped
            # a few per line instead of one long line.
            entries = [f"{sid}: {_format_quantity(qty)}" for sid, qty in sorted(positions.items())]
            grouped_lines = [", ".join(entries[i:i + _POSITIONS_PER_LINE]) for i in range(0, len(entries), _POSITIONS_PER_LINE)]
            lines.append(f"보유 포지션 ({len(positions)}개):")
            lines.extend(grouped_lines)
        else:
            lines.append(f"보유 포지션: {len(positions)}개 (너무 많아 표시 생략)")

    # Session 38 continued: `performance` is `storage.serialization.
    # paper_performance_report_to_payload`'s own JSON-safe dict, present
    # once `scripts/run_paper_trading_cycle.py` started computing it
    # (ADR-0136) -- absent entirely on an older report file, and every
    # individual metric inside it may honestly be `None` (see that
    # module's own `reasons` dict) rather than a real number. Both cases
    # are skipped, never rendered as a fabricated 0/N/A.
    performance = report.get("performance")
    if performance is not None:
        sharpe = performance.get("sharpe_ratio")
        if sharpe is not None:
            lines.append(f"샤프 비율: {sharpe:.3f} ({_sharpe_label(sharpe)})")
        sortino = performance.get("sortino_ratio")
        if sortino is not None:
            lines.append(f"소르티노 비율: {sortino:.3f}")
        max_dd = performance.get("max_drawdown")
        if max_dd is not None:
            lines.append(f"최대 낙폭: {max_dd:.2%}")
        total_return = performance.get("total_return")
        if total_return is not None:
            arrow = "▲" if total_return >= 0 else "▼"
            lines.append(f"총 수익률: {arrow} {total_return:.2%}")

    note = report.get("note")
    if note:
        lines.append(f"_{_KNOWN_NOTES_KO.get(note, note)}_")

    return "\n".join(lines)


def _utf16_length(s: str) -> int:
    """Discord (like most JS-originated web APIs) measures a string's
    length the same way JavaScript's own `.length` does: UTF-16 CODE
    UNITS, not Unicode codepoints -- confirmed via independent search,
    not assumed (multiple sources agree Discord/Telegram-style chunking
    tools have to special-case this exact gap). Python's `len()` counts
    codepoints, so a character outside the Basic Multilingual Plane
    (e.g. most emoji, U+10000 and above) counts as ONE codepoint in
    Python but TWO UTF-16 code units in Discord's own accounting --
    `len()` alone under-counts exactly those characters."""
    return len(s.encode("utf-16-le")) // 2


def truncate_for_discord(content: str, *, limit: int = _DISCORD_CONTENT_LIMIT) -> str:
    """Pure. Discord's webhook API rejects (HTTP 400) any `content` over
    `limit` UTF-16 code units (see `_utf16_length`) -- truncate rather
    than let a long report crash the send outright.

    External review, LOW-2 (Session 38 continued): previously compared
    `len(content)` (Python codepoints) against `limit` directly. Every
    report this module formats today has at most one astral character
    (a single leading emoji), so the previous version never actually
    mis-truncated in practice -- but a future formatter combining
    several emoji/rare CJK characters near the boundary could have
    silently sent oversized content and gotten a real HTTP 400. Never
    splits a surrogate pair mid-character -- iterates by Python
    codepoint (each one already a complete, valid character) and stops
    BEFORE a codepoint that would push the running UTF-16 count over
    budget, so truncation always lands on a whole-character boundary."""
    if _utf16_length(content) <= limit:
        return content
    budget = limit - _utf16_length(_TRUNCATION_SUFFIX)
    kept: list[str] = []
    used = 0
    for ch in content:
        ch_length = 2 if ord(ch) > 0xFFFF else 1
        if used + ch_length > budget:
            break
        kept.append(ch)
        used += ch_length
    return "".join(kept) + _TRUNCATION_SUFFIX


# ADR-0166 (external review, real production failure): the first real
# scheduled/workflow_dispatch run to actually exercise this call (the
# account owner's webhook secret was only registered 2026-09-18) got a
# real HTTP 403 straight back from Discord's own infrastructure --
# connection succeeded, Discord itself rejected the request. No
# `User-Agent` header was ever sent, leaving Python's default
# `Python-urllib/x.y` string, a well-known bot signature -- the same
# root cause this project already found and fixed for Stooq (ADR-0157)
# and already worked around for SEC EDGAR (a required descriptive UA by
# policy). A real, current desktop-browser User-Agent is the same
# category of fix, applied here for the same reason. This is a
# best-effort fix against a plausible but not independently confirmed
# cause (this session's own egress blocks discord.com entirely, so it
# cannot be verified here) -- needs re-verification against a real
# scheduled/workflow_dispatch run, not assumed fixed from this reasoning
# alone.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


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
        webhook_url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": _USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        if response.status not in (200, 204):
            raise RuntimeError(f"Discord webhook returned unexpected HTTP {response.status}")
