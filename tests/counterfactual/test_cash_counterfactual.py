"""Unit tests for counterfactual.counterfactual.compute_cash_counterfactual.

See docs/specifications/PHASE-10-counterfactual-attribution.md section 3.2.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from counterfactual_helpers import utc

from counterfactual.counterfactual import compute_cash_counterfactual


class TestCashCounterfactual:
    def test_zero_rate_default_yields_zero_return(self) -> None:
        outcome = compute_cash_counterfactual(utc(2024, 1, 2), utc(2024, 1, 9))
        assert outcome.action == "CASH"
        assert outcome.hypothetical_return == 0.0
        assert outcome.basis == "cash_baseline_zero_rate"

    def test_horizon_matches_the_requested_window(self) -> None:
        outcome = compute_cash_counterfactual(utc(2024, 1, 2), utc(2024, 1, 9))
        assert outcome.horizon == timedelta(days=7)

    def test_nonzero_rate_is_a_real_annualized_computation_not_fabricated(self) -> None:
        one_year = compute_cash_counterfactual(utc(2024, 1, 1), utc(2025, 1, 1), risk_free_rate=0.05)
        assert one_year.hypothetical_return == pytest.approx(0.05, abs=1e-3)
        assert one_year.basis == "cash_baseline_explicit_rate"

    def test_nonzero_rate_scales_with_horizon(self) -> None:
        half_year = compute_cash_counterfactual(utc(2024, 1, 1), utc(2024, 7, 2), risk_free_rate=0.05)
        assert half_year.hypothetical_return == pytest.approx(0.025, abs=2e-3)

    def test_rejects_evaluation_time_before_decision_time(self) -> None:
        with pytest.raises(ValueError):
            compute_cash_counterfactual(utc(2024, 1, 9), utc(2024, 1, 2))

    def test_zero_horizon_yields_zero_return(self) -> None:
        outcome = compute_cash_counterfactual(utc(2024, 1, 2), utc(2024, 1, 2), risk_free_rate=0.05)
        assert outcome.hypothetical_return == 0.0

    def test_makes_no_data_repository_call(self) -> None:
        """Documented in the spec (section 5): CASH needs no market data
        at all. A direct proof: calling it with no repository argument in
        the signature at all is itself the guarantee -- this test pins
        that the function signature has no repository/DataRepository
        parameter, so it can never be given one to (mis)use."""
        import inspect

        params = inspect.signature(compute_cash_counterfactual).parameters
        assert "repository" not in params
        assert "data_repository" not in params
