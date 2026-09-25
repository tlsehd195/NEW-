"""resolve_api_key: resolves `ProviderConfig.api_key_reference` to a real
Gemini API key value.

**This module is the only place in `ai_gateway.providers.gemini*` that
calls `os.environ`/`os.getenv`** (`tests/ai_gateway/providers/
test_gemini_boundary.py` verifies this by AST scan), mirroring
`data_infra.providers.tiingo_auth.resolve_api_key`'s identical isolation
discipline. The resolved key is never returned beyond the immediate call
that needs it, never placed on a persisted model field, and never logged.
"""

from __future__ import annotations

import os

from ai_gateway.config import ProviderConfig
from ai_gateway.provider import ProviderAuthError


def resolve_api_key(config: ProviderConfig) -> str:
    api_key = os.environ.get(config.api_key_reference)
    if not api_key:
        raise ProviderAuthError(
            f"missing credentials: {config.api_key_reference} is not set in the environment"
        )
    return api_key
