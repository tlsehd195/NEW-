"""Macro time-series data model for the planned macro filter (ADR-0217):
point-in-time FRED/ALFRED observations of rates, credit spreads, the
dollar, employment, CPI, PCE, VIX and financial conditions.

**The point-in-time pitfall this module exists to prevent**: a macro
observation's `observation_date` (e.g. CPI for 2024-01) is NOT when it
became public (CPI for January is released mid-February), and the first
published value is often revised later (payrolls are revised twice in
the following two months, then again annually). Using today's FRED value
for a past date leaks both the release lag and every later revision into
a backtest. Every record here is therefore one ALFRED *vintage*: the
value as FRED published it from `realtime_start` onward, with
`available_time` derived from `realtime_start`, never from
`observation_date`.

`available_time` convention (`vintage_available_time`): ALFRED's
real-time dates are calendar dates in US time with no time of day. The
latest instant any US time zone is still on `realtime_start` is before
06:00 UTC of the next day, so `available_time = realtime_start + 1 day,
06:00 UTC`. That can be up to ~20 hours later than the real release
(CPI at 08:30 ET), never earlier -- the only direction of error a
point-in-time guard may make.

Observations older than a series' first archived vintage carry that
first vintage as their `realtime_start`, i.e. they look later than
they really were published. That is again conservative (the backtest
simply cannot use them before that date).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
from typing import Optional

from data_infra.models import Provenance

VINTAGE_AVAILABILITY_OFFSET = timedelta(days=1, hours=6)


class MacroCategory(str, Enum):
    RATES = "RATES"
    CREDIT = "CREDIT"
    DOLLAR = "DOLLAR"
    EMPLOYMENT = "EMPLOYMENT"
    INFLATION = "INFLATION"
    VOLATILITY = "VOLATILITY"
    FINANCIAL_CONDITIONS = "FINANCIAL_CONDITIONS"


@dataclass(frozen=True)
class MacroSeriesSpec:
    series_id: str
    category: MacroCategory
    description: str
    frequency: str  # FRED's own frequency label: "D", "W", "M"
    revised: bool  # True when the published values are routinely revised after release


# The first-stage macro-filter series (ADR-0217). Chosen for long daily/
# monthly history on FRED and a direct mapping to what the account owner
# asked for (rates, dollar, bonds, employment, CPI, PCE, VIX).
# Deliberately NOT included:
# - ICE DXY: not on FRED. DTWEXBGS (Fed broad dollar index, 2006+) is the
#   FRED stand-in; the ICE DXY itself is only obtainable as a traded
#   proxy (e.g. UUP ETF prices), which the price catalog already handles.
# - ICE BofA high-yield OAS (BAMLH0A0HYM2): since April 2026 FRED only
#   serves a rolling 3 years of it (ICE licensing), too short to
#   backtest. BAA10Y (Moody's Baa minus 10-year Treasury, 1986+) is the
#   long-history credit-spread stand-in.
MACRO_SERIES_CATALOG: tuple[MacroSeriesSpec, ...] = (
    MacroSeriesSpec("DFF", MacroCategory.RATES, "Effective federal funds rate", "D", False),
    MacroSeriesSpec("DGS3MO", MacroCategory.RATES, "3-month Treasury constant maturity yield", "D", False),
    MacroSeriesSpec("DGS2", MacroCategory.RATES, "2-year Treasury constant maturity yield", "D", False),
    MacroSeriesSpec("DGS10", MacroCategory.RATES, "10-year Treasury constant maturity yield", "D", False),
    MacroSeriesSpec("T10Y2Y", MacroCategory.RATES, "10-year minus 2-year Treasury spread", "D", False),
    MacroSeriesSpec("T10Y3M", MacroCategory.RATES, "10-year minus 3-month Treasury spread", "D", False),
    MacroSeriesSpec("BAA10Y", MacroCategory.CREDIT, "Moody's Baa corporate yield minus 10-year Treasury", "D", False),
    MacroSeriesSpec("DTWEXBGS", MacroCategory.DOLLAR, "Fed nominal broad U.S. dollar index", "D", True),
    MacroSeriesSpec("PAYEMS", MacroCategory.EMPLOYMENT, "Total nonfarm payrolls", "M", True),
    MacroSeriesSpec("UNRATE", MacroCategory.EMPLOYMENT, "Unemployment rate", "M", True),
    MacroSeriesSpec("ICSA", MacroCategory.EMPLOYMENT, "Initial jobless claims", "W", True),
    MacroSeriesSpec("CPIAUCSL", MacroCategory.INFLATION, "CPI, all items, seasonally adjusted", "M", True),
    MacroSeriesSpec("CPILFESL", MacroCategory.INFLATION, "Core CPI (ex food and energy)", "M", True),
    MacroSeriesSpec("PCEPI", MacroCategory.INFLATION, "PCE price index", "M", True),
    MacroSeriesSpec("PCEPILFE", MacroCategory.INFLATION, "Core PCE price index", "M", True),
    MacroSeriesSpec("VIXCLS", MacroCategory.VOLATILITY, "CBOE VIX close", "D", False),
    MacroSeriesSpec("NFCI", MacroCategory.FINANCIAL_CONDITIONS, "Chicago Fed National Financial Conditions Index", "W", True),
)

MACRO_SERIES_BY_ID: dict[str, MacroSeriesSpec] = {spec.series_id: spec for spec in MACRO_SERIES_CATALOG}


def _require_aware(name: str, value: Optional[datetime]) -> None:
    if value is None:
        return
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{name} must be timezone-aware: {value!r}")


def date_to_utc_midnight(value: date) -> datetime:
    return datetime.combine(value, time(0, 0), tzinfo=timezone.utc)


def vintage_available_time(realtime_start: date) -> datetime:
    """The never-too-early `available_time` for a value FRED first
    published on `realtime_start` -- see the module docstring."""
    return date_to_utc_midnight(realtime_start) + VINTAGE_AVAILABILITY_OFFSET


def macro_record_id(source: str, series_id: str, observation_date: date, realtime_start: date) -> str:
    return f"{source}:{series_id}:{observation_date.isoformat()}:{realtime_start.isoformat()}"


@dataclass(frozen=True)
class MacroObservationRecord:
    """One vintage of one macro observation. `value is None` means FRED
    published "." (no value) for that date in that vintage -- stored, not
    dropped, so a later "value withdrawn" vintage is not mistaken for the
    earlier value still standing."""

    series_id: str
    observation_date: datetime
    value: Optional[float]
    realtime_start: datetime
    realtime_end: Optional[datetime]
    available_time: datetime
    ingestion_time: datetime
    provenance: Provenance

    def __post_init__(self) -> None:
        for name, value in (
            ("observation_date", self.observation_date),
            ("realtime_start", self.realtime_start),
            ("realtime_end", self.realtime_end),
            ("available_time", self.available_time),
            ("ingestion_time", self.ingestion_time),
        ):
            _require_aware(f"MacroObservationRecord.{name}", value)
        if not self.series_id:
            raise ValueError("MacroObservationRecord.series_id must not be empty")
        if self.value is not None and not math.isfinite(self.value):
            raise ValueError(f"MacroObservationRecord.value must be finite or None, got {self.value!r}")
        if self.realtime_end is not None and self.realtime_end < self.realtime_start:
            raise ValueError("MacroObservationRecord.realtime_end must not be before realtime_start")
        if self.available_time < self.realtime_start:
            raise ValueError(
                "MacroObservationRecord.available_time must not be earlier than realtime_start "
                "(a vintage cannot be known before FRED published it)"
            )
