"""Category: Task Router Test -- PROJECT_MASTER_PLAN.md section 5.2:
provider/model selection per task tier, priority-ordered, deterministic."""

from __future__ import annotations

from ai_gateway_helpers import make_gateway_config, make_provider_config

from ai_gateway.config import GatewayConfig
from ai_gateway.enums import TaskTier
from ai_gateway.task_router import TaskRouter


class TestCandidatesForTier:
    def test_orders_by_priority_ascending(self) -> None:
        a = make_provider_config("a", priority=2)
        b = make_provider_config("b", priority=0)
        c = make_provider_config("c", priority=1)
        router = TaskRouter(make_gateway_config(a, b, c))
        ordered = router.candidates_for(TaskTier.LOW)
        assert [p.provider_id for p in ordered] == ["b", "c", "a"]

    def test_excludes_disabled_providers(self) -> None:
        a = make_provider_config("a", enabled=False)
        b = make_provider_config("b")
        router = TaskRouter(make_gateway_config(a, b))
        assert [p.provider_id for p in router.candidates_for(TaskTier.LOW)] == ["b"]

    def test_excludes_providers_not_supporting_the_tier(self) -> None:
        a = make_provider_config("a", supported_tiers=(TaskTier.HIGH,))
        b = make_provider_config("b", supported_tiers=(TaskTier.LOW, TaskTier.MEDIUM))
        router = TaskRouter(make_gateway_config(a, b))
        assert [p.provider_id for p in router.candidates_for(TaskTier.LOW)] == ["b"]
        assert [p.provider_id for p in router.candidates_for(TaskTier.HIGH)] == ["a"]

    def test_no_providers_configured_for_tier_returns_empty(self) -> None:
        a = make_provider_config("a", supported_tiers=(TaskTier.HIGH,))
        router = TaskRouter(make_gateway_config(a))
        assert router.candidates_for(TaskTier.LOW) == ()

    def test_ties_broken_by_provider_id_deterministically(self) -> None:
        a = make_provider_config("z", priority=0)
        b = make_provider_config("a", priority=0)
        router = TaskRouter(make_gateway_config(a, b))
        assert [p.provider_id for p in router.candidates_for(TaskTier.LOW)] == ["a", "z"]


class TestGatewayConfigValidation:
    def test_duplicate_provider_id_rejected(self) -> None:
        import pytest

        with pytest.raises(ValueError):
            GatewayConfig(providers=(make_provider_config("a"), make_provider_config("a")))
