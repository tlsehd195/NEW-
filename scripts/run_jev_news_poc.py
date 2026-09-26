#!/usr/bin/env python3
"""Research-only PoC: does TypeSafe AI's Jev (a "System One" classifier --
state + typed questions in, calibrated probabilities out; it does not
generate text or forecast prices, docs.typesafe.ai/introduction) read
financial news headlines in a way that carries information about the
stock's subsequent return? ADR-0218.

docs/PROJECT_STATUS.md kept Jev on hold with "never wire it in before a
PoC measures its accuracy". This script is that PoC and nothing more:

**Explicitly separate from the real trading pipeline**, same boundary as
`scripts/run_ai_prediction_experiment.py`: it never imports `predict`/
`decision`/`risk`/`broker`/`ai_gateway`, never produces a decision, and
nothing it writes feeds back into any pipeline. It talks to Jev over
plain HTTPS with the standard library, so no provider adapter is added
to `src/ai_gateway` (CLAUDE.md "Grounding Gate 배선 보류 결정").

Subcommands:

    smoke     -- one real call, confirms JEV_API_KEY works and prints
                 the served model name + token usage.
    extract   -- streams the FNSPID news CSV (stdin or --input),
                 keeps headlines for the chosen universe inside the
                 allowed date window, dedupes to one headline per
                 (symbol, event day), and writes a seeded, year-
                 stratified sample as JSONL. The sample stays on the
                 runner (headlines are third-party text); only
                 aggregate numbers are ever committed.
    evaluate  -- joins the sample to real adjusted closes from a price
                 catalog, asks Jev three separately-framed questions per
                 headline, and writes an aggregate-only JSON report.

The three Jev framings (each a separate request, so none sees another's
state):

    masked    -- headline with company names/tickers replaced by
                 "the company", no date. The honest signal.
    unmasked  -- original headline + ticker, no date.
    probe     -- ticker + exact date + headline, asking directly
                 whether the stock beat the market over the following
                 five trading days. Jev is a 2026 model evaluated on
                 2010-2020 news, so any real skill here is memorised
                 outcome knowledge (look-ahead leakage), not reading.

Pre-registered pass rule (ADR-0218), all three must hold:
    1. masked forward-return IC bootstrap 95% CI lower bound > 0
    2. probe forward-return IC 95% CI contains 0 (no memorised outcomes)
    3. unmasked-minus-masked forward IC gap CI contains 0 or is negative

Point-in-time handling: a headline stamped at/after 20:00 UTC (the NYSE
close during daylight time; conservative in winter) rolls to the next
calendar day. The tradable "forward" window starts at the close of the
first trading day AFTER the event day, so a date-only or after-hours
timestamp can never be inside it. Event days end at least
`--horizon-buffer-days` before the first locked TEST window so no return
window touches it (RULE 0.8).

Usage (the workflow runs these; the key only ever comes from env):
    export JEV_API_KEY=...
    python3 scripts/run_jev_news_poc.py smoke
    curl -sL <FNSPID All_external.csv> | python3 scripts/run_jev_news_poc.py extract --out sample.jsonl
    python3 scripts/run_jev_news_poc.py evaluate --sample sample.jsonl \\
        --db-path ./data/price_catalog --report-out report.json
"""

from __future__ import annotations

import argparse
import bisect
import csv
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional, TextIO

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

JEV_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = "jev-latest"
FNSPID_ALL_EXTERNAL_URL = (
    "https://huggingface.co/datasets/Zihan1004/FNSPID/resolve/main/Stock_news/All_external.csv"
)
CLOSE_HOUR_UTC = 20
FORWARD_DAYS = 5
MAX_ABS_WINDOW_RETURN = 0.5  # larger 2-6 day moves are treated as bad data, dropped and counted

