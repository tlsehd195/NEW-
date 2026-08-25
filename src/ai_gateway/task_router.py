"""TaskRouter: PROJECT_MASTER_PLAN.md section 5.2 -- "모든 작업에 같은
모델을 사용하지 않는다... Task Router가 작업 등급에 맞는 provider/model을
선택한다."

See docs/specifications/PHASE-12-ai-gateway.md section 6.
"""

from __future__ import annotations

from ai_gateway.config import GatewayConfig, ProviderConfig
from ai_gateway.enums import TaskTier


class TaskRouter:
    """A thin, deterministic lookup over `GatewayConfig` -- no state of
    its own, no data access, no randomness. `candidates_for` is the
    single source of truth for "which providers, in what order, may
    serve this tier" that both the Gateway and tests use, so routing
    logic is never duplicated."""

    def __init__(self, config: GatewayConfig) -> None:
        self._config = config

    def candidates_for(self, tier: TaskTier) -> tuple[ProviderConfig, ...]:
        return self._config.providers_for_tier(tier)
