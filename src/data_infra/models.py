"""Core domain model for the Data Infrastructure layer (Phase 1).

Authoritative reference: docs/specifications/PHASE-1-data-infrastructure.md
sections 5-9, and ADR-0003 (data model), ADR-0004 (point-in-time).

Design notes
------------
- Every timestamp field must be timezone-aware. A naive ``datetime``
  anywhere here is a schema validation failure (raised eagerly in
  ``__post_init__``), per the Phase 1 spec section 10.
- These dataclasses intentionally do NOT enforce OHLC invariants,
  negative-price checks, etc. Those are *data quality* concerns (severity-
  scored, non-fatal to storage) implemented in ``data_infra.quality`` —
  Raw-layer data must remain representable even when it is invalid, so
  that invalid records can be retained and flagged rather than silently
  dropped or made impossible to construct (Phase 1 spec section 17, Raw
  Data Immutability).
- ``Provenance`` is a shared value object composed into every time-series
  record instead of duplicating source/version fields per type (ADR-0003).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from data_infra.enums import (
    BenchmarkReturnType,
    CorporateActionType,
    InstrumentType,
    SecurityStatus,
)


def _require_aware(name: str, value: Optional[datetime]) -> None:
    if value is None:
        return
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(
            f"{name} must be timezone-aware (naive datetimes are a schema "
            f"validation failure per PHASE-1-data-infrastructure.md section 10): {value!r}"
        )


@dataclass(frozen=True)
class Provenance:
    """Where a record came from and which version it is.

    Composed into PriceBar / CorporateAction / BenchmarkPoint rather than
    duplicated per type (ADR-0003).
    """

    source: str
    source_dataset: str
    source_record_id: str
    retrieved_at: datetime
    data_version: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        _require_aware("Provenance.retrieved_at", self.retrieved_at)
        if not self.source or not self.source_dataset or not self.source_record_id:
            raise ValueError("Provenance requires non-empty source, source_dataset, source_record_id")


@dataclass(frozen=True)
class SecurityMaster:
    """Security identity, separated from the bare ticker string.

    security_id is the stable identifier that all time-series data
    references; ticker/exchange/status can change over the security's
    life without invalidating historical references (Phase 1 spec
    section 6).
    """

    security_id: str
    ticker: str
    exchange: str
    currency: str
    company_id: str
    instrument_type: InstrumentType
    valid_from: datetime
    status: SecurityStatus
    valid_to: Optional[datetime] = None

    def __post_init__(self) -> None:
        _require_aware("SecurityMaster.valid_from", self.valid_from)
        _require_aware("SecurityMaster.valid_to", self.valid_to)
        if not self.security_id:
            raise ValueError("SecurityMaster.security_id must not be empty")
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("SecurityMaster.valid_to must be after valid_from")

    def is_valid_at(self, at_time: datetime) -> bool:
        _require_aware("at_time", at_time)
        if at_time < self.valid_from:
            return False
        if self.valid_to is not None and at_time >= self.valid_to:
            return False
        return True


@dataclass(frozen=True)
class PriceBar:
    """A single OHLCV bar. See Phase 1 spec section 5 for field semantics,
    especially section 5.2 for what ``adjusted_close`` does and does not
    mean -- the same "raw is truth, adjusted is a separate optional view,
    never substituted" discipline applies identically to
    ``adjusted_high``/``adjusted_low`` below."""

    security_id: str
    timestamp: datetime  # start of the bar's period, per spec section 10
    open: float
    high: float
    low: float
    close: float
    volume: float
    available_time: datetime
    ingestion_time: datetime
    provenance: Provenance
    adjusted_close: Optional[float] = None
    # Session 36 continued addition -- needed to correctly implement a
    # Corwin & Schultz (2012) high-low bid-ask spread estimator
    # (`strategy_research.factor_scores.bid_ask_spread_score`), whose own
    # 2-day "gamma" term cross-compares one day's high/low against the
    # NEXT day's -- if either day's raw high/low straddled an
    # unadjusted stock split, that comparison mixes two different price
    # scales and produces a spurious, wildly wrong estimate. `close` has
    # always had this same "raw vs. adjusted" split via `adjusted_close`;
    # `high`/`low` never did, since no earlier factor in this module
    # needed a cross-day comparison of price LEVELS (only of returns,
    # for which `adjusted_close` already suffices). Optional and never
    # fabricated -- `None` for any provider that does not supply it
    # (e.g. `StooqDataProvider`, which supplies raw prices only).
    adjusted_high: Optional[float] = None
    adjusted_low: Optional[float] = None
    vwap: Optional[float] = None
    trade_count: Optional[int] = None
    currency: Optional[str] = None
    exchange: Optional[str] = None
    event_time: Optional[datetime] = None
    publication_time: Optional[datetime] = None

    def __post_init__(self) -> None:
        for name, value in (
            ("timestamp", self.timestamp),
            ("available_time", self.available_time),
            ("ingestion_time", self.ingestion_time),
            ("event_time", self.event_time),
            ("publication_time", self.publication_time),
        ):
            _require_aware(f"PriceBar.{name}", value)
        if not self.security_id:
            raise ValueError("PriceBar.security_id must not be empty")
        if self.publication_time is not None and self.available_time < self.publication_time:
            # ADR-0004: available_time must never be set earlier than publication_time.
            raise ValueError(
                "PriceBar.available_time must not be earlier than publication_time "
                "(ADR-0004 point-in-time ordering constraint)"
            )


@dataclass(frozen=True)
class CorporateAction:
    """One corporate action event. See Phase 1 spec section 7 for the four
    distinguished timestamps."""

    security_id: str
    action_type: CorporateActionType
    available_time: datetime
    ingestion_time: datetime
    provenance: Provenance
    event_time: Optional[datetime] = None
    announcement_time: Optional[datetime] = None
    effective_time: Optional[datetime] = None
    # Event-specific payload (e.g. {"ratio": "2:1"} for SPLIT,
    # {"amount": 0.24, "currency": "USD"} for DIVIDEND). Kept generic in
    # Phase 1 rather than one field per event type, since only SPLIT and
    # DIVIDEND are populated in the mock dataset (data-catalog.md) and a
    # rigid per-type schema is not yet justified by a concrete need.
    details: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name, value in (
            ("available_time", self.available_time),
            ("ingestion_time", self.ingestion_time),
            ("event_time", self.event_time),
            ("announcement_time", self.announcement_time),
            ("effective_time", self.effective_time),
        ):
            _require_aware(f"CorporateAction.{name}", value)
        if not self.security_id:
            raise ValueError("CorporateAction.security_id must not be empty")


@dataclass(frozen=True)
class BenchmarkPoint:
    """A single benchmark index level observation.

    ``return_type`` must always be set explicitly — never assume a
    benchmark series is total-return or price-return without checking
    (Phase 1 spec section 5.2 / data-catalog.md)."""

    benchmark_id: str
    timestamp: datetime
    level: float
    return_type: BenchmarkReturnType
    currency: str
    available_time: datetime
    ingestion_time: datetime
    provenance: Provenance

    def __post_init__(self) -> None:
        for name, value in (
            ("timestamp", self.timestamp),
            ("available_time", self.available_time),
            ("ingestion_time", self.ingestion_time),
        ):
            _require_aware(f"BenchmarkPoint.{name}", value)
        if not self.benchmark_id:
            raise ValueError("BenchmarkPoint.benchmark_id must not be empty")


@dataclass(frozen=True)
class UniverseMembership:
    """A (security, universe) membership interval, used to support
    survivorship-bias-free historical universe queries (Phase 1 spec
    section 8)."""

    security_id: str
    universe: str
    valid_from: datetime
    valid_to: Optional[datetime] = None

    def __post_init__(self) -> None:
        _require_aware("UniverseMembership.valid_from", self.valid_from)
        _require_aware("UniverseMembership.valid_to", self.valid_to)
        if not self.security_id or not self.universe:
            raise ValueError("UniverseMembership requires non-empty security_id and universe")
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("UniverseMembership.valid_to must be after valid_from")

    def is_member_at(self, at_time: datetime) -> bool:
        _require_aware("at_time", at_time)
        if at_time < self.valid_from:
            return False
        if self.valid_to is not None and at_time >= self.valid_to:
            return False
        return True
