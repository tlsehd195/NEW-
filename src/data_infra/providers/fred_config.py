"""FredConfig: every value `FredMacroProvider` needs, kept out of code --
mirrors `data_infra.providers.tiingo_config.TiingoConfig`'s "credential
reference, never a secret value" discipline applied to the FRED (Federal
Reserve Economic Data) macro-data API instead of a per-security OHLCV
provider.

See docs/decisions/ADR-0208-fred-macro-data-adapter.md.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from data_infra.versioning import compute_data_version


@dataclass(frozen=True)
class FredConfig:
    version: str = "fred_config_v1"
    provider_id: str = "fred"
    base_url: str = "https://api.stlouisfed.org"
    # An environment-variable *name*, never a secret value itself --
    # reserved in .env.example (ADR-0208), mirroring TiingoConfig.
    # api_key_reference's identical "name, not value" discipline.
    api_key_reference: str = "FRED_API_KEY"
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if not self.provider_id:
            raise ValueError("FredConfig.provider_id must not be empty")
        if not self.base_url:
            raise ValueError("FredConfig.base_url must not be empty")
        if not self.api_key_reference:
            raise ValueError("FredConfig.api_key_reference must not be empty")
        if self.timeout_seconds <= 0:
            raise ValueError("FredConfig.timeout_seconds must be positive")

    def configuration_version(self) -> str:
        return compute_data_version(asdict(self))


DEFAULT_FRED_CONFIG = FredConfig()
