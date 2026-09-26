"""Category: Research PoC -- scripts/run_jev_news_poc.py (ADR-0218).

No network: every Jev call goes through an injected fake transport, and
prices come from an in-memory PriceTable."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import urllib.error
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "run_jev_news_poc.py"


def _load():
    spec = importlib.util.spec_from_file_location("run_jev_news_poc", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


poc = _load()


# ----------------------------------------------------------------- masking

def test_mask_removes_company_name_and_possessive():
    assert poc.mask_headline("Apple's iPhone sales beat estimates", "AAPL") == "the company iPhone sales beat estimates"


def test_mask_removes_long_ticker_but_not_short_ticker_words():
    assert "AAPL" not in poc.mask_headline("AAPL shares jump", "AAPL")
    # "T" must not eat every capital T; only the exchange-prefixed form is masked.
    masked = poc.mask_headline("The Street likes AT&T (NYSE: T) today", "T")
    assert "AT&T" not in masked and "NYSE: T" not in masked and masked.startswith("The Street")


def test_every_universe_symbol_has_aliases():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
    from data_infra.universe import RESEARCH_UNIVERSE_STAGE4

    assert set(RESEARCH_UNIVERSE_STAGE4.symbol_ids) <= set(poc.COMPANY_ALIASES)


# ------------------------------------------------------------- timestamps

def test_after_close_headline_rolls_to_next_day():
    ts = poc.parse_news_timestamp("2015-03-02 21:15:00 UTC")
    assert poc.event_day(ts) == date(2015, 3, 3)


def test_intraday_and_date_only_headlines_keep_their_day():
    assert poc.event_day(poc.parse_news_timestamp("2015-03-02 14:00:00 UTC")) == date(2015, 3, 2)
    assert poc.event_day(poc.parse_news_timestamp("2015-03-02")) == date(2015, 3, 2)


def test_unparseable_timestamp_is_none():
    assert poc.parse_news_timestamp("not a date") is None


# ----------------------------------------------------------------- extract

def _csv_rows(text: str):
    import csv

    return csv.DictReader(io.StringIO(text))


def test_extract_filters_universe_window_and_dedupes():
    text = (
        "Unnamed: 0,Date,Article_title,Stock_symbol\n"
        "0,2012-05-01 10:00:00 UTC,Apple beats,AAPL\n"
        "1,2012-05-01 11:00:00 UTC,Apple second headline same day,AAPL\n"
        "2,2012-05-01 10:00:00 UTC,Unknown co,ZZZZ\n"
        "3,2009-12-31 10:00:00 UTC,Too early,MSFT\n"
        "4,2021-01-05 10:00:00 UTC,Locked window,MSFT\n"
        "5,2013-07-01 10:00:00 UTC,Microsoft news,msft\n"
    )
    sample, stats = poc.extract_sample(
        _csv_rows(text), {"AAPL", "MSFT"}, date(2010, 1, 1), date(2020, 7, 29), sample_size=10, seed=1
    )
    assert {(s["symbol"], s["event_day"]) for s in sample} == {("AAPL", "2012-05-01"), ("MSFT", "2013-07-01")}
    assert stats["unique_symbol_days"] == 2
    assert stats["rows_in_universe"] == 5


def test_extract_default_end_is_before_every_locked_window():
    end = poc._default_end(30)
    poc._require_unlocked(date(2010, 1, 1), end + timedelta(days=30))  # must not raise


def test_require_unlocked_refuses_locked_range():
    with pytest.raises(SystemExit):
        poc._require_unlocked(date(2020, 1, 1), date(2021, 1, 1))


# ----------------------------------------------------------------- returns

def _table():
    days = [date(2015, 1, 1) + timedelta(days=i) for i in range(12)]
    return days, poc.PriceTable({
        "AAA": {d: 100.0 + i for i, d in enumerate(days)},
        "BBB": {d: 100.0 for d in days},
    })


def test_forward_window_starts_after_event_day():
    days, table = _table()
    out = table.excess_returns("AAA", days[3], horizon=5)
    # forward: close(day4) -> close(day9); market = mean(AAA, BBB)
    aaa = 109 / 104 - 1
    assert out["forward"] == pytest.approx(aaa - aaa / 2)
    # reaction: close(day2) -> close(day4)
    aaa_r = 104 / 102 - 1
    assert out["reaction"] == pytest.approx(aaa_r - aaa_r / 2)


def test_returns_none_near_calendar_edges():
    days, table = _table()
    assert table.excess_returns("AAA", days[0])["forward"] is None
    assert table.excess_returns("AAA", days[-2])["forward"] is None


def test_implausible_move_is_dropped():
    days = [date(2015, 1, 1) + timedelta(days=i) for i in range(12)]
    table = poc.PriceTable({"AAA": {d: (100.0 if i < 6 else 10.0) for i, d in enumerate(days)}, "BBB": {d: 50.0 for d in days}})
    assert table.excess_returns("AAA", days[3], horizon=5)["forward"] is None


# ------------------------------------------------------------------- stats

def test_spearman_perfect_and_inverse():
    assert poc.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert poc.spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    assert poc.spearman([1, 1, 1], [1, 2, 3]) is None


def _rows(n, *, masked_fn, probe_fn, unmasked_fn=None):
    import random

    rng = random.Random(7)
    rows = []
    for i in range(n):
        fwd = rng.gauss(0, 0.02)
        rows.append({
            "event_day": f"{2011 + i % 5}-06-01", "forward": fwd, "reaction": fwd,
            "masked": masked_fn(fwd, rng), "unmasked": (unmasked_fn or masked_fn)(fwd, rng),
            "probe": probe_fn(fwd, rng),
        })
    return rows


def test_report_passes_when_masked_signal_is_real_and_probe_is_noise():
    rows = _rows(400, masked_fn=lambda f, r: f + r.gauss(0, 0.01), probe_fn=lambda f, r: r.gauss(0, 0.1))
    report = poc.build_report(rows, resamples=200, seed=1)
    assert report["verdict"] == "PASS"


def test_report_fails_when_probe_knows_outcomes():
    rows = _rows(400, masked_fn=lambda f, r: f + r.gauss(0, 0.01), probe_fn=lambda f, r: f)
    report = poc.build_report(rows, resamples=200, seed=1)
    assert report["pass_rule_checks"]["probe_forward_ic_ci_contains_0"] is False
    assert report["verdict"] == "FAIL"


def test_report_fails_when_masked_signal_is_noise():
    rows = _rows(400, masked_fn=lambda f, r: r.gauss(0, 1), probe_fn=lambda f, r: r.gauss(0, 0.1))
    assert poc.build_report(rows, resamples=200, seed=1)["verdict"] == "FAIL"


# -------------------------------------------------------------- Jev client

def _answer(probs=None, noul=None):
    answers = {}
    if probs is not None:
        answers["sentiment"] = {"type": "choice", "choice": max(probs, key=probs.get), "probabilities": probs}
    if noul is not None:
        answers["outperformed"] = {"type": "noul", "noul": noul}
    return {"model": "jev-1.13.0", "answers": answers, "usage": {"input_tokens": 10, "output_tokens": 1}}


def test_ask_jev_sends_three_separate_framings():
    seen = []

    def transport(url, payload, key, timeout):
        seen.append(payload)
        if "outperformed" in payload["questions"]:
            return _answer(noul=0.7)
        return _answer(probs={"positive": 0.6, "neutral": 0.3, "negative": 0.1})

    client = poc.JevClient("k", transport=transport)
    out = poc.ask_jev(client, {"symbol": "AAPL", "event_day": "2014-02-03", "headline": "Apple beats estimates"})
    assert out["masked"] == pytest.approx(0.5) and out["probe"] == pytest.approx(0.2)
    assert out["input_tokens"] == 30
    assert "Apple" not in json.dumps(seen[0]["state"]) and "2014" not in json.dumps(seen[0]["state"])
    assert "2014" not in json.dumps(seen[1]["state"])
    assert seen[2]["state"]["date"] == "2014-02-03"
    assert all(p["model"] == "jev-latest" for p in seen)


def test_client_retries_rate_limit_then_succeeds():
    calls = {"n": 0}

    def transport(url, payload, key, timeout):
        calls["n"] += 1
        if calls["n"] < 3:
            raise urllib.error.HTTPError(url, 429, "rate", {}, None)
        return _answer(probs={"positive": 1.0, "neutral": 0.0, "negative": 0.0})

    client = poc.JevClient("k", transport=transport, sleep=lambda s: None)
    assert client.evaluate("x", {})["model"] == "jev-1.13.0"
    assert calls["n"] == 3


def test_client_error_never_contains_key():
    def transport(url, payload, key, timeout):
        raise urllib.error.HTTPError(url, 401, f"bad key {key}", {}, None)

    client = poc.JevClient("SECRET-KEY-123", transport=transport, sleep=lambda s: None)
    with pytest.raises(poc.JevError) as exc:
        client.evaluate("x", {})
    assert "SECRET-KEY-123" not in str(exc.value) and exc.value.__cause__ is None


def test_script_does_not_import_trading_pipeline():
    source = _SCRIPT_PATH.read_text()
    for package in ("predict", "decision", "risk", "broker", "ai_gateway"):
        assert f"from {package}" not in source and f"import {package}" not in source
