"""Shared test helpers for the Phase 23 strategy_research test suite.

**SYNTHETIC / TEST FIXTURE ONLY.** Every price series this module
produces is a closed-form deterministic function (no `random` module,
no real market data) -- it exists solely to give the strategy_research
pipeline (leakage, determinism, cost integration, benchmark comparison,
train/validation/test boundaries) enough multi-year history to actually
exercise long lookback windows and multiple rebalances. Metrics computed
against this data are PIPELINE-VALIDATION RESULTS ONLY and must never be
reported, logged, or documented as real strategy performance evidence
(instruction sections 6/35/38 -- see
docs/research/STRATEGY-RESEARCH-REPORT.md for how this distinction is
actually maintained in this Phase's reporting).
"""

from __future__ import annotations

import math
from datetime import date, datetime, timezone

from backtest_helpers import build_repository, make_bars, make_benchmark, make_security, trading_days

from data_infra.repository import InMemoryDataRepository

SYNTHETIC_UNIVERSE = ("TRENDUP", "TRENDDOWN", "CYCLICAL", "FLATLOW", "FLATHIGH")


def _trendup(i: int) -> float:
    return 100.0 * (1.0006**i)


def _trenddown(i: int) -> float:
    return 100.0 * (0.9997**i)


def _cyclical(i: int) -> float:
    return 100.0 * (1.0001**i) * (1.0 + 0.12 * math.sin(i / 30.0))


def _flat_low_vol(i: int) -> float:
    return 100.0 * (1.0 + 0.01 * math.sin(i / 15.0))


def _flat_high_vol(i: int) -> float:
    # Deterministically alternating +-8% day over day (not a smooth
    # sine -- a smooth low-frequency oscillation has much lower
    # day-to-day realized volatility than its amplitude alone suggests,
    # since consecutive daily returns stay small). This alternation
    # gives a genuinely large day-to-day realized volatility while
    # staying trendless (no persistent drift) and fully deterministic.
    return 100.0 * (1.08 if i % 2 == 0 else 0.92)


_GENERATORS = {
    "TRENDUP": _trendup,
    "TRENDDOWN": _trenddown,
    "CYCLICAL": _cyclical,
    "FLATLOW": _flat_low_vol,
    "FLATHIGH": _flat_high_vol,
}


def synthetic_multi_year_repository(
    start: date, end: date, *, symbols=SYNTHETIC_UNIVERSE, benchmark_id: str = "SP500"
) -> InMemoryDataRepository:
    """Builds an `InMemoryDataRepository` covering `[start, end]` with
    one deterministic-formula price series per symbol in `symbols`
    (must be a subset of `SYNTHETIC_UNIVERSE`), plus a synthetic
    benchmark series (a mild, steady uptrend distinct from any single
    symbol's own path, so benchmark-relative comparisons are
    meaningful, not trivially identical to a symbol)."""
    days = trading_days(start, end)
    bars = []
    securities = []
    for symbol in symbols:
        generator = _GENERATORS[symbol]
        closes = [generator(i) for i in range(len(days))]
        bars.extend(make_bars(symbol, days, closes))
        securities.append(make_security(symbol, symbol, valid_from=days_to_utc(start)))
    bench_levels = [4000.0 * (1.0003**i) for i in range(len(days))]
    bench = make_benchmark(days, bench_levels, benchmark_id=benchmark_id)
    return build_repository(bars=bars, securities=securities, benchmarks=bench)


def days_to_utc(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
