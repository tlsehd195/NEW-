"""Shared test helpers for the Phase 2 backtesting test suite."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Sequence

from data_infra.calendar import US_EQUITY
from data_infra.enums import (
    BenchmarkReturnType,
    CorporateActionType,
    InstrumentType,
    SecurityStatus,
)
from data_infra.models import (
    BenchmarkPoint,
    CorporateAction,
    PriceBar,
    Provenance,
    SecurityMaster,
    UniverseMembership,
)
from data_infra.repository import InMemoryDataRepository


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def checkpoint(d: date, hour: int = 20) -> datetime:
    return utc(d.year, d.month, d.day, hour)


def trading_days(start: date, end: date, calendar=US_EQUITY) -> list[date]:
    days = []
    current = start
    while current <= end:
        if calendar.is_trading_day(current):
            days.append(current)
        current += timedelta(days=1)
    return days


def make_provenance(source_record_id: str, day: date, source: str = "test_source") -> Provenance:
    return Provenance(
        source=source,
        source_dataset=f"test_{source}",
        source_record_id=source_record_id,
        retrieved_at=checkpoint(day),
        data_version=f"v-{day.isoformat()}",
    )


def make_bars(
    security_id: str,
    days: Sequence[date],
    closes: Sequence[float],
    *,
    volume: float = 200_000.0,
    source: str = "test_source",
) -> list[PriceBar]:
    assert len(days) == len(closes)
    bars = []
    for d, close in zip(days, closes):
        bars.append(
            PriceBar(
                security_id=security_id,
                timestamp=checkpoint(d, 0),
                open=close,
                high=close * 1.005,
                low=close * 0.995,
                close=close,
                volume=volume,
                available_time=checkpoint(d),
                ingestion_time=checkpoint(d),
                provenance=make_provenance(f"{security_id}-{d.isoformat()}", d, source),
                adjusted_close=close,
            )
        )
    return bars


def make_security(
    security_id: str,
    ticker: str,
    *,
    valid_from: datetime = utc(2020, 1, 1),
    valid_to: datetime | None = None,
    status: SecurityStatus = SecurityStatus.ACTIVE,
) -> SecurityMaster:
    return SecurityMaster(
        security_id=security_id,
        ticker=ticker,
        exchange="NASDAQ",
        currency="USD",
        company_id=f"COMPANY-{ticker}",
        instrument_type=InstrumentType.EQUITY,
        valid_from=valid_from,
        valid_to=valid_to,
        status=status,
    )


def make_benchmark(days: Sequence[date], levels: Sequence[float], benchmark_id: str = "SP500") -> list[BenchmarkPoint]:
    assert len(days) == len(levels)
    points = []
    for d, level in zip(days, levels):
        points.append(
            BenchmarkPoint(
                benchmark_id=benchmark_id,
                timestamp=checkpoint(d, 0),
                level=level,
                return_type=BenchmarkReturnType.PRICE_RETURN,
                currency="USD",
                available_time=checkpoint(d),
                ingestion_time=checkpoint(d),
                provenance=make_provenance(f"{benchmark_id}-{d.isoformat()}", d, "bench_source"),
            )
        )
    return points


def make_split(security_id: str, effective_day: date, ratio: str = "2:1") -> CorporateAction:
    return CorporateAction(
        security_id=security_id,
        action_type=CorporateActionType.SPLIT,
        available_time=checkpoint(effective_day),
        ingestion_time=checkpoint(effective_day),
        provenance=make_provenance(f"{security_id}-split-{effective_day.isoformat()}", effective_day, "corp_actions"),
        event_time=checkpoint(effective_day, 0),
        effective_time=checkpoint(effective_day, 0),
        details={"ratio": ratio},
    )


def make_dividend(security_id: str, effective_day: date, amount: float) -> CorporateAction:
    return CorporateAction(
        security_id=security_id,
        action_type=CorporateActionType.DIVIDEND,
        available_time=checkpoint(effective_day),
        ingestion_time=checkpoint(effective_day),
        provenance=make_provenance(
            f"{security_id}-div-{effective_day.isoformat()}", effective_day, "corp_actions"
        ),
        event_time=checkpoint(effective_day, 0),
        effective_time=checkpoint(effective_day, 0),
        details={"amount": amount},
    )


def make_membership(
    security_id: str, valid_from: datetime, valid_to: datetime | None = None, universe: str = "SP500"
) -> UniverseMembership:
    return UniverseMembership(security_id=security_id, universe=universe, valid_from=valid_from, valid_to=valid_to)


def build_repository(
    *,
    bars: Sequence[PriceBar] = (),
    securities: Sequence[SecurityMaster] = (),
    corporate_actions: Sequence[CorporateAction] = (),
    benchmarks: Sequence[BenchmarkPoint] = (),
    universe_memberships: Sequence[UniverseMembership] = (),
) -> InMemoryDataRepository:
    return InMemoryDataRepository(
        bars=bars,
        securities=securities,
        corporate_actions=corporate_actions,
        benchmarks=benchmarks,
        universe_memberships=universe_memberships,
        calendars={"US_EQUITY": US_EQUITY},
    )
