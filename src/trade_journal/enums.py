"""Enumerations for the Trade Journal (Phase 3).

See docs/specifications/PHASE-3-trade-journal.md.
"""

from __future__ import annotations

from enum import Enum


class TradeProvenance(str, Enum):
    """Never mixed silently — PROJECT_MASTER_PLAN.md section 36."""

    HISTORICAL_SIMULATION = "HISTORICAL_SIMULATION"
    PAPER_TRADING = "PAPER_TRADING"
    LIVE_TRADING = "LIVE_TRADING"


class DecisionAction(str, Enum):
    """Mirrors PROJECT_MASTER_PLAN.md section 22 in full. Phase 2's
    Strategy interface only ever produces BUY/SELL today; HOLD/EXIT/
    NO_TRADE are reserved for Phase 7's Decision Agent (Phase 3 spec
    section 5.4)."""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    EXIT = "EXIT"
    NO_TRADE = "NO_TRADE"


class CorrectionTargetType(str, Enum):
    DECISION = "DECISION"
    TRADE = "TRADE"
