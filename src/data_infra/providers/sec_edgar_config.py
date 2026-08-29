"""SecEdgarConfig: every value `SecEdgarFundamentalsProvider` needs,
kept out of code -- mirrors `TiingoConfig`'s shape (Phase 20), applied
to SEC EDGAR (Phase 33, ADR-0042).

Unlike Tiingo, SEC EDGAR's XBRL API requires no API key -- it is a
free, public US government data source -- but it does require every
request to carry a descriptive `User-Agent` identifying the requester
(SEC's own published fair-access policy: "Company Name AdminContact@
domain.com"), which is why `user_agent` is a required config field
rather than a hardcoded header, per this project's "no unowned
identifying string baked into code" discipline (mirrors
`api_key_reference` never being a literal secret).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from data_infra.versioning import compute_data_version


@dataclass(frozen=True)
class SecEdgarConfig:
    version: str = "sec_edgar_config_v1"
    provider_id: str = "sec_edgar"
    base_url: str = "https://data.sec.gov"
    # SEC's fair-access policy requires a descriptive User-Agent on
    # every request (documented requirement, not merely a courtesy --
    # requests without one are liable to be rejected). This is a
    # placeholder; a real deployment must set it to this project's own
    # actual contact string before making any live request.
    user_agent: str = "NEW- Research Project research@example.com"
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if not self.provider_id:
            raise ValueError("SecEdgarConfig.provider_id must not be empty")
        if not self.base_url:
            raise ValueError("SecEdgarConfig.base_url must not be empty")
        if not self.user_agent:
            raise ValueError("SecEdgarConfig.user_agent must not be empty")
        if self.timeout_seconds <= 0:
            raise ValueError("SecEdgarConfig.timeout_seconds must be positive")

    def configuration_version(self) -> str:
        return compute_data_version(asdict(self))


DEFAULT_SEC_EDGAR_CONFIG = SecEdgarConfig()
