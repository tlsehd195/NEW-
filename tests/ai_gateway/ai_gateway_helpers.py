"""Shared test helpers for the Phase 12 AI Gateway test suite."""

from __future__ import annotations

from datetime import datetime, timezone

from ai_gateway.config import GatewayConfig, ProviderConfig
from ai_gateway.enums import TaskTier
from ai_gateway.models import AIRequest

from trade_journal.enums import TradeProvenance


def utc(year: int, month: int, day: int, hour: int = 12, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def make_provider_config(provider_id: str = "provider-a", **overrides) -> ProviderConfig:
    fields = dict(provider_id=provider_id, provider_name=f"Provider {provider_id}", model="mock-model-v1")
    fields.update(overrides)
    return ProviderConfig(**fields)


def make_gateway_config(*providers: ProviderConfig) -> GatewayConfig:
    if not providers:
        providers = (make_provider_config(),)
    return GatewayConfig(providers=providers)


def make_request(
    request_id: str = "AIREQ-000001",
    *,
    task_tier: TaskTier = TaskTier.LOW,
    payload: str = "summarize: hello world",
    prompt_template_id: str = "test-template",
    prompt_template_version: str = "v1",
    max_tokens: int | None = 200,
    requested_at: datetime = utc(2024, 3, 1),
    provenance: TradeProvenance = TradeProvenance.HISTORICAL_SIMULATION,
    experiment_id: str | None = None,
    response_schema: tuple[str, ...] | None = None,
) -> AIRequest:
    return AIRequest(
        request_id=request_id, task_tier=task_tier, prompt_template_id=prompt_template_id,
        prompt_template_version=prompt_template_version, payload=payload, max_tokens=max_tokens,
        requested_at=requested_at, provenance=provenance, experiment_id=experiment_id,
        response_schema=response_schema,
    )


__all__ = ["utc", "make_provider_config", "make_gateway_config", "make_request"]