# Company names as they commonly appear in headlines, for the masked framing.
# Over-masking only removes information, so it can never inflate the masked IC.
COMPANY_ALIASES: dict[str, tuple[str, ...]] = {
    "AAPL": ("Apple",), "MSFT": ("Microsoft",), "NVDA": ("Nvidia", "NVIDIA"),
    "AMZN": ("Amazon",), "GOOGL": ("Alphabet", "Google"), "META": ("Meta Platforms", "Meta", "Facebook"),
    "AVGO": ("Broadcom", "Avago"), "TSLA": ("Tesla",), "JPM": ("JPMorgan Chase", "JPMorgan", "JP Morgan", "J.P. Morgan"),
    "V": ("Visa",), "MA": ("Mastercard", "MasterCard"), "COST": ("Costco",),
    "WMT": ("Walmart", "Wal-Mart"), "JNJ": ("Johnson & Johnson", "J&J"), "XOM": ("Exxon Mobil", "ExxonMobil", "Exxon"),
    "CAT": ("Caterpillar",), "HON": ("Honeywell",), "UPS": ("United Parcel Service", "UPS"),
    "BA": ("Boeing",), "UNH": ("UnitedHealth",), "PFE": ("Pfizer",),
    "ABBV": ("AbbVie",), "MRK": ("Merck",), "BAC": ("Bank of America", "BofA"),
    "GS": ("Goldman Sachs", "Goldman"), "PG": ("Procter & Gamble", "P&G"), "KO": ("Coca-Cola", "Coke"),
    "PEP": ("PepsiCo", "Pepsi"), "HD": ("Home Depot",), "MCD": ("McDonald's", "McDonald’s", "McDonalds"),
    "NKE": ("Nike",), "CVX": ("Chevron",), "VZ": ("Verizon",),
    "T": ("AT&T",), "DIS": ("Walt Disney", "Disney"), "ORCL": ("Oracle",),
    "IBM": ("IBM",), "CSCO": ("Cisco",), "NEE": ("NextEra Energy", "NextEra"),
    "PLD": ("Prologis", "ProLogis"), "AMT": ("American Tower",), "EQIX": ("Equinix",),
    "SPG": ("Simon Property",), "LIN": ("Linde", "Praxair"), "APD": ("Air Products",),
    "ECL": ("Ecolab",), "NEM": ("Newmont",), "DUK": ("Duke Energy",),
    "SO": ("Southern Company", "Southern Co"), "D": ("Dominion Energy", "Dominion Resources", "Dominion"),
    "SLB": ("Schlumberger",), "COP": ("ConocoPhillips",), "MS": ("Morgan Stanley",),
    "WFC": ("Wells Fargo",), "AXP": ("American Express", "AmEx", "Amex"), "LLY": ("Eli Lilly", "Lilly"),
    "TMO": ("Thermo Fisher",), "ABT": ("Abbott Laboratories", "Abbott"), "ADBE": ("Adobe",),
    "CRM": ("Salesforce.com", "Salesforce"), "QCOM": ("Qualcomm",), "LOW": ("Lowe's", "Lowe’s", "Lowes"),
    "PM": ("Philip Morris",), "PSX": ("Phillips 66",), "VLO": ("Valero",),
    "OXY": ("Occidental Petroleum", "Occidental"), "WMB": ("Williams Companies", "Williams Cos"),
    "KMI": ("Kinder Morgan",), "GE": ("General Electric",), "RTX": ("Raytheon", "United Technologies"),
    "LMT": ("Lockheed Martin", "Lockheed"), "DE": ("John Deere", "Deere"), "EMR": ("Emerson Electric", "Emerson"),
    "AEP": ("American Electric Power",), "EXC": ("Exelon",), "SRE": ("Sempra",),
    "XEL": ("Xcel Energy", "Xcel"), "ED": ("Consolidated Edison", "Con Edison", "ConEd"), "O": ("Realty Income",),
    "PSA": ("Public Storage",), "WELL": ("Welltower", "Health Care REIT"), "DLR": ("Digital Realty",),
    "AVB": ("AvalonBay",), "SHW": ("Sherwin-Williams", "Sherwin Williams"), "FCX": ("Freeport-McMoRan", "Freeport"),
    "DOW": ("Dow Chemical", "Dow Inc", "Dow"), "NUE": ("Nucor",),
}


# ---------------------------------------------------------------- Jev client

class JevError(RuntimeError):
    pass


