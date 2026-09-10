"""Session 36 continued tests for `orchestration.paper_strategies`
(ADR-0110) -- the strategy registry `scripts/run_paper_trading_cycle.py`
now builds its one "baseline_rule" configuration through, and
`scripts/run_multi_strategy_paper_trading_cycle.py` uses to run more
than one strategy at once."""

from __future__ import annotations

import pytest

from orchestration.paper_strategies import (
    STRATEGIES,
    PaperStrategyKind,
    RunCycleStartingIds,
    build_run_cycle_components,
)

from predict.predictor import DriftPredictor, RandomWalkPredictor

from risk.config import RiskConfig


class TestRegistryContents:
    def test_all_three_expected_names_present(self) -> None:
        assert set(STRATEGIES) == {"baseline_rule", "random_walk_baseline", "buy_and_hold"}

    def test_baseline_rule_and_random_walk_baseline_are_run_cycle_kind(self) -> None:
        assert STRATEGIES["baseline_rule"].kind == PaperStrategyKind.RUN_CYCLE
        assert STRATEGIES["random_walk_baseline"].kind == PaperStrategyKind.RUN_CYCLE

    def test_buy_and_hold_is_buy_and_hold_kind(self) -> None:
        assert STRATEGIES["buy_and_hold"].kind == PaperStrategyKind.BUY_AND_HOLD

    def test_every_spec_name_matches_its_own_registry_key(self) -> None:
        for key, spec in STRATEGIES.items():
            assert spec.name == key


class TestBuildRunCycleComponents:
    def test_baseline_rule_uses_drift_predictor(self) -> None:
        components = build_run_cycle_components("baseline_rule", risk_config=RiskConfig())
        assert isinstance(components["predictor"], DriftPredictor)

    def test_random_walk_baseline_uses_random_walk_predictor(self) -> None:
        components = build_run_cycle_components("random_walk_baseline", risk_config=RiskConfig())
        assert isinstance(components["predictor"], RandomWalkPredictor)

    def test_returns_exactly_the_five_run_cycle_component_keys(self) -> None:
        components = build_run_cycle_components("baseline_rule", risk_config=RiskConfig())
        assert set(components) == {"predictor", "regime_detector", "decision_agent", "position_sizer", "risk_engine"}

    def test_unregistered_name_raises_key_error(self) -> None:
        with pytest.raises(KeyError):
            build_run_cycle_components("no_such_strategy", risk_config=RiskConfig())

    def test_buy_and_hold_name_raises_key_error(self) -> None:
        """buy_and_hold is BUY_AND_HOLD-kind, not RUN_CYCLE -- it has no
        predictor/decision_agent at all, so asking this function to
        build RUN_CYCLE components for it must fail closed, never
        silently return something else."""
        with pytest.raises(KeyError):
            build_run_cycle_components("buy_and_hold", risk_config=RiskConfig())

    def test_starting_ids_are_respected_and_independent_per_component(self) -> None:
        ids = RunCycleStartingIds(prediction=100, observation=200, composite=300, decision=400, sizing=500, risk=600)
        components = build_run_cycle_components("baseline_rule", risk_config=RiskConfig(), starting_ids=ids)
        assert components["predictor"]._ids.allocate() == "PRED-000100"
        assert components["decision_agent"]._ids.allocate() == "DEC-OUT-000400"

    def test_default_starting_ids_all_start_at_one(self) -> None:
        components = build_run_cycle_components("baseline_rule", risk_config=RiskConfig())
        assert components["predictor"]._ids.allocate() == "PRED-000001"
