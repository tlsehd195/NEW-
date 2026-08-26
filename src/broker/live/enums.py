"""Enumerations for Live Trading (Phase 16).

See docs/specifications/PHASE-16-live-trading.md sections 5, 7, 8, 14.
"""

from __future__ import annotations

from enum import Enum


class OperationalState(str, Enum):
    """Instruction section 42's required state vocabulary. Transitions
    are tracked by `LiveTradingSession` and are always audit-logged
    (`broker.live.session`) -- never a bare in-memory flag."""

    OFF = "OFF"
    ARMED = "ARMED"  # config + approval present, gate not yet evaluated this session
    READY = "READY"  # gate passed, no order submitted yet
    ACTIVE = "ACTIVE"  # at least one order submitted and no blocking condition since
    HALTED = "HALTED"  # kill switch engaged or a critical trigger fired
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    BROKER_UNKNOWN = "BROKER_UNKNOWN"
    ACCOUNT_UNKNOWN = "ACCOUNT_UNKNOWN"
    POSITION_UNKNOWN = "POSITION_UNKNOWN"
    KILL_SWITCHED = "KILL_SWITCHED"
    SHUTTING_DOWN = "SHUTTING_DOWN"


class ReconciliationStatus(str, Enum):
    """`UNKNOWN` whenever either side's state is itself unavailable --
    never coerced to `MATCHED` (instruction section 12, 16, 18)."""

    MATCHED = "MATCHED"
    MISMATCH = "MISMATCH"
    UNKNOWN = "UNKNOWN"
