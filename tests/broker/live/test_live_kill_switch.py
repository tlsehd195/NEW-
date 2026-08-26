"""Category: Safety Test -- kill switch trigger evaluation, engage,
and release-requires-approval semantics."""

from __future__ import annotations

import pytest

from live_helpers import make_approval, make_live_config, utc

from broker.live.kill_switch import (
    InMemoryKillSwitchRepository,
    KillSwitchTriggerContext,
    engage_kill_switch,
    evaluate_kill_switch_triggers,
    is_engaged,
    release_kill_switch,
)

from monitoring.enums import ComponentHealthStatus


def _ctx(**overrides):
    defaults = dict(
        as_of_time=utc(2024, 1, 2), broker_health=ComponentHealthStatus.HEALTHY,
        risk_health=ComponentHealthStatus.HEALTHY, monitoring_pipeline_health=ComponentHealthStatus.HEALTHY,
        account_state_known=True, position_state_known=True, daily_loss=None, orders_in_last_hour=None,
        config=make_live_config(),
    )
    defaults.update(overrides)
    return KillSwitchTriggerContext(**defaults)


class TestNoTriggerWhenHealthy:
    def test_fully_healthy_context_triggers_nothing(self) -> None:
        assert evaluate_kill_switch_triggers(_ctx()) is None


class TestEachTriggerIndependently:
    def test_broker_unavailable_triggers(self) -> None:
        reason = evaluate_kill_switch_triggers(_ctx(broker_health=ComponentHealthStatus.UNAVAILABLE))
        assert reason == "broker_health_unavailable"

    def test_broker_unknown_triggers(self) -> None:
        reason = evaluate_kill_switch_triggers(_ctx(broker_health=ComponentHealthStatus.UNKNOWN))
        assert reason == "broker_health_unknown"

    def test_broker_degraded_does_not_trigger(self) -> None:
        """DEGRADED is a warning, not a kill-switch-worthy condition --
        only UNAVAILABLE/UNKNOWN are critical."""
        assert evaluate_kill_switch_triggers(_ctx(broker_health=ComponentHealthStatus.DEGRADED)) is None

    def test_risk_engine_unavailable_triggers(self) -> None:
        reason = evaluate_kill_switch_triggers(_ctx(risk_health=ComponentHealthStatus.UNAVAILABLE))
        assert reason == "risk_health_unavailable"

    def test_monitoring_pipeline_unknown_triggers(self) -> None:
        reason = evaluate_kill_switch_triggers(_ctx(monitoring_pipeline_health=ComponentHealthStatus.UNKNOWN))
        assert reason == "monitoring_pipeline_health_unknown"

    def test_account_state_unknown_triggers(self) -> None:
        assert evaluate_kill_switch_triggers(_ctx(account_state_known=False)) == "account_state_unknown"

    def test_position_state_unknown_triggers(self) -> None:
        assert evaluate_kill_switch_triggers(_ctx(position_state_known=False)) == "position_state_unknown"

    def test_daily_loss_limit_breached_triggers_only_when_configured(self) -> None:
        assert evaluate_kill_switch_triggers(_ctx(daily_loss=1000.0)) is None  # not configured -- no trigger
        reason = evaluate_kill_switch_triggers(
            _ctx(daily_loss=1000.0, config=make_live_config(max_daily_loss=500.0))
        )
        assert reason == "daily_loss_limit_breached"

    def test_daily_loss_below_limit_does_not_trigger(self) -> None:
        reason = evaluate_kill_switch_triggers(
            _ctx(daily_loss=100.0, config=make_live_config(max_daily_loss=500.0))
        )
        assert reason is None

    def test_abnormal_order_frequency_triggers_only_when_configured(self) -> None:
        assert evaluate_kill_switch_triggers(_ctx(orders_in_last_hour=1000)) is None
        reason = evaluate_kill_switch_triggers(
            _ctx(orders_in_last_hour=50, config=make_live_config(max_order_frequency_per_hour=10))
        )
        assert reason == "abnormal_order_frequency"


class TestEngageAndRelease:
    def test_engage_records_system_as_trigger(self) -> None:
        event = engage_kill_switch(event_id="KS1", reason="broker_health_unavailable", occurred_at=utc(2024, 1, 2), configuration_version="cfg-1")
        assert event.engaged is True
        assert event.triggered_by == "SYSTEM"

    def test_release_requires_valid_approval(self) -> None:
        approval = make_approval()
        event = release_kill_switch(event_id="KS2", approval=approval, occurred_at=utc(2024, 1, 3), configuration_version="cfg-1")
        assert event.engaged is False
        assert event.triggered_by == approval.approved_by

    def test_release_cannot_be_called_without_an_approval_argument(self) -> None:
        with pytest.raises(TypeError):
            release_kill_switch(event_id="KS3", occurred_at=utc(2024, 1, 3), configuration_version="cfg-1")  # type: ignore[call-arg]


class TestRepositoryStateDerivation:
    def test_empty_history_is_not_engaged(self) -> None:
        repo = InMemoryKillSwitchRepository()
        assert is_engaged(repo) is False

    def test_engage_then_release_reflects_latest_event(self) -> None:
        repo = InMemoryKillSwitchRepository()
        repo.record(engage_kill_switch(event_id="KS1", reason="x", occurred_at=utc(2024, 1, 2), configuration_version="cfg-1"))
        assert is_engaged(repo) is True

        approval = make_approval()
        repo.record(release_kill_switch(event_id="KS2", approval=approval, occurred_at=utc(2024, 1, 3), configuration_version="cfg-1"))
        assert is_engaged(repo) is False

    def test_history_is_append_only_and_idempotent(self) -> None:
        repo = InMemoryKillSwitchRepository()
        event = engage_kill_switch(event_id="KS1", reason="x", occurred_at=utc(2024, 1, 2), configuration_version="cfg-1")
        repo.record(event)
        repo.record(event)
        assert len(repo.list_all()) == 1

    def test_re_engaging_after_release_is_reflected(self) -> None:
        repo = InMemoryKillSwitchRepository()
        repo.record(engage_kill_switch(event_id="KS1", reason="x", occurred_at=utc(2024, 1, 2), configuration_version="cfg-1"))
        repo.record(release_kill_switch(event_id="KS2", approval=make_approval(), occurred_at=utc(2024, 1, 3), configuration_version="cfg-1"))
        repo.record(engage_kill_switch(event_id="KS3", reason="y", occurred_at=utc(2024, 1, 4), configuration_version="cfg-1"))
        assert is_engaged(repo) is True
        assert len(repo.list_all()) == 3
