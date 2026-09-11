"""Category: Repository Test -- InMemoryPositionSizingRepository/
InMemoryRiskRepository .get_as_of tie-break determinism (ADR-0117)."""

from __future__ import annotations

from datetime import datetime, timezone

from risk.enums import RiskCheckStatus
from risk.models import PositionSizingResult, RiskCheckedPosition
from risk.repository import InMemoryPositionSizingRepository, InMemoryRiskRepository

from trade_journal.enums import DecisionAction


def utc(year: int, month: int, day: int, hour: int = 20) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


def _sizing_result(as_of_time: datetime, *, sizing_id: str, decision_id: str) -> PositionSizingResult:
    return PositionSizingResult(
        sizing_id=sizing_id, security_id="AAA", as_of_time=as_of_time, status=RiskCheckStatus.PASS,
        reason="normal_sizing", decision_id=decision_id, decision_action=DecisionAction.BUY,
        proposed_target_weight=0.1, proposed_target_quantity=50.0, current_weight=0.0, current_quantity=0.0,
        sizing_version="sizer-v1", feature_version="feat-v1",
    )


def _risk_checked(as_of_time: datetime, *, risk_id: str, sizing_id: str) -> RiskCheckedPosition:
    return RiskCheckedPosition(
        risk_id=risk_id, security_id="AAA", as_of_time=as_of_time, status=RiskCheckStatus.PASS,
        reason="normal_sizing", breached_limits=(), final_target_weight=0.1, final_target_quantity=50.0,
        sizing_id=sizing_id, decision_id="DEC-OUT-000001", prediction_id=None,
        risk_state=None, risk_version="risk-v1", feature_version="feat-v1",
    )


class TestPositionSizingGetAsOfTieBreak:
    def test_a_genuine_as_of_time_tie_deterministically_prefers_the_higher_sizing_id(self) -> None:
        # Two sizing results for different decisions, same as_of_time (a
        # different decision_id so the natural-key dedup doesn't
        # collapse them into one row) -- `max(..., key=as_of_time)`
        # alone resolved a tie by dict insertion order.
        T = utc(2024, 6, 1)
        repo = InMemoryPositionSizingRepository()
        repo.record(_sizing_result(T, sizing_id="SIZE-000001", decision_id="DEC-OUT-000001"))
        repo.record(_sizing_result(T, sizing_id="SIZE-000002", decision_id="DEC-OUT-000002"))

        result = repo.get_as_of("AAA", T)
        assert result is not None
        assert result.sizing_id == "SIZE-000002"

    def test_tie_break_is_independent_of_insertion_order(self) -> None:
        T = utc(2024, 6, 1)
        repo = InMemoryPositionSizingRepository()
        repo.record(_sizing_result(T, sizing_id="SIZE-000002", decision_id="DEC-OUT-000002"))
        repo.record(_sizing_result(T, sizing_id="SIZE-000001", decision_id="DEC-OUT-000001"))

        result = repo.get_as_of("AAA", T)
        assert result is not None
        assert result.sizing_id == "SIZE-000002"


class TestRiskCheckedGetAsOfTieBreak:
    def test_a_genuine_as_of_time_tie_deterministically_prefers_the_higher_risk_id(self) -> None:
        T = utc(2024, 6, 1)
        repo = InMemoryRiskRepository()
        repo.record(_risk_checked(T, risk_id="RISK-000001", sizing_id="SIZE-000001"))
        repo.record(_risk_checked(T, risk_id="RISK-000002", sizing_id="SIZE-000002"))

        result = repo.get_as_of("AAA", T)
        assert result is not None
        assert result.risk_id == "RISK-000002"

    def test_tie_break_is_independent_of_insertion_order(self) -> None:
        T = utc(2024, 6, 1)
        repo = InMemoryRiskRepository()
        repo.record(_risk_checked(T, risk_id="RISK-000002", sizing_id="SIZE-000002"))
        repo.record(_risk_checked(T, risk_id="RISK-000001", sizing_id="SIZE-000001"))

        result = repo.get_as_of("AAA", T)
        assert result is not None
        assert result.risk_id == "RISK-000002"
