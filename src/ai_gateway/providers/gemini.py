"""GeminiProviderAdapter: a real (not mock) `ai_gateway.provider.
AIProviderAdapter` implementation, calling Google's Gemini API.

See this subpackage's own `__init__.py` docstring and ADR-0206 for why
this lives here rather than in `ai_gateway.provider` alongside
`MockProviderAdapter`. Only ever constructed by `scripts.
run_ai_prediction_experiment`/`scripts.verify_gemini_adapter` in this
repository -- never by `predict`/`decision`/`risk`/`broker`, which do not
import `ai_gateway.providers.*` at all (ADR-0206's own boundary section).

**Honesty about evidence tier**: unlike this project's market-data
providers (built only against Tier 2 documentation, never exercised
against a real response), this adapter's request/response shape WAS
verified directly against a real Gemini API call in this environment
(2026-09-25, `scripts/verify_gemini_adapter.py`, account owner's own
`GEMINI_API_KEY`) -- see `ai_gateway.providers.gemini_transport`'s own
docstring for the exact facts confirmed. The one still-unverified
assumption, isolated here alone: `generationConfig.thinkingConfig.
thinkingBudget` (an attempt to cap `gemini-3.8-flash`'s default "thinking"
token spend, named after the equivalent Gemini 2.5-generation parameter)
was never actually confirmed to be honored by a real response inspected
in this environment -- the free tier's 5 requests/minute limit was
already exhausted verifying the rest of this module before that specific
check could be made. If a future session confirms this field does
nothing for this model, remove it rather than leave a silently-ignored
setting.
"""

from __future__ import annotations

from typing import Iterator, Optional

from ai_gateway.config import ProviderConfig
from ai_gateway.enums import ProviderHealthStatus
from ai_gateway.models import AIRequest, ProviderLimits, UsageEstimate, UsageInfo
from ai_gateway.provider import RawProviderOutput
from ai_gateway.providers.gemini_auth import resolve_api_key
from ai_gateway.providers.gemini_transport import GeminiHttpTransport

# `rpm_limit=5` is a real, directly-confirmed number (2026-09-25 free-tier
# 429 response body: "limit: 5, model: gemini-3.8-flash" -- see
# `ai_gateway.providers.gemini_transport`'s own docstring). The other three
# limit fields stay `None` (honestly "not confirmed"), never a guessed
# number standing in for a real one -- `QuotaManager` does not enforce
# `rpm_limit`/`tpm_limit` proactively today (it only tracks `rpd_limit`/
# `tpd_limit`), so this value is informational for a caller's own client-side
# pacing (`scripts.run_ai_prediction_experiment`'s `--pause-seconds`), not
# something the Gateway itself currently paces against.
DEFAULT_GEMINI_PROVIDER_CONFIG = ProviderConfig(
    provider_id="gemini",
    provider_name="Google Gemini",
    model="gemini-3.8-flash",
    api_key_reference="GEMINI_API_KEY",
    rpm_limit=5,
    rpd_limit=None,
    tpm_limit=None,
    tpd_limit=None,
    monthly_limit=None,
)


def _build_request_body(request: AIRequest) -> dict:
    body: dict = {"contents": [{"role": "user", "parts": [{"text": request.payload}]}]}
    generation_config: dict = {
        # Best-effort attempt to cap "thinking" token spend -- see this
        # module's own "Honesty about evidence tier" docstring above for
        # why this one field is not yet confirmed to have any effect.
        "thinkingConfig": {"thinkingBudget": 0},
    }
    if request.max_tokens is not None:
        generation_config["maxOutputTokens"] = request.max_tokens
    if request.response_schema:
        # Prompt-level structured output: `AIRequest.response_schema` is
        # field NAMES only (no types -- `ai_gateway.validation`'s own
        # contract), so this asks for JSON output generically rather
        # than constructing a typed Gemini `responseSchema`, which would
        # require guessing a type for each field this module has no way
        # to know.
        generation_config["responseMimeType"] = "application/json"
    body["generationConfig"] = generation_config
    return body


