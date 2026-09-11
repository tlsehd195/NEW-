"""Unit tests for trade_journal.analysis — the concrete Post Trade
Analysis / Counterfactual / Attribution computations Phase 3 actually
performs (see docs/specifications/PHASE-3-trade-journal.md sections 7,
5.7).
"""

from __future__ import annotations

from datetime import date

import pytest
from journal_helpers import make_fill, utc

from data_infra.calendar import US_EQUITY
from data_infra.enums import InstrumentType, SecurityStatus
from data_infra.models import PriceBar, Provenance, SecurityMaster
from data_infra.repository import InMemoryDataRepository

from trade_journal.analysis import (
    compute_execution_attribution,
    compute_execution_error,
    compute_hold_counterfactual,
)


class TestExecutionError:
    def test_matches_hand_computation(self) -> None:
        fill = make_fill(price=101.0, reference_price=100.0)
        assert compute_execution_error(fill) == pytest.approx(0.01)

    def test_negative_when_price_is_better_than_reference(self) -> None:
        fill = make_fill(price=99.0, reference_price=100.0)
        assert compute_execution_error(fill) == pytest.approx(-0.01)

    def test_zero_reference_price_is_none_not_a_fabricated_zero(self) -> None:
        # ADR-0117: a 0 reference_price makes the ratio genuinely
        # undefined -- returning 0.0 (the previous behavior) fabricated
        # "no execution error" instead of "cannot be computed",
        # contradicting this module's own stated "never estimate a
        # value and present it as fact" discipline.
        fill = make_fill(price=0.0, reference_price=0.0)
        assert compute_execution_error(fill) is None


def _repo_with_bars(closes: dict[date, float]) -> InMemoryDataRepository:
    bars = []
    for i, (d, close) in enumerate(sorted(closes.items())):
        bars.append(
            PriceBar(
                security_id="AAA", timestamp=utc(d.year, d.month, d.day, 0), open=close, high=close * 1.01,
                low=close * 0.99, close=close, volume=100_000.0,
                available_time=utc(d.year, d.month, d.day, 20), ingestion_time=utc(d.year, d.month, d.day, 20),
                provenance=Provenance(source="test", source_dataset="test_ds", source_record_id=f"aaa-{i}",
                                       retrieved_at=utc(d.year, d.month, d.day, 20), data_version=f"v{i}"),
            )
        )
    sec = SecurityMaster(security_id="AAA", ticker="AAA", exchange="NASDAQ", currency="USD",
                          company_id="C1", instrument_type=InstrumentType.EQUITY,
                          valid_from=utc(2020, 1, 1), status=SecurityStatus.ACTIVE)
    return InMemoryDataRepository(bars=bars, securities=[sec], calendars={"US_EQUITY": US_EQUITY})


class TestHoldCounterfactual:
    def test_matches_hand_computation(self) -> None:
        repo = _repo_with_bars({date(2024, 1, 2): 100.0, date(2024, 1, 9): 110.0})
        outcome = compute_hold_counterfactual(
            repo, "AAA", decision_time=utc(2024, 1, 2, 20), evaluation_time=utc(2024, 1, 9, 20),
        )
        assert outcome.action == "HOLD"
        assert outcome.hypothetical_return == pytest.approx(0.10)
        assert outcome.basis == "post_hoc_price_replay"

    def test_insufficient_data_does_not_fabricate_a_return(self) -> None:
        repo = InMemoryDataRepository(calendars={"US_EQUITY": US_EQUITY})  # no bars at all
        outcome = compute_hold_counterfactual(
            repo, "AAA", decision_time=utc(2024, 1, 2, 20), evaluation_time=utc(2024, 1, 9, 20),
        )
        assert outcome.hypothetical_return is None
        assert outcome.basis == "insufficient_data"

    def test_rejects_evaluation_time_before_decision_time(self) -> None:
        repo = _repo_with_bars({date(2024, 1, 2): 100.0})
        with pytest.raises(ValueError):
            compute_hold_counterfactual(
                repo, "AAA", decision_time=utc(2024, 1, 9, 20), evaluation_time=utc(2024, 1, 2, 20),
            )

    def test_horizon_matches_the_requested_window(self) -> None:
        from datetime import timedelta

        repo = _repo_with_bars({date(2024, 1, 2): 100.0, date(2024, 1, 9): 100.0})
        outcome = compute_hold_counterfactual(
            repo, "AAA", decision_time=utc(2024, 1, 2, 20), evaluation_time=utc(2024, 1, 9, 20),
        )
        assert outcome.horizon == timedelta(days=7)


class TestExecutionAttribution:
    def test_matches_hand_computation(self) -> None:
        assert compute_execution_attribution(transaction_costs=500.0, initial_capital=50_000.0) == pytest.approx(-0.01)

    def test_zero_initial_capital_does_not_crash(self) -> None:
        assert compute_execution_attribution(transaction_costs=500.0, initial_capital=0.0) == 0.0

    def test_zero_cost_yields_zero_drag(self) -> None:
        assert compute_execution_attribution(transaction_costs=0.0, initial_capital=50_000.0) == 0.0
