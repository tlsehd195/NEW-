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
    # Session 36 (ADR-0045): the user, asked whether this project's own
    # CANDIDATE evidence level should be a hard prerequisite for Live
    # activation, delegated to the recommendation that it should --
    # motivated directly by a real observed case (leverage reached
    # CANDIDATE with a -26.43% held-out TEST result, the worst this
    # project has recorded) proving CANDIDATE alone is not a safe signal
    # to skip past. This attestation is the same kind of structural
    # human-checkpoint `checklist_completed` already is (a boolean this
    # project cannot verify computationally, enforced the same way) --
    # it does not, by itself, prove a human actually reviewed the
    # evidence; it makes skipping that review require deliberately lying
    # on this field, not merely forgetting a step.
    strategy_evidence_reviewed: bool

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
        if not self.strategy_evidence_reviewed:
            raise ValueError(
                "LiveActivationApproval.strategy_evidence_reviewed must be True -- the strategy being "
                "activated must have reached at least this project's CANDIDATE evidence level "
                "(strategy_research.evidence.EvidenceLevel) AND a human must have reviewed its "
                "held-out TEST result specifically, not merely its evidence label (ADR-0045; a real "
                "CANDIDATE-graded strategy's TEST result has been this project's own worst on record)"
            )

    def is_valid(self) -> bool:
        """Always `True` once constructed -- `__post_init__` already
        rejected any invalid combination; this method exists so a
        caller can express intent (`approval.is_valid()`) without
        re-deriving the same checks."""
        return True
