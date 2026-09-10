"""Short interest data model (Session 36 continued) -- FINRA Rule 4560
equity short-interest reporting, parallel in spirit to
`data_infra.insider_models.InsiderTransaction` but for a security's
aggregate reported short position rather than one insider's own trade.

**The same point-in-time pitfall `InsiderTransaction`/`FundamentalRecord`
exist to prevent, restated for this data**: a report's `settlement_date`
(the date short positions are AS OF) is NOT when that fact became
public. FINRA Rule 4560 requires member firms to report by the second
business day after the settlement date, and -- per FINRA's own current
published schedule -- FINRA disseminates the AGGREGATE short-interest
figures publicly 7 BUSINESS DAYS after the settlement date, never
sooner. `available_time` is therefore never `settlement_date` itself;
see `SHORT_INTEREST_DISSEMINATION_LAG_DAYS` below for exactly how it is
derived.

**Why this project does not parse FINRA's own real bulk-file format
directly, mirroring `data_infra.providers.file_import.LocalFileDataProvider`'s
own stated reasoning verbatim**: this sandboxed session's outbound
network is blocked to `finra.org` (confirmed this session, the same
class of blocker every real market-data/fundamentals/insider-transaction
provider integrated so far has hit), so this project has never seen a
real FINRA short-interest file and has not independently verified its
exact column layout, delimiter, or header conventions from a live
sample -- only secondary descriptions of the field names FINRA
publishes. Guessing that exact byte-level format with false confidence
would violate this project's "never fabricate provider capabilities"
discipline the same way `LocalFileDataProvider`'s own docstring already
refuses to guess a CRSP/Nasdaq Data Link bulk-file layout it has never
seen. This module instead defines ONE simple, explicit, project-owned
schema (`data_infra.providers.short_interest_file_import`'s
`_REQUIRED_COLUMNS`) that a user's own external preprocessing step
(reshaping whatever FINRA's real file actually contains, in an
environment that CAN reach finra.org) is responsible for producing --
the identical division of responsibility `file_import.py` already
established for real market-data acquisition."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from data_infra.models import Provenance

# FINRA's own currently-published schedule: firms report by the 2nd
# business day after settlement; FINRA disseminates the aggregate
# short-interest figures publicly 7 BUSINESS days after settlement date
# (verified via FINRA's own public rule-filing materials, Session 36
# continued web research -- this session cannot fetch finra.org
# directly to re-verify at ingestion time, so this constant is the one
# place that fact is recorded). Converted to a CONSERVATIVE calendar-day
# upper bound (11, not 7*7/5=9.8) rather than exact business-day
# arithmetic: 7 business days spans at most 2 weekends (worst case, a
# settlement date landing on a Friday), i.e. at most 11 calendar days --
# using this fixed upper bound guarantees `available_time` is NEVER
# earlier than the true public dissemination time (the only direction
# of error a point-in-time guard must never make), at the cost of being
# up to a few calendar days more conservative than necessary on other
# settlement-date weekdays. A real trading-calendar business-day
# calculator was deliberately not built for this one lag computation --
# out of proportion to what a single conservative constant already
# achieves safely.
SHORT_INTEREST_DISSEMINATION_LAG_DAYS = 11


def _require_aware(name: str, value: Optional[datetime]) -> None:
    if value is None:
        return
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{name} must be timezone-aware: {value!r}")


def dissemination_available_time(settlement_date: datetime) -> datetime:
    """The conservative, never-too-early `available_time` for a short
    interest report with this `settlement_date` -- see module docstring
    and `SHORT_INTEREST_DISSEMINATION_LAG_DAYS` for the reasoning."""
    _require_aware("settlement_date", settlement_date)
    return settlement_date + timedelta(days=SHORT_INTEREST_DISSEMINATION_LAG_DAYS)


@dataclass(frozen=True)
class ShortInterestRecord:
    """One security's aggregate short position as of one settlement
    date. `short_interest_quantity`/`average_daily_volume`/
    `days_to_cover` mirror FINRA's own published field semantics
    (`currentShortPositionQuantity`, `averageDailyVolumeQuantity`,
    `daysToCoverQuantity`) without claiming to reproduce FINRA's own
    exact file schema (see module docstring)."""

    security_id: str
    settlement_date: datetime
    short_interest_quantity: float
    average_daily_volume: Optional[float]
    days_to_cover: Optional[float]
    available_time: datetime
    ingestion_time: datetime
    provenance: Provenance

    def __post_init__(self) -> None:
        for name, value in (
            ("settlement_date", self.settlement_date),
            ("available_time", self.available_time),
            ("ingestion_time", self.ingestion_time),
        ):
            _require_aware(f"ShortInterestRecord.{name}", value)
        if not self.security_id:
            raise ValueError("ShortInterestRecord.security_id must not be empty")
        if self.short_interest_quantity < 0:
            raise ValueError("ShortInterestRecord.short_interest_quantity must not be negative")
        if self.average_daily_volume is not None and self.average_daily_volume < 0:
            raise ValueError("ShortInterestRecord.average_daily_volume must not be negative")
        if self.days_to_cover is not None and self.days_to_cover < 0:
            raise ValueError("ShortInterestRecord.days_to_cover must not be negative")
        if self.available_time < self.settlement_date:
            # A report cannot become public before the date its own
            # figures are as of -- mirrors InsiderTransaction's identical
            # available_time/transaction_date ordering guard.
            raise ValueError(
                "ShortInterestRecord.available_time must not be earlier than settlement_date "
                "(a report cannot become public before the date it is as of)"
            )
