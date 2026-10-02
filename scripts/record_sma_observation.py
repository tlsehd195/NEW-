#!/usr/bin/env python3
"""Observe-only log of the 10-month SMA rule on SPY (ADR-0235).

Records, once per calendar month, what `sma_10m` says: hold SPY while the
previous month-end close is above the average of the last 10 month-end
closes, otherwise sit in cash. The decision uses only closes known at run
time, so the log is point-in-time by construction. Nothing trades on it;
paper trading is untouched. The backtest used dividend-adjusted closes and
this uses Twelve Data's split-adjusted closes, so a borderline month can
differ.

Appends one JSON line to `--log` the first time it runs in a new month and
prints whether the state flipped. With `--discord-on-flip` and
DISCORD_WEBHOOK_URL set, a flip is also sent to Discord.

Makes a real call to api.twelvedata.com; TWELVEDATA_API_KEY from the
environment only.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from macro_filter.overlays import SMA_MONTHS, month_end_closes, sma_exposure  # noqa: E402

SYMBOL = "SPY"


def build_entry(bars: Sequence, now: datetime) -> Optional[dict]:
    exposure = sma_exposure(bars, now)
    if exposure is None:
        return None
    window = month_end_closes(bars, now)[-SMA_MONTHS:]
    return {
        "recorded_at": now.isoformat(),
        "decision_month": f"{now.year:04d}-{now.month:02d}",
        "symbol": SYMBOL,
        "last_month_end_close": round(window[-1], 4),
        "sma_10_month_ends": round(statistics.fmean(window), 4),
        "implied_exposure": exposure,
        "risk_off": exposure == 0.0,
    }


def last_entry(log: Path) -> Optional[dict]:
    if not log.exists():
        return None
    lines = [line for line in log.read_text().splitlines() if line.strip()]
    return json.loads(lines[-1]) if lines else None


def rows_to_bars(rows: Sequence[dict]) -> list:
    bars = []
    for row in rows:
        ts = datetime.fromisoformat(row["datetime"][:10]).replace(tzinfo=timezone.utc)
        bars.append(SimpleNamespace(timestamp=ts, close=float(row["close"]), adjusted_close=None))
    return sorted(bars, key=lambda b: b.timestamp)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--discord-on-flip", action="store_true")
    args = parser.parse_args(argv)

    from data_infra.providers.twelvedata import TwelveDataDataProvider
    from data_infra.providers.twelvedata_config import DEFAULT_TWELVEDATA_CONFIG
    from data_infra.providers.twelvedata_transport import TwelveDataHttpTransport

    now = datetime.now(timezone.utc)
    provider = TwelveDataDataProvider(
        DEFAULT_TWELVEDATA_CONFIG, TwelveDataHttpTransport(DEFAULT_TWELVEDATA_CONFIG.base_url)
    )
    bars = rows_to_bars(provider.fetch(SYMBOL, now - timedelta(days=400), now))
    entry = build_entry(bars, now)
    if entry is None:
        print(f"{SYMBOL}: fewer than {SMA_MONTHS} month-end closes available", file=sys.stderr)
        return 1

    previous = last_entry(args.log)
    print(json.dumps(entry, sort_keys=True))
    if previous is not None and previous.get("decision_month") == entry["decision_month"]:
        print("already recorded this month; log unchanged")
        return 0
    args.log.parent.mkdir(parents=True, exist_ok=True)
    with args.log.open("a") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")

    flipped = previous is not None and previous.get("risk_off") != entry["risk_off"]
    print(f"appended; state {'FLIPPED' if flipped else 'unchanged'} (risk_off={entry['risk_off']})")
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if flipped and args.discord_on_flip and webhook:
        from notifications.discord_webhook import send_discord_message

        state = "위험 회피 (현금 100% 신호)" if entry["risk_off"] else "정상 (주식 100% 신호)"
        send_discord_message(
            webhook,
            f"[관찰 전용] SPY 10개월 이동평균 규칙이 {state}로 바뀌었습니다. "
            f"전월 말 종가 {entry['last_month_end_close']}, 10개월 평균 {entry['sma_10_month_ends']}. "
            "실제 매매는 바뀌지 않습니다.",
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
