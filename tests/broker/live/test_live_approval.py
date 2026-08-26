"""Category: Security / Human Approval Test --
`LiveActivationApproval`'s structural rejection of automated actors and
requirement of a real confirmation phrase."""

from __future__ import annotations

import pytest

from live_helpers import utc

from broker.live.approval import REQUIRED_CONFIRMATION_TOKEN, LiveActivationApproval


class TestApprovedByMustBeHuman:
    @pytest.mark.parametrize("name", ["AI", "ai", "System", "SYSTEM", "Claude", "claude", ""])
    def test_automated_actor_names_rejected(self, name: str) -> None:
        with pytest.raises(ValueError):
            LiveActivationApproval(
                approved_by=name, approved_at=utc(2024, 1, 2), confirmation_token=REQUIRED_CONFIRMATION_TOKEN,
                checklist_completed=True,
            )

    def test_real_operator_identity_accepted(self) -> None:
        approval = LiveActivationApproval(
            approved_by="jane.doe", approved_at=utc(2024, 1, 2), confirmation_token=REQUIRED_CONFIRMATION_TOKEN,
            checklist_completed=True,
        )
        assert approval.is_valid() is True


class TestConfirmationToken:
    def test_wrong_token_rejected(self) -> None:
        with pytest.raises(ValueError):
            LiveActivationApproval(
                approved_by="jane.doe", approved_at=utc(2024, 1, 2), confirmation_token="wrong phrase",
                checklist_completed=True,
            )

    def test_empty_token_rejected(self) -> None:
        with pytest.raises(ValueError):
            LiveActivationApproval(
                approved_by="jane.doe", approved_at=utc(2024, 1, 2), confirmation_token="",
                checklist_completed=True,
            )


class TestChecklistMustBeCompleted:
    def test_incomplete_checklist_rejected(self) -> None:
        with pytest.raises(ValueError):
            LiveActivationApproval(
                approved_by="jane.doe", approved_at=utc(2024, 1, 2), confirmation_token=REQUIRED_CONFIRMATION_TOKEN,
                checklist_completed=False,
            )


class TestTimestampMustBeAware:
    def test_naive_timestamp_rejected(self) -> None:
        from datetime import datetime

        with pytest.raises(ValueError):
            LiveActivationApproval(
                approved_by="jane.doe", approved_at=datetime(2024, 1, 2), confirmation_token=REQUIRED_CONFIRMATION_TOKEN,
                checklist_completed=True,
            )