def _extract_text(body: Optional[dict]) -> str:
    if not body:
        return ""
    candidates = body.get("candidates") or []
    if not candidates:
        return ""
    parts = (candidates[0].get("content") or {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts if isinstance(p, dict) and "text" in p)


def _extract_usage(body: Optional[dict]) -> UsageInfo:
    meta = (body or {}).get("usageMetadata")
    if not isinstance(meta, dict):
        return UsageInfo()
    return UsageInfo(
        prompt_tokens=meta.get("promptTokenCount"),
        completion_tokens=meta.get("candidatesTokenCount"),
        # Read directly from Gemini's own total, never `prompt +
        # completion` -- gemini-3.8-flash's `thoughtsTokenCount` is part
        # of the real total but not part of either of those two fields
        # (gemini_transport's own docstring point 2); summing the other
        # two would silently under-report real usage.
        total_tokens=meta.get("totalTokenCount"),
    )


def _sum_usage(a: UsageInfo, b: UsageInfo) -> UsageInfo:
    return UsageInfo(
        prompt_tokens=(a.prompt_tokens or 0) + (b.prompt_tokens or 0),
        completion_tokens=(a.completion_tokens or 0) + (b.completion_tokens or 0),
        total_tokens=(a.total_tokens or 0) + (b.total_tokens or 0),
    )


class GeminiProviderAdapter:
    """`generate()` performs exactly one real HTTP call per invocation --
    no client-side retry loop here (`ai_gateway.gateway.AIGateway`
    already owns retry/failover across `ProviderConfig.max_retries` and
    provider fallback; duplicating that here would retry twice for one
    logical attempt)."""

    def __init__(self, config: ProviderConfig, *, transport: Optional[GeminiHttpTransport] = None) -> None:
        self.provider_id = config.provider_id
        self._config = config
        self._transport = transport if transport is not None else GeminiHttpTransport()
        self._cumulative_usage = UsageInfo(prompt_tokens=0, completion_tokens=0, total_tokens=0)

    def generate(self, request: AIRequest) -> RawProviderOutput:
        api_key = resolve_api_key(self._config)
        response = self._transport.generate_content(
            model=self._config.model,
            api_key=api_key,
            request_body=_build_request_body(request),
            timeout=self._config.timeout_seconds,
        )
        usage = _extract_usage(response.body)
        self._cumulative_usage = _sum_usage(self._cumulative_usage, usage)
        # `_extract_text` returns "" for a safety-blocked/empty response
        # (no candidates, or a candidate with no text part) -- `ai_gateway.
        # validation.validate_response_content` already treats an empty
        # string as `INVALID_RESPONSE` ("empty_content"), so that case is
        # handled correctly without this adapter inventing a second,
        # adapter-specific failure path for it.
        return RawProviderOutput(content=_extract_text(response.body), usage=usage)

    def stream(self, request: AIRequest) -> Iterator[str]:
        # Matches `MockProviderAdapter.stream()`'s own documented scope
        # (PHASE-12 spec section 1.1: `stream()` is not a real streaming
        # interface in this phase) -- two chunks of the same content
        # `generate()` would produce, not Gemini's own SSE streaming
        # endpoint.
        output = self.generate(request)
        midpoint = max(1, len(output.content) // 2)
        yield output.content[:midpoint]
        yield output.content[midpoint:]

    def estimate_usage(self, request: AIRequest) -> UsageEstimate:
        estimated_prompt_tokens = max(1, len(request.payload) // 4)
        estimated_completion_tokens = request.max_tokens or estimated_prompt_tokens
        return UsageEstimate(
            provider_id=self.provider_id,
            estimated_prompt_tokens=estimated_prompt_tokens,
            estimated_total_tokens=estimated_prompt_tokens + estimated_completion_tokens,
            basis="char_count_heuristic_v1",
        )

    def get_usage(self) -> UsageInfo:
        return self._cumulative_usage

    def health_check(self) -> ProviderHealthStatus:
        # No lightweight, quota-free Gemini endpoint exists to probe --
        # calling generateContent itself would consume real quota just to
        # check health. `UNKNOWN` is the honest answer (`ai_gateway.
        # enums.ProviderHealthStatus`'s own docstring: `QuotaManager`
        # treats `UNKNOWN` exactly like `UNAVAILABLE`, never as a
        # fabricated `HEALTHY` this adapter has not actually verified).
        return ProviderHealthStatus.UNKNOWN

    def get_limits(self) -> ProviderLimits:
        return ProviderLimits(
            provider_id=self.provider_id,
            rpm_limit=self._config.rpm_limit,
            rpd_limit=self._config.rpd_limit,
            tpm_limit=self._config.tpm_limit,
            tpd_limit=self._config.tpd_limit,
            monthly_limit=self._config.monthly_limit,
        )
