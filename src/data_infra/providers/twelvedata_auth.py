"""resolve_api_key: resolves `TwelveDataConfig.api_key_reference` to a
real value.

**This module and `tiingo_auth.py`/`alphavantage_auth.py` are the only
places in `data_infra.providers.*` allowed to touch `os.environ`/
`os.getenv`** (`tests/data_infra/test_tiingo_auth.py` verifies this by
AST scan across the whole package). The resolved key is never returned
beyond the immediate call that needs it, never placed on a persisted
model field, and never logged.
"""

from __future__ import annotations

import os

from data_infra.provider import PermanentProviderError
from data_infra.providers.twelvedata_config import TwelveDataConfig


def resolve_api_key(config: TwelveDataConfig) -> str:
    api_key = os.environ.get(config.api_key_reference)
    if not api_key:
        raise PermanentProviderError(
            f"missing credentials: {config.api_key_reference} is not set in the environment"
        )
    return api_key
