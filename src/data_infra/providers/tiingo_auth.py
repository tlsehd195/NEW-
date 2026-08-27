"""resolve_api_key: resolves `TiingoConfig.api_key_reference` to a real
value.

**This module is the only place in `data_infra.providers.*` that calls
`os.environ`/`os.getenv`** (`tests/data_infra/test_tiingo_provider.py`
verifies this by AST scan), mirroring `broker.toss.auth`'s identical
isolation discipline for the Toss credential (Phase 13). The resolved
key is never returned beyond the immediate call that needs it, never
placed on a persisted model field, and never logged.
"""

from __future__ import annotations

import os

from data_infra.providers.tiingo_config import TiingoConfig
from data_infra.provider import PermanentProviderError


def resolve_api_key(config: TiingoConfig) -> str:
    api_key = os.environ.get(config.api_key_reference)
    if not api_key:
        raise PermanentProviderError(
            f"missing credentials: {config.api_key_reference} is not set in the environment"
        )
    return api_key
