"""Category: Provider Selector Test -- narrows the Task Router's ordered
candidates down to what the Quota Manager currently considers available."""

from __future__ import annotations

from ai_gateway_helpers import make_gateway_config, make_provider_config, utc

from ai_gateway.enums import TaskTier
from ai_gateway.provider_selector import ProviderSelector
from ai_gateway.quota_manager import QuotaManager
from ai_gateway.repository import InMemoryQuotaStateRepository
from ai_gateway.task_router import TaskRouter


class TestSelect:
    def test_returns_all_available_in_priority_order(self) -> None:
        a = make_provider_config("a", priority=0)
        b = make_provider_config("b", priority=1)
        config = make_gateway_config(a, b)
        qm = QuotaManager(InMemoryQuotaStateRepository())
        qm.initialize(a, at=utc(2024, 1, 1))
        qm.initialize(b, at=utc(2024, 1, 1))
        selector = ProviderSelector(TaskRouter(config), qm)
        assert [p.provider_id for p in selector.select(TaskTier.LOW, as_of=utc(2024, 1, 1))] == ["a", "b"]

    def test_excludes_exhausted_provider(self) -> None:
        a = make_provider_config("a", priority=0)
        b = make_provider_config("b", priority=1)
        config = make_gateway_config(a, b)
        qm = QuotaManager(InMemoryQuotaStateRepository())
        qm.initialize(a, at=utc(2024, 1, 1))
        qm.initialize(b, at=utc(2024, 1, 1))
        qm.mark_quota_exhausted("a", at=utc(2024, 1, 1, 13))
        selector = ProviderSelector(TaskRouter(config), qm)
        assert [p.provider_id for p in selector.select(TaskTier.LOW, as_of=utc(2024, 1, 1, 14))] == ["b"]

    def test_uninitialized_provider_is_excluded_not_assumed_available(self) -> None:
        a = make_provider_config("a")
        config = make_gateway_config(a)
        qm = QuotaManager(InMemoryQuotaStateRepository())  # never initialized
        selector = ProviderSelector(TaskRouter(config), qm)
        assert selector.select(TaskTier.LOW, as_of=utc(2024, 1, 1)) == ()

    def test_all_exhausted_returns_empty(self) -> None:
        a = make_provider_config("a")
        config = make_gateway_config(a)
        qm = QuotaManager(InMemoryQuotaStateRepository())
        qm.initialize(a, at=utc(2024, 1, 1))
        qm.mark_quota_exhausted("a", at=utc(2024, 1, 1, 13))
        selector = ProviderSelector(TaskRouter(config), qm)
        assert selector.select(TaskTier.LOW, as_of=utc(2024, 1, 1, 14)) == ()
