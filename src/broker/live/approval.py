"""LiveActivationApproval: the human-sourced token
`broker.live.safety_gate.evaluate_safety_gate` requires alongside
`LiveTradingConfig.live_trading_enabled`. Nothing in this codebase's
deterministic pipeline (`decision.*`/`risk.*`/`broker.live.session`/
`monitoring.*`) constructs one -- the only constructors anywhere in
`src/` or `tests/` are this module's own tests
(`tests/broker/live/test_live_approval.py`), verified by an AST scan
across the whole repository
(`tests/broker/live/test_live_boundary.py::TestActivationApprovalIsHumanOnly`).

See docs/specifications/PHASE-16-live-trading.md section 4, 39.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

# A fixed, non-secret literal the operator must type verbatim as part of
# a documented manual procedure (docs/operations/LIVE-TRADING-RUNBOOK.md)
# -- not a credential, just a deliberate extra step against an
# accidental/scripted True.
REQUIRED_CONFIRMATION_TOKEN = "I CONFIRM LIVE TRADING ACTIVATION"


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{name} must be timezone-aware: {value!r}")


@dataclass(frozen=True)
class LiveActivationApproval:
    approved_by: str  # operator identity -- never "AI"/"SYSTEM"/empty
    approved_at: datetime
    confirmation_token: str
    checklist_completed: bool

    def __post_init__(self) -> None:
        if not self.approved_by or self.approved_by.strip().upper() in ("AI", "SYSTEM", "CLAUDE"):
            raise ValueError(
                "LiveActivationApproval.approved_by must be a real, non-empty operator identity, "
                "never a value naming an automated actor"
            )
        _require_aware("LiveActivationApproval.approved_at", self.approved_at)
        if self.confirmation_token != REQUIRED_CONFIRMATION_TOKEN:
            raise ValueError("LiveActivationApproval.confirmation_token does not match the required phrase")
        if not self.checklist_completed:
            raise ValueError("LiveActivationApproval.checklist_completed must be True")

    def is_valid(self) -> bool:
        """Always `True` once constructed -- `__post_init__` already
        rejected any invalid combination; this method exists so a
        caller can express intent (`approval.is_valid()`) without
        re-deriving the same checks."""
        return True
