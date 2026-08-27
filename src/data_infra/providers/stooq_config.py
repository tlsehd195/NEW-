"""StooqConfig: Stooq requires no API key at all (ADR-0025: "No-API-key
CSV endpoint"), so unlike `TiingoConfig` there is no credential
reference field and no dedicated auth module -- there is nothing to
resolve from the environment for this provider.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from data_infra.versioning import compute_data_version


@dataclass(frozen=True)
class StooqConfig:
    version: str = "stooq_config_v1"
    provider_id: str = "stooq"
    base_url: str = "https://stooq.com"
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if not self.provider_id:
            raise ValueError("StooqConfig.provider_id must not be empty")
        if not self.base_url:
            raise ValueError("StooqConfig.base_url must not be empty")
        if self.timeout_seconds <= 0:
            raise ValueError("StooqConfig.timeout_seconds must be positive")

    def configuration_version(self) -> str:
        return compute_data_version(asdict(self))


DEFAULT_STOOQ_CONFIG = StooqConfig()
