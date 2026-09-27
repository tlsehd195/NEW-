#!/usr/bin/env python3
"""Observe-only log of the real-time Sahm rule (ADR-0220 follow-up).

The research-window validation left the Sahm rule as the one lead worth
watching but could not confirm it. This records, going forward, what the
rule says each time FRED's unemployment rate changes: the values fetched
today are exactly what was known today, so the log is point-in-time by
construction. Nothing trades on it. Paper trading is untouched.

Appends one JSON line to `--log` only when the latest observation or its
value changed since the last line (a new release or a revision), and
prints whether the rule's state flipped. With `--discord-on-flip` and
DISCORD_WEBHOOK_URL set, a flip is also sent to Discord.

Makes a real call to api.stlouisfed.org; FRED_API_KEY from the
environment only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from data_infra.providers.fred import FredMacroProvider  # noqa: E402
from data_infra.providers.fred_config import DEFAULT_FRED_CONFIG  # noqa: E402
from data_infra.providers.fred_transport import FredHttpTransport  # noqa: E402
from macro_filter.config import DEFAULT_MACRO_FILTER_CONFIG  # noqa: E402
from macro_filter.signals import sahm_rule_reading  # noqa: E402

SERIES_ID = "UNRATE"


def build_entry(values: list[tuple[date, float]], now: datetime) -> Optional[dict]:
    config = DEFAULT_MACRO_FILTER_CONFIG
    reading = sahm_rule_reading(values, now, config)
    if reading is None:
        return None
    return {
        "recorded_at": now.isoformat(),
        "series_id": SERIES_ID,
        "latest_observation_date": reading.latest_observation_date.isoformat(),
        "latest_rate": reading.latest_rate,
        "three_month_average": round(reading.three_month_average, 4),
        "prior_twelve_month_low": round(reading.prior_twelve_month_low, 4),
        "gap": round(reading.gap, 4),
        "active": reading.active,
        "implied_exposure": config.single_signal_exposure if reading.active else 1.0,
        "config_version": config.configuration_version(),
    }


def last_entry(log: Path) -> Optional[dict]:
    if not log.exists():
        return None
    lines = [line for line in log.read_text().splitlines() if line.strip()]
    return json.loads(lines[-1]) if lines else None


def changed(previous: Optional[dict], entry: dict) -> bool:
    if previous is None:
        return True
    keys = ("latest_observation_date", "latest_rate", "three_month_average", "prior_twelve_month_low")
    return any(previous.get(k) != entry[k] for k in keys)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--discord-on-flip", action="store_true")
    args = parser.parse_args(argv)

    now = datetime.now(timezone.utc)
    provider = FredMacroProvider(DEFAULT_FRED_CONFIG, FredHttpTransport(DEFAULT_FRED_CONFIG.base_url))
    observations = provider.fetch_series(SERIES_ID, now.date() - timedelta(days=30 * 24), now.date())
    values = [(o.observation_date, o.value) for o in observations if o.value is not None]
    entry = build_entry(values, now)
    if entry is None:
        print(f"{SERIES_ID}: not enough fresh monthly data for the Sahm rule", file=sys.stderr)
        return 1

    previous = last_entry(args.log)
    print(json.dumps(entry, sort_keys=True))
    if not changed(previous, entry):
        print("no new release or revision since the last entry; log unchanged")
        return 0
    args.log.parent.mkdir(parents=True, exist_ok=True)
    with args.log.open("a") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")

    flipped = previous is not None and previous.get("active") != entry["active"]
    print(f"appended; state {'FLIPPED' if flipped else 'unchanged'} (active={entry['active']})")
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if flipped and args.discord_on_flip and webhook:
        from notifications.discord_webhook import send_discord_message

        state = "켜짐 (위험 회피: 주식 비중 50% 신호)" if entry["active"] else "꺼짐 (정상: 주식 비중 100% 신호)"
        send_discord_message(
            webhook,
            f"[관찰 전용] 실업률(Sahm) 규칙이 {state}. "
            f"실업률 {entry['latest_rate']}% ({entry['latest_observation_date']}), "
            f"3개월 평균이 12개월 최저보다 {entry['gap']:.2f}%p 높음. 실제 매매는 바뀌지 않습니다.",
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
