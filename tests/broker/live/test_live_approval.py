"""Category: Security / Human Approval Test --
`LiveActivationApproval`'s structural rejection of automated actors and
requirement of a real confirmation phrase."""

from __future__ import annotations

import pytest

from live_helpers import utc

from broker.live.approval import REQUIRED_CONFIRMATION_TOKEN, LiveActivationApproval, approval_to_payload, payload_to_approval


class TestApprovedByMustBeHuman:
    @pytest.mark.parametrize("name", ["AI", "ai", "System", "SYSTEM", "Claude", "claude", ""])
    def test_automated_actor_names_rejected(self, name: str) -> None:
        with pytest.raises(ValueError):
            LiveActivationApproval(
                approved_by=name, approved_at=utc(2024, 1, 2), confirmation_token=REQUIRED_CONFIRMATION_TOKEN,
                checklist_completed=True, strategy_evidence_reviewed=True,
            )

    def test_real_operator_identity_accepted(self) -> None:
        approval = LiveActivationApproval(
            approved_by="jane.doe", approved_at=utc(2024, 1, 2), confirmation_token=REQUIRED_CONFIRMATION_TOKEN,
            checklist_completed=True, strategy_evidence_reviewed=True,
        )
        assert approval.is_valid() is True


class TestConfirmationToken:
    def test_wrong_token_rejected(self) -> None:
        with pytest.raises(ValueError):
            LiveActivationApproval(
                approved_by="jane.doe", approved_at=utc(2024, 1, 2), confirmation_token="wrong phrase",
                checklist_completed=True, strategy_evidence_reviewed=True,
            )

    def test_empty_token_rejected(self) -> None:
        with pytest.raises(ValueError):
            LiveActivationApproval(
                approved_by="jane.doe", approved_at=utc(2024, 1, 2), confirmation_token="",
                checklist_completed=True, strategy_evidence_reviewed=True,
            )


class TestChecklistMustBeCompleted:
    def test_incomplete_checklist_rejected(self) -> None:
        with pytest.raises(ValueError):
            LiveActivationApproval(
                approved_by="jane.doe", approved_at=utc(2024, 1, 2), confirmation_token=REQUIRED_CONFIRMATION_TOKEN,
                checklist_completed=False, strategy_evidence_reviewed=True,
            )


class TestStrategyEvidenceMustBeReviewed:
    """Session 36 (ADR-0045): the strategy being activated must have
    reached this project's CANDIDATE evidence level and had its
    held-out TEST result specifically reviewed by a human, not just its
    evidence label -- motivated by a real observed case where CANDIDATE
    alone came with the worst TEST result this project has recorded."""

    def test_unreviewed_evidence_rejected(self) -> None:
        with pytest.raises(ValueError):
            LiveActivationApproval(
                approved_by="jane.doe", approved_at=utc(2024, 1, 2), confirmation_token=REQUIRED_CONFIRMATION_TOKEN,
                checklist_completed=True, strategy_evidence_reviewed=False,
            )

    def test_reviewed_evidence_accepted(self) -> None:
        approval = LiveActivationApproval(
            approved_by="jane.doe", approved_at=utc(2024, 1, 2), confirmation_token=REQUIRED_CONFIRMATION_TOKEN,
            checklist_completed=True, strategy_evidence_reviewed=True,
        )
        assert approval.is_valid() is True


class TestPayloadRoundTrip:
    """2순위 priority pass (ADR-0197's "no human-approval CLI tool" gap):
    `scripts/grant_live_activation_approval.py` writes/reads a real
    approval via this exact round trip."""

    def test_round_trip_preserves_every_field(self) -> None:
        approval = LiveActivationApproval(
            approved_by="jane.doe", approved_at=utc(2024, 1, 2), confirmation_token=REQUIRED_CONFIRMATION_TOKEN,
            checklist_completed=True, strategy_evidence_reviewed=True,
        )
        reloaded = payload_to_approval(approval_to_payload(approval))
        assert reloaded == approval

    def test_a_tampered_payload_with_checklist_forced_true_but_missing_other_fields_still_fails_validation(self) -> None:
        """The round trip re-runs __post_init__ -- a hand-edited JSON
        file cannot bypass validation just by round-tripping structurally."""
        with pytest.raises(ValueError):
            payload_to_approval({
                "approved_by": "jane.doe", "approved_at": utc(2024, 1, 2).isoformat(),
                "confirmation_token": "wrong phrase", "checklist_completed": True,
                "strategy_evidence_reviewed": True,
            })

    def test_payload_uses_plain_json_serializable_types(self) -> None:
        import json

        approval = LiveActivationApproval(
            approved_by="jane.doe", approved_at=utc(2024, 1, 2), confirmation_token=REQUIRED_CONFIRMATION_TOKEN,
            checklist_completed=True, strategy_evidence_reviewed=True,
        )
        # Must not raise -- every value is a plain JSON type (str/bool).
        json.dumps(approval_to_payload(approval))


class TestTimestampMustBeAware:
    def test_naive_timestamp_rejected(self) -> None:
        from datetime import datetime

        with pytest.raises(ValueError):
            LiveActivationApproval(
                approved_by="jane.doe", approved_at=datetime(2024, 1, 2), confirmation_token=REQUIRED_CONFIRMATION_TOKEN,
                checklist_completed=True, strategy_evidence_reviewed=True,
            )
