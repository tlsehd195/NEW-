"""Builds a dividend-reinvested (TOTAL_RETURN) BenchmarkPoint series from
raw PriceBar + CorporateAction records.

See docs/decisions/ADR-0026-benchmark-return-type.md for why this exists:
PHASE-2-backtesting.md section 9.3 left PRICE_RETURN vs TOTAL_RETURN as a
DECISION REQUIRED pending a real data source; this phase's ADR decides
TOTAL_RETURN and this module is the concrete construction path -- reusing
`backtest.corporate_actions`'s own split-ratio parsing and event-type
sets rather than duplicating them, and applying the identical
available_time look-ahead discipline used everywhere else in this
project (data_infra.repository, backtest.corporate_actions.
CorporateActionApplier).

`BenchmarkEngine` (backtest/benchmark.py) already reads whichever
`return_type` the underlying BenchmarkPoint data reports and handles it
correctly -- nothing there needs to change for this module's output to
be usable.

**Not yet wired to real data**: this module operates on whatever
PriceBar/CorporateAction records it is given; it fabricates nothing and
does not itself fetch SPY data. Constructing a real SPY total-return
BenchmarkPoint series requires actually ingesting real SPY price and
dividend history first (blocked this phase -- see ADR-0025/ADR-0026),
at which point this function is the intended consumer of that data.
"""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

from data_infra.enums import BenchmarkReturnType
from data_infra.models import BenchmarkPoint, CorporateAction, PriceBar, Provenance
from data_infra.versioning import compute_data_version

from backtest.corporate_actions import _DIVIDEND_TYPES, _SPLIT_TYPES, _parse_ratio


def build_total_return_benchmark_points(
    benchmark_id: str,
    price_bars: Sequence[PriceBar],
    corporate_actions: Sequence[CorporateAction],
    *,
    as_of_time: datetime,
    currency: str = "USD",
    base_level: float = 100.0,
    source: str = "total_return_index",
) -> list[BenchmarkPoint]:
    """Reconstructs a normalized (base_level-indexed, since no real S&P
    500/SPY series is being fabricated -- ADR-0026) total-return index
    from a single security's raw closes plus its SPLIT/REVERSE_SPLIT/
    DIVIDEND corporate actions.

    Point-in-time safety: both `price_bars` and `corporate_actions` are
    defensively re-filtered to `available_time <= as_of_time` here (the
    same "AsOfDataView should never surface this, but re-check anyway"
    discipline as CorporateActionApplier.apply) -- callers are expected
    to have already used the repository's own as-of query, but this
    function does not trust that alone. Each output point's
    `available_time` is the running maximum of every bar's and action's
    `available_time` from the series start through that point (not just
    that day's own), since a level on day T is mathematically a function
    of the entire path from day 0 -- a dividend for day 2 discovered
    late must push the *available_time* of every subsequent day's level
    forward too, exactly mirroring why a corporate action's own
    available_time gates visibility (see
    tests/integration/test_market_data_point_in_time.py). Earlier
    points are never affected, since they do not depend on later
    information -- the past is still never rewritten.
    """
    safe_bars = sorted(
        (b for b in price_bars if b.available_time <= as_of_time), key=lambda b: b.timestamp
    )
    safe_actions = [a for a in corporate_actions if a.available_time <= as_of_time]

    split_ratio_by_date: dict = {}
    dividend_amount_by_date: dict = {}
    action_available_by_date: dict = {}
    for action in safe_actions:
        event_date = (action.effective_time or action.event_time)
        if event_date is None:
            continue
        key = event_date.date()
        latest_available = action_available_by_date.get(key)
        if latest_available is None or action.available_time > latest_available:
            action_available_by_date[key] = action.available_time
        if action.action_type in _SPLIT_TYPES:
            ratio = _parse_ratio(action.details.get("ratio"))
            if ratio is not None and ratio > 0:
                split_ratio_by_date[key] = split_ratio_by_date.get(key, 1.0) * ratio
        elif action.action_type in _DIVIDEND_TYPES:
            amount = action.details.get("amount")
            if amount is not None:
                dividend_amount_by_date[key] = dividend_amount_by_date.get(key, 0.0) + float(amount)

    points: list[BenchmarkPoint] = []
    level = base_level
    running_available_time: datetime = None  # type: ignore[assignment]
    for i, bar in enumerate(safe_bars):
        day = bar.timestamp.date()
        day_available = bar.available_time
        if day in action_available_by_date and action_available_by_date[day] > day_available:
            day_available = action_available_by_date[day]
        running_available_time = day_available if running_available_time is None else max(
            running_available_time, day_available
        )

        if i > 0 and safe_bars[i - 1].close > 0:
            split_ratio = split_ratio_by_date.get(day, 1.0)
            dividend = dividend_amount_by_date.get(day, 0.0)
            total_return_factor = (bar.close * split_ratio + dividend) / safe_bars[i - 1].close
            level = level * total_return_factor

        points.append(
            BenchmarkPoint(
                benchmark_id=benchmark_id,
                timestamp=bar.timestamp,
                level=level,
                return_type=BenchmarkReturnType.TOTAL_RETURN,
                currency=currency,
                available_time=running_available_time,
                ingestion_time=as_of_time,
                provenance=Provenance(
                    source=source,
                    source_dataset=f"{source}_{benchmark_id}",
                    source_record_id=f"{benchmark_id}:{bar.timestamp.isoformat()}",
                    retrieved_at=as_of_time,
                    data_version=compute_data_version(
                        {"benchmark_id": benchmark_id, "timestamp": bar.timestamp, "level": level, "base_level": base_level}
                    ),
                ),
            )
        )
    return points
