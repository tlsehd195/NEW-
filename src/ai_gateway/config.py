"""ProviderConfig / TaskRoutingConfig / GatewayConfig: every threshold
and routing choice the AI Gateway uses, kept out of code -- the same
discipline `learning.config`/`decision.config`/`risk.config`/
`evolution.config` already established.

See docs/specifications/PHASE-12-ai-gateway.md sections 5, 6.

`ProviderConfig.api_key_reference` is a *name* (e.g.
`"AI_PROVIDER_A_API_KEY"`, matching the placeholder already reserved in
`.env.example`) -- never a real key value. Nothing in this module reads
`os.environ`/`os.getenv` at all (`tests/ai_gateway/test_ai_gateway_boundary.py`
verifies this by AST scan across the whole package): Phase 12 does not
make a real provider call, so it never needs to resolve the reference to
an actual secret.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

from ai_gateway.enums import TaskTier

from data_infra.versioning import compute_data_version


@dataclass(frozen=True)
class ProviderConfig:
    version: str = "provider_config_v1"
    provider_id: str = "mock-provider"
    provider_name: str = "Mock Provider"
    model: str = "mock-model-v1"
    api_key_reference: str = "AI_PROVIDER_A_API_KEY"  # env var NAME only -- never a value
    rpm_limit: Optional[int] = 60
    rpd_limit: Optional[int] = 1000
    tpm_limit: Optional[int] = 100_000
    tpd_limit: Optional[int] = 1_000_000
    monthly_limit: Optional[int] = None
    priority: int = 0  # lower = tried first within a tier
    enabled: bool = True
    supported_tiers: tuple[TaskTier, ...] = (TaskTier.LOW, TaskTier.MEDIUM, TaskTier.HIGH)
    timeout_seconds: float = 30.0
    max_retries: int = 2

    def __post_init__(self) -> None:
        if not self.provider_id:
            raise ValueError("ProviderConfig.provider_id must not be empty")
        for name, value in (
            ("rpm_limit", self.rpm_limit), ("rpd_limit", self.rpd_limit),
            ("tpm_limit", self.tpm_limit), ("tpd_limit", self.tpd_limit),
            ("monthly_limit", self.monthly_limit),
        ):
            if value is not None and value <= 0:
                raise ValueError(f"{name} must be positive when configured, got {value!r}")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.max_retries < 0:
            raise ValueError("max_retries must not be negative")
        if not self.supported_tiers:
            raise ValueError("supported_tiers must not be empty")

    def configuration_version(self) -> str:
        payload = asdict(self)
        payload["supported_tiers"] = [t.value for t in self.supported_tiers]
        return compute_data_version(payload)


@dataclass(frozen=True)
class GatewayConfig:
    """The Task Router's provider priority list per tier is derived
    directly from `providers` (each provider's `supported_tiers` +
    `priority`), never a second, independently-maintained list that
    could drift out of sync with the provider configs themselves."""

    version: str = "gateway_config_v1"
    providers: tuple[ProviderConfig, ...] = field(default_factory=lambda: (ProviderConfig(),))

    def __post_init__(self) -> None:
        ids = [p.provider_id for p in self.providers]
        if len(ids) != len(set(ids)):
            raise ValueError(f"GatewayConfig.providers has duplicate provider_id values: {ids!r}")

    def providers_for_tier(self, tier: TaskTier) -> tuple[ProviderConfig, ...]:
        """Enabled providers that support `tier`, ordered by
        `priority` ascending, ties broken by `provider_id` for
        determinism."""
        candidates = [p for p in self.providers if p.enabled and tier in p.supported_tiers]
        return tuple(sorted(candidates, key=lambda p: (p.priority, p.provider_id)))

    def configuration_version(self) -> str:
        return compute_data_version(
            {"version": self.version, "providers": [p.configuration_version() for p in self.providers]}
        )


DEFAULT_GATEWAY_CONFIG = GatewayConfig()
