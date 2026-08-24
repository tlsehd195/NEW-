"""Enumerations shared across the Phase 1 data infrastructure domain model.

See docs/specifications/PHASE-1-data-infrastructure.md for the meaning of
each value; this module intentionally carries no behavior beyond the
enums themselves.
"""

from __future__ import annotations

from enum import Enum


class InstrumentType(str, Enum):
    """Phase 1 only populates EQUITY. Other types are reserved for future
    phases and are intentionally not modeled yet (no design decision
    requires them — PROJECT_MASTER_PLAN.md section 17.3)."""

    EQUITY = "EQUITY"


class SecurityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DELISTED = "DELISTED"
    RENAMED = "RENAMED"
    MERGED = "MERGED"


class CorporateActionType(str, Enum):
    SPLIT = "SPLIT"
    REVERSE_SPLIT = "REVERSE_SPLIT"
    DIVIDEND = "DIVIDEND"
    SPECIAL_DIVIDEND = "SPECIAL_DIVIDEND"
    MERGER = "MERGER"
    ACQUISITION = "ACQUISITION"
    SPIN_OFF = "SPIN_OFF"
    TICKER_CHANGE = "TICKER_CHANGE"
    DELISTING = "DELISTING"


class BenchmarkReturnType(str, Enum):
    """Whether a BenchmarkPoint series is a price-return or total-return
    (dividends reinvested) series. Must always be explicit — see
    PHASE-1-data-infrastructure.md section 5.2 / data-catalog.md for why
    this cannot be left implicit."""

    PRICE_RETURN = "PRICE_RETURN"
    TOTAL_RETURN = "TOTAL_RETURN"


class DataLifecycleState(str, Enum):
    DISCOVERED = "DISCOVERED"
    INGESTED = "INGESTED"
    VALIDATED = "VALIDATED"
    NORMALIZED = "NORMALIZED"
    STORED = "STORED"
    AVAILABLE = "AVAILABLE"
    DERIVED = "DERIVED"
    CONSUMED = "CONSUMED"
    # Error states
    INGESTION_FAILED = "INGESTION_FAILED"
    QUALITY_REJECTED = "QUALITY_REJECTED"
    QUALITY_FLAGGED = "QUALITY_FLAGGED"
    SUPERSEDED = "SUPERSEDED"


class DataQualitySeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class DataQualityRunStatus(str, Enum):
    PASSED = "PASSED"
    PASSED_WITH_WARNINGS = "PASSED_WITH_WARNINGS"
    FAILED = "FAILED"
    CRITICAL_FAILURE = "CRITICAL_FAILURE"


class IngestionStatus(str, Enum):
    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    FAILED = "FAILED"
