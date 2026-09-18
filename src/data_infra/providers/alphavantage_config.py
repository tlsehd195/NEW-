"""AlphaVantageConfig: every value `AlphaVantageDataProvider` needs,
kept out of code -- same "credential reference, never a secret value"
discipline as `TiingoConfig`/`TwelveDataConfig` (ADR-0025/ADR-0164).

See docs/decisions/ADR-0164-second-and-third-fallback-data-providers.md.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from data_infra.versioning import compute_data_version


@dataclass(frozen=True)
class AlphaVantageConfig:
    version: str = "alphavantage_config_v1"
    provider_id: str = "alphavantage"
    base_url: str = "https://www.alphavantage.co"
    # An environment-variable *name*, never a secret value itself.
    api_key_reference: str = "ALPHAVANTAGE_API_KEY"
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if not self.provider_id:
            raise ValueError("AlphaVantageConfig.provider_id must not be empty")
        if not self.base_url:
            raise ValueError("AlphaVantageConfig.base_url must not be empty")
        if not self.api_key_reference:
            raise ValueError("AlphaVantageConfig.api_key_reference must not be empty")
        if self.timeout_seconds <= 0:
            raise ValueError("AlphaVantageConfig.timeout_seconds must be positive")

    def configuration_version(self) -> str:
        return compute_data_version(asdict(self))


DEFAULT_ALPHAVANTAGE_CONFIG = AlphaVantageConfig()
