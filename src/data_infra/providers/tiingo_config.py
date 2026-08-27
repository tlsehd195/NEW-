"""TiingoConfig: every value `TiingoDataProvider` needs, kept out of
code -- mirrors `broker.config.BrokerConfig`'s "credential reference,
never a secret value" discipline (Phase 13) applied to a market-data
provider instead (Phase 20, `docs/decisions/ADR-0025`).

See docs/decisions/ADR-0025-market-data-provider-selection.md.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from data_infra.versioning import compute_data_version


@dataclass(frozen=True)
class TiingoConfig:
    version: str = "tiingo_config_v1"
    provider_id: str = "tiingo"
    base_url: str = "https://api.tiingo.com"
    # An environment-variable *name*, never a secret value itself --
    # already reserved in .env.example since Phase 1 (MARKET_DATA_API_KEY).
    api_key_reference: str = "MARKET_DATA_API_KEY"
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if not self.provider_id:
            raise ValueError("TiingoConfig.provider_id must not be empty")
        if not self.base_url:
            raise ValueError("TiingoConfig.base_url must not be empty")
        if not self.api_key_reference:
            raise ValueError("TiingoConfig.api_key_reference must not be empty")
        if self.timeout_seconds <= 0:
            raise ValueError("TiingoConfig.timeout_seconds must be positive")

    def configuration_version(self) -> str:
        return compute_data_version(asdict(self))


DEFAULT_TIINGO_CONFIG = TiingoConfig()
