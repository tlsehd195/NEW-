"""Category: Unit Test -- `orchestration.live_safety_gate_inputs`
(ADR-0072), the real, spec-faithful (`PHASE-16-live-trading.md` section
5) computations for `model_state_valid`/`configuration_integrity_valid`."""

from __future__ import annotations

from live_helpers import make_live_config
from monitoring_helpers import make_transition

from learning.enums import CandidateModelStatus

from orchestration.live_safety_gate_inputs import (
    compute_configuration_integrity_valid,
    compute_model_state_valid,
)


class TestComputeModelStateValid:
    def test_no_transition_is_not_valid(self) -> None:
        assert compute_model_state_valid(None) is False

    def test_a_passed_transition_to_candidate_is_not_valid(self) -> None:
        transition = make_transition(to_status=CandidateModelStatus.CANDIDATE, passed=True)
        assert compute_model_state_valid(transition) is False

    def test_a_passed_transition_to_backtested_is_not_valid(self) -> None:
        transition = make_transition(to_status=CandidateModelStatus.BACKTESTED, passed=True)
        assert compute_model_state_valid(transition) is False

    def test_a_passed_transition_to_approved_is_valid(self) -> None:
        transition = make_transition(to_status=CandidateModelStatus.APPROVED, passed=True)
        assert compute_model_state_valid(transition) is True

    def test_a_passed_transition_to_deployed_is_valid(self) -> None:
        transition = make_transition(to_status=CandidateModelStatus.DEPLOYED, passed=True)
        assert compute_model_state_valid(transition) is True

    def test_a_failed_transition_to_approved_is_not_valid(self) -> None:
        """A failed attempt never advances the candidate's status
        (ADR-0045's own precedent, restated by this project's own
        `ModelStatusTransitionRepository.get_current_status` docstring)
        -- even if `to_status` names APPROVED, `passed=False` means the
        attempt did not actually succeed."""
        transition = make_transition(to_status=CandidateModelStatus.APPROVED, passed=False)
        assert compute_model_state_valid(transition) is False


class TestComputeConfigurationIntegrityValid:
    def test_matching_pinned_version_is_valid(self) -> None:
        config = make_live_config(live_trading_enabled=True)
        assert compute_configuration_integrity_valid(config, config.configuration_version()) is True

    def test_a_stale_pinned_version_is_not_valid(self) -> None:
        config = make_live_config(live_trading_enabled=True)
        stale_pin = make_live_config(live_trading_enabled=True, max_daily_loss=999.0).configuration_version()
        assert config.configuration_version() != stale_pin  # sanity: the two configs really do differ
        assert compute_configuration_integrity_valid(config, stale_pin) is False
