"""ProviderSelector: PROJECT_MASTER_PLAN.md section 5's pipeline stage
between Quota Manager and Provider Adapter -- narrows the Task Router's
ordered candidate list down to providers that are actually available
*right now*, per the Quota Manager's fail-closed `is_available` check.

See docs/specifications/PHASE-12-ai-gateway.md section 9.
"""

from __future__ import annotations

from datetime import datetime

from ai_gateway.config import ProviderConfig
from ai_gateway.enums import TaskTier
from ai_gateway.quota_manager import QuotaManager
from ai_gateway.task_router import TaskRouter


class ProviderSelector:
    def __init__(self, task_router: TaskRouter, quota_manager: QuotaManager) -> None:
        self._task_router = task_router
        self._quota_manager = quota_manager

    def select(self, tier: TaskTier, *, as_of: datetime) -> tuple[ProviderConfig, ...]:
        """The ordered fallback sequence for `tier` at `as_of` -- every
        provider still configured/enabled for this tier that the Quota
        Manager currently considers available, in priority order. An
        empty tuple means "nothing is currently usable" (distinct from
        `TaskRouter.candidates_for` returning empty, which means
        "nothing is even configured" -- `ai_gateway.gateway.AIGateway`
        maps the two to different `RequestStatus` values)."""
        candidates = self._task_router.candidates_for(tier)
        return tuple(c for c in candidates if self._quota_manager.is_available(c.provider_id, as_of=as_of))
