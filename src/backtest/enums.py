"""Enumerations shared across the Phase 2 backtesting package.

See docs/specifications/PHASE-2-backtesting.md for meaning; mirrors the
severity/status taxonomy pattern Phase 1's data_infra.enums already
established, for consistency across the codebase.
"""

from __future__ import annotations

from enum import Enum


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    # Structurally reserved, not implemented in Phase 2 — see Phase 2
    # spec section 6.1 and ADR-0006.
    LIMIT = "LIMIT"


class OrderStatus(str, Enum):
    PROPOSED = "PROPOSED"
    REJECTED = "REJECTED"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    # Order was generated on the final decision checkpoint of the
    # backtest window, so there is no future bar to fill it against
    # (Phase 2 spec section 6.2).
    NOT_EXECUTED = "NOT_EXECUTED"
    # Reserved for future async brokers (Paper/Toss, Phase 13+) that have
    # a real cancellation window between order submission and fill.
    # Phase 2's synchronous BacktestBroker never produces this value —
    # added so the Order state machine already matches
    # PROJECT_MASTER_PLAN.md section 26 in full, and so Phase 3's Trade
    # Journal (which must represent every Order status losslessly) does
    # not need a second, broker-specific status enum.
    CANCELLED = "CANCELLED"


class IntegritySeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class IntegrityStatus(str, Enum):
    PASSED = "PASSED"
    PASSED_WITH_WARNINGS = "PASSED_WITH_WARNINGS"
    FAILED = "FAILED"
    CRITICAL_FAILURE = "CRITICAL_FAILURE"


class ExperimentResult(str, Enum):
    PASSED = "PASSED"
    INTEGRITY_FAILED = "INTEGRITY_FAILED"