def _post_json(url: str, payload: dict, api_key: str, timeout: float) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 -- fixed https URL
        return json.loads(response.read().decode("utf-8"))


class JevClient:
    """Minimal client for POST /v1/systemone (docs.typesafe.ai/api.md).
    The key is held only in memory and never appears in any message this
    class raises or prints."""

    def __init__(
        self,
        api_key: str,
        *,
        transport: Callable[[str, dict, str, float], dict] = _post_json,
        max_retries: int = 5,
        timeout: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key:
            raise JevError("JEV_API_KEY is empty")
        self._api_key = api_key
        self._transport = transport
        self._max_retries = max_retries
        self._timeout = timeout
        self._sleep = sleep

    def evaluate(self, state, questions: dict) -> dict:
        payload = {"state": state, "model": JEV_MODEL, "questions": questions}
        for attempt in range(self._max_retries + 1):
            try:
                return self._transport(JEV_ENDPOINT, payload, self._api_key, self._timeout)
            except urllib.error.HTTPError as exc:
                if exc.code in (429, 500, 502, 503, 529) and attempt < self._max_retries:
                    self._sleep(min(2 ** attempt, 30))
                    continue
                raise JevError(f"Jev HTTP {exc.code}") from None
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt < self._max_retries:
                    self._sleep(min(2 ** attempt, 30))
                    continue
                raise JevError(f"Jev connection failed: {type(exc).__name__}") from None
        raise JevError("unreachable")


SENTIMENT_QUESTION = {
    "type": "choice",
    "instructions": (
        "This is a financial news headline about one company. For a shareholder of that "
        "company, is this headline good news, bad news, or neither for the stock price?"
    ),
    "criteria": {
        "positive": "good news for the company's stock price",
        "neutral": "no clear effect on the company's stock price, or purely informational",
        "negative": "bad news for the company's stock price",
    },
}

PROBE_QUESTION = {
    "type": "noul",
    "instructions": (
        "Over the five trading days after the given date, did this company's stock "
        "outperform the overall US stock market?"
    ),
}


def sentiment_signal(answer: dict) -> Optional[float]:
    probabilities = answer.get("probabilities") or {}
    if "positive" not in probabilities or "negative" not in probabilities:
        return None
    return float(probabilities["positive"]) - float(probabilities["negative"])


def probe_signal(answer: dict) -> Optional[float]:
    value = answer.get("noul")
    return None if value is None else float(value) - 0.5


# ------------------------------------------------------------ text handling

def mask_headline(headline: str, symbol: str) -> str:
    text = headline
    for alias in sorted(COMPANY_ALIASES.get(symbol, ()), key=len, reverse=True):
        text = re.sub(rf"(?<![A-Za-z]){re.escape(alias)}(?:'s|’s|s)?(?![A-Za-z])", "the company", text)
    # Exchange-prefixed / $-prefixed tickers are unambiguous even for 1-2 letter symbols.
    text = re.sub(rf"\b(?:NYSE|NASDAQ|Nasdaq|NasdaqGS|NYSEARCA)\s*:\s*{re.escape(symbol)}\b", "the company's ticker", text)
    text = re.sub(rf"\${re.escape(symbol)}\b", "the company's ticker", text)
    if len(symbol) >= 3:
        text = re.sub(rf"(?<![A-Za-z]){re.escape(symbol)}(?![A-Za-z])", "the company's ticker", text)
    return text


def parse_news_timestamp(raw: str) -> Optional[datetime]:
    raw = (raw or "").strip()
    if not raw:
        return None
    raw = raw.replace(" UTC", "").replace("T", " ").rstrip("Z")
    for fmt in ("%Y-%m-%d %H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(raw, fmt)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


def event_day(timestamp: datetime) -> date:
    """Calendar day whose close is the first one that can have seen the
    headline. A 00:00:00 stamp is treated as date-only (no rollover); the
    forward window starts a trading day later anyway."""
    has_time = (timestamp.hour, timestamp.minute, timestamp.second) != (0, 0, 0)
    if has_time and timestamp.hour >= CLOSE_HOUR_UTC:
        return timestamp.date() + timedelta(days=1)
    return timestamp.date()


# ------------------------------------------------------------------ extract

def _pick(row: dict, *names: str) -> str:
    lowered = {k.lower().strip(): v for k, v in row.items() if k}
    for name in names:
        if name.lower() in lowered and lowered[name.lower()]:
            return lowered[name.lower()]
    return ""


def extract_sample(
    rows: Iterable[dict],
    symbols: set[str],
    start: date,
    end_exclusive: date,
    sample_size: int,
    seed: int,
) -> tuple[list[dict], dict]:
    by_key: dict[tuple[str, str], dict] = {}
    stats = {"rows_read": 0, "rows_in_universe": 0, "rows_in_window": 0, "unparseable_dates": 0}
    for row in rows:
        stats["rows_read"] += 1
        symbol = _pick(row, "Stock_symbol").strip().upper()
        if symbol not in symbols:
            continue
        stats["rows_in_universe"] += 1
        timestamp = parse_news_timestamp(_pick(row, "Date"))
        if timestamp is None:
            stats["unparseable_dates"] += 1
            continue
        day = event_day(timestamp)
        if not (start <= day < end_exclusive):
            continue
        headline = " ".join(_pick(row, "Article_title").split())
        if not headline:
            continue
        stats["rows_in_window"] += 1
        key = (symbol, day.isoformat())
        if key not in by_key:  # first headline seen for that (symbol, day); order is the file's, not ours
            by_key[key] = {"symbol": symbol, "event_day": day.isoformat(), "headline": headline}
    stats["unique_symbol_days"] = len(by_key)

    rng = random.Random(seed)
    by_year: dict[str, list[dict]] = {}
    for item in sorted(by_key.values(), key=lambda r: (r["event_day"], r["symbol"])):
        by_year.setdefault(item["event_day"][:4], []).append(item)
    years = sorted(by_year)
    sample: list[dict] = []
    if years:
        per_year = max(1, sample_size // len(years))
        for year in years:
            pool = by_year[year]
            sample.extend(rng.sample(pool, min(per_year, len(pool))))
    stats["sample_size"] = len(sample)
    stats["sample_by_year"] = {y: sum(1 for s in sample if s["event_day"].startswith(y)) for y in years}
    return sample, stats


# ---------------------------------------------------------------- returns

class PriceTable:
    """Adjusted closes per symbol on one shared trading calendar."""

    def __init__(self, closes: dict[str, dict[date, float]]) -> None:
        self.closes = closes
        self.calendar = sorted({d for series in closes.values() for d in series})

    def _ret(self, symbol: str, d0: date, d1: date) -> Optional[float]:
        series = self.closes.get(symbol, {})
        if d0 not in series or d1 not in series or series[d0] <= 0:
            return None
        return series[d1] / series[d0] - 1.0

    def _market(self, d0: date, d1: date) -> Optional[float]:
        values = [r for s in self.closes if (r := self._ret(s, d0, d1)) is not None]
        return sum(values) / len(values) if values else None

    def excess_returns(self, symbol: str, day: date, horizon: int = FORWARD_DAYS) -> dict:
        """reaction: close(before event day) -> close(trading day after).
        forward: close(trading day after) -> `horizon` trading days later."""
        i = bisect.bisect_left(self.calendar, day)
        out: dict[str, Optional[float]] = {"reaction": None, "forward": None}
        if i < 1 or i + 1 + horizon >= len(self.calendar):
            return out
        windows = {
            "reaction": (self.calendar[i - 1], self.calendar[i + 1]),
            "forward": (self.calendar[i + 1], self.calendar[i + 1 + horizon]),
        }
        for name, (d0, d1) in windows.items():
            stock, market = self._ret(symbol, d0, d1), self._market(d0, d1)
            if stock is None or market is None or abs(stock) > MAX_ABS_WINDOW_RETURN:
                continue
            out[name] = stock - market
        return out


def load_price_table(db_path: Path, symbols: list[str], start: date, end: date) -> PriceTable:
    from storage.config import StorageConfig
    from storage.data_repository import DuckDBDataRepository
    from storage.engine import StorageEngine

    repository = DuckDBDataRepository(StorageEngine(StorageConfig(root_dir=db_path)))
    t0 = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
    t1 = datetime(end.year, end.month, end.day, tzinfo=timezone.utc)
    closes: dict[str, dict[date, float]] = {}
    for symbol in symbols:
        bars = repository.get_bars(symbol, t0, t1, as_of_time=t1)
        series = {b.timestamp.date(): float(b.adjusted_close or b.close) for b in bars}
        if series:
            closes[symbol] = series
    return PriceTable(closes)


# ------------------------------------------------------------------ stats

def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda k: values[k])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2.0
        i = j + 1
    return ranks


def spearman(x: list[float], y: list[float]) -> Optional[float]:
    if len(x) < 3:
        return None
    rx, ry = _ranks(x), _ranks(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    if vx == 0 or vy == 0:
        return None
    return cov / (vx * vy) ** 0.5


def _percentile(sorted_values: list[float], q: float) -> float:
    idx = min(len(sorted_values) - 1, max(0, int(round(q * (len(sorted_values) - 1)))))
    return sorted_values[idx]


def bootstrap_ci(stat: Callable[[list[int]], Optional[float]], n: int, *, resamples: int, seed: int) -> Optional[list[float]]:
    rng = random.Random(seed)
    values = []
    for _ in range(resamples):
        idx = [rng.randrange(n) for _ in range(n)]
        v = stat(idx)
        if v is not None:
            values.append(v)
    if len(values) < resamples // 2:
        return None
    values.sort()
    return [_percentile(values, 0.025), _percentile(values, 0.975)]


def signal_metrics(signal: list[float], target: list[float], *, resamples: int, seed: int) -> dict:
    n = len(signal)
    ic = spearman(signal, target)
    ci = bootstrap_ci(
        lambda idx: spearman([signal[i] for i in idx], [target[i] for i in idx]), n, resamples=resamples, seed=seed
    ) if n >= 30 else None
    order = sorted(range(n), key=lambda i: signal[i])
    third = n // 3
    spread = None
    if third >= 10:
        low = [target[i] for i in order[:third]]
        high = [target[i] for i in order[-third:]]
        spread = sum(high) / len(high) - sum(low) / len(low)
    decided = [(s, t) for s, t in zip(signal, target) if abs(s) >= 0.2 and t != 0]
    hit = sum(1 for s, t in decided if (s > 0) == (t > 0)) / len(decided) if decided else None
    return {
        "n": n, "spearman_ic": ic, "ic_ci95": ci,
        "top_minus_bottom_tercile_excess_return": spread,
        "hit_rate_when_abs_signal_ge_0_2": hit, "n_hit_rate": len(decided),
    }


def gap_ci(a: list[float], b: list[float], target: list[float], *, resamples: int, seed: int) -> Optional[list[float]]:
    n = len(target)

    def stat(idx: list[int]) -> Optional[float]:
        t = [target[i] for i in idx]
        ia, ib = spearman([a[i] for i in idx], t), spearman([b[i] for i in idx], t)
        return None if ia is None or ib is None else ia - ib

    return bootstrap_ci(stat, n, resamples=resamples, seed=seed) if n >= 30 else None


# --------------------------------------------------------------- evaluate

def ask_jev(client: JevClient, item: dict) -> dict:
    symbol, headline = item["symbol"], item["headline"]
    masked = client.evaluate(mask_headline(headline, symbol), {"sentiment": SENTIMENT_QUESTION})
    unmasked = client.evaluate(f"Ticker: {symbol}\nHeadline: {headline}", {"sentiment": SENTIMENT_QUESTION})
    probe = client.evaluate(
        {"ticker": symbol, "date": item["event_day"], "headline": headline}, {"outperformed": PROBE_QUESTION}
    )
    usage = sum(int((r.get("usage") or {}).get("input_tokens", 0)) for r in (masked, unmasked, probe))
    return {
        "masked": sentiment_signal(masked["answers"]["sentiment"]),
        "unmasked": sentiment_signal(unmasked["answers"]["sentiment"]),
        "probe": probe_signal(probe["answers"]["outperformed"]),
        "model": masked.get("model"),
        "input_tokens": usage,
    }


def build_report(rows: list[dict], *, resamples: int, seed: int) -> dict:
    report: dict = {"metrics": {}, "by_year_masked_forward_ic": {}}
    for target_name in ("reaction", "forward"):
        usable = [r for r in rows if r.get(target_name) is not None and None not in (r["masked"], r["unmasked"], r["probe"])]
        target = [r[target_name] for r in usable]
        block = {
            variant: signal_metrics([r[variant] for r in usable], target, resamples=resamples, seed=seed)
            for variant in ("masked", "unmasked", "probe")
        }
        block["unmasked_minus_masked_ic_ci95"] = gap_ci(
            [r["unmasked"] for r in usable], [r["masked"] for r in usable], target, resamples=resamples, seed=seed
        )
        report["metrics"][target_name] = block
    forward = [r for r in rows if r.get("forward") is not None and r["masked"] is not None]
    for year in sorted({r["event_day"][:4] for r in forward}):
        subset = [r for r in forward if r["event_day"].startswith(year)]
        report["by_year_masked_forward_ic"][year] = {
            "n": len(subset), "ic": spearman([r["masked"] for r in subset], [r["forward"] for r in subset]),
        }

    fwd = report["metrics"]["forward"]
    masked_ci, probe_ci, gap = fwd["masked"]["ic_ci95"], fwd["probe"]["ic_ci95"], fwd["unmasked_minus_masked_ic_ci95"]
    checks = {
        "masked_forward_ic_ci_lower_gt_0": bool(masked_ci and masked_ci[0] > 0),
        "probe_forward_ic_ci_contains_0": bool(probe_ci and probe_ci[0] <= 0 <= probe_ci[1]),
        "unmasked_gap_not_significantly_positive": bool(gap and gap[0] <= 0),
    }
    report["pass_rule_checks"] = checks
    report["verdict"] = "PASS" if all(checks.values()) else "FAIL"
    return report


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _universe(name: str):
    from data_infra.universe import RESEARCH_UNIVERSE_STAGE4

    if name != "RESEARCH_UNIVERSE_STAGE4":
        raise SystemExit(f"unsupported universe {name!r}")
    return list(RESEARCH_UNIVERSE_STAGE4.symbol_ids)


def _default_end(buffer_days: int) -> date:
    from strategy_research.locked_windows import earliest_locked_window_start

    return earliest_locked_window_start().date() - timedelta(days=buffer_days)


def _require_unlocked(start: date, end: date) -> None:
    from strategy_research.locked_windows import overlaps_any_locked_window

    locked = overlaps_any_locked_window(
        datetime(start.year, start.month, start.day, tzinfo=timezone.utc),
        datetime(end.year, end.month, end.day, tzinfo=timezone.utc),
    )
    if locked:
        raise SystemExit(f"range {start}..{end} overlaps locked window(s): {', '.join(w.name for w in locked)}")


def _api_key() -> str:
    key = os.environ.get("JEV_API_KEY", "").strip()
    if not key:
        raise SystemExit("JEV_API_KEY is not set (GitHub Actions secret JEV_API_KEY)")
    return key


def cmd_smoke(_args) -> int:
    client = JevClient(_api_key())
    response = client.evaluate(
        "Acme Corp beats quarterly earnings estimates and raises full-year guidance.",
        {"sentiment": SENTIMENT_QUESTION},
    )
    answer = response["answers"]["sentiment"]
    print(json.dumps({
        "model": response.get("model"), "choice": answer.get("choice"),
        "probabilities": answer.get("probabilities"), "confidence": answer.get("confidence"),
        "usage": response.get("usage"),
    }, indent=2))
    return 0 if answer.get("choice") == "positive" else 1


def cmd_extract(args) -> int:
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end) if args.end else _default_end(args.horizon_buffer_days)
    _require_unlocked(start, end + timedelta(days=args.horizon_buffer_days))
    csv.field_size_limit(sys.maxsize)
    stream: TextIO = open(args.input, encoding="utf-8", errors="replace", newline="") if args.input else sys.stdin
    try:
        sample, stats = extract_sample(
            csv.DictReader(stream), set(_universe(args.universe)), start, end, args.sample_size, args.seed
        )
    finally:
        if args.input:
            stream.close()
    args.out.write_text("".join(json.dumps(s, ensure_ascii=False) + "\n" for s in sample), encoding="utf-8")
    stats.update({"start": start.isoformat(), "end_exclusive": end.isoformat()})
    Path(str(args.out) + ".stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    print(json.dumps(stats, indent=2))
    return 0 if sample else 1


def cmd_evaluate(args) -> int:
    sample = _read_jsonl(args.sample)
    if not sample:
        print("FATAL: empty sample", file=sys.stderr)
        return 1
    days = [date.fromisoformat(s["event_day"]) for s in sample]
    price_start, price_end = min(days) - timedelta(days=10), max(days) + timedelta(days=args.horizon_buffer_days)
    _require_unlocked(price_start, price_end)
    prices = load_price_table(args.db_path, _universe(args.universe), price_start, price_end)

    rows = []
    for item in sample:
        rets = prices.excess_returns(item["symbol"], date.fromisoformat(item["event_day"]))
        if rets["forward"] is None and rets["reaction"] is None:
            continue
        rows.append({**item, **rets})
    dropped_no_prices = len(sample) - len(rows)

    client = JevClient(_api_key())
    failures = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(ask_jev, client, r) for r in rows]
        answered = []
        for row, future in zip(rows, futures):
            try:
                answered.append({**row, **future.result()})
            except (JevError, KeyError, TypeError, ValueError) as exc:
                failures += 1
                print(f"warn: Jev call failed for one item: {exc}", file=sys.stderr)
    if failures > len(rows) * 0.1:
        print(f"FATAL: {failures}/{len(rows)} Jev calls failed", file=sys.stderr)
        return 1

    report = build_report(answered, resamples=args.resamples, seed=args.seed)
    report.update({
        "experiment": "jev_news_poc_v1",
        "adr": "ADR-0218",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "jev_model_served": next((r["model"] for r in answered if r.get("model")), None),
        "universe": args.universe,
        "event_day_range": [min(days).isoformat(), max(days).isoformat()],
        "forward_horizon_trading_days": FORWARD_DAYS,
        "market_proxy": "equal-weight mean return of the universe symbols over the same window",
        "news_source": FNSPID_ALL_EXTERNAL_URL,
        "sample_items": len(sample),
        "dropped_no_prices": dropped_no_prices,
        "jev_failures": failures,
        "items_evaluated": len(answered),
        "total_input_tokens": sum(r["input_tokens"] for r in answered),
        "bootstrap_resamples": args.resamples,
    })
    args.report_out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("smoke")

    extract = sub.add_parser("extract")
    extract.add_argument("--input", type=Path, default=None, help="FNSPID CSV path; stdin when omitted")
    extract.add_argument("--out", type=Path, required=True)
    extract.add_argument("--universe", default="RESEARCH_UNIVERSE_STAGE4")
    extract.add_argument("--start", default="2010-01-01")
    extract.add_argument("--end", default=None, help="exclusive; default = first locked window start - buffer")
    extract.add_argument("--sample-size", type=int, default=2000)
    extract.add_argument("--seed", type=int, default=20260926)
    extract.add_argument("--horizon-buffer-days", type=int, default=30)

    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("--sample", type=Path, required=True)
    evaluate.add_argument("--db-path", type=Path, required=True)
    evaluate.add_argument("--report-out", type=Path, required=True)
    evaluate.add_argument("--universe", default="RESEARCH_UNIVERSE_STAGE4")
    evaluate.add_argument("--workers", type=int, default=8)
    evaluate.add_argument("--resamples", type=int, default=1000)
    evaluate.add_argument("--seed", type=int, default=20260926)
    evaluate.add_argument("--horizon-buffer-days", type=int, default=30)

    args = parser.parse_args(argv)
    return {"smoke": cmd_smoke, "extract": cmd_extract, "evaluate": cmd_evaluate}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
