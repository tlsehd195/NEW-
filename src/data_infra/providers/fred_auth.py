"""resolve_api_key: resolves `FredConfig.api_key_reference` to a real
FRED API key value.

**This module is (along with `tiingo_auth.py`/`twelvedata_auth.py`/
`alphavantage_auth.py`) one of the only places in `data_infra.
providers.*` that calls `os.environ`/`os.getenv`**
(`tests/data_infra/test_fred_auth.py` verifies this by AST scan, and
`tests/broker/live/test_production_safety_cross_cutting.py`'s repo-wide
scan has `fred_auth.py` added to its `allowed_files` set). The resolved
key is never returned beyond the immediate call that needs it, never
placed on a persisted model field, and never logged.
"""

from __future__ import annotations

import os

from data_infra.providers.fred_config import FredConfig
from data_infra.provider import PermanentProviderError


def resolve_api_key(config: FredConfig) -> str:
    api_key = os.environ.get(config.api_key_reference)
    if not api_key:
        raise PermanentProviderError(
            f"missing credentials: {config.api_key_reference} is not set in the environment"
        )
    return api_key
