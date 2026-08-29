"""Category: SecEdgarConfig validation -- mirrors TiingoConfig's own
test coverage shape (Phase 33, ADR-0042)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from data_infra.providers.sec_edgar_config import DEFAULT_SEC_EDGAR_CONFIG, SecEdgarConfig


class TestDefaults:
    def test_default_config_requires_no_api_key_reference(self) -> None:
        # Unlike TiingoConfig, SEC EDGAR needs no API key -- there is
        # deliberately no api_key_reference field on this config.
        assert not hasattr(DEFAULT_SEC_EDGAR_CONFIG, "api_key_reference")

    def test_default_base_url_is_data_sec_gov(self) -> None:
        assert DEFAULT_SEC_EDGAR_CONFIG.base_url == "https://data.sec.gov"

    def test_default_user_agent_is_non_empty(self) -> None:
        assert DEFAULT_SEC_EDGAR_CONFIG.user_agent


class TestValidation:
    def test_empty_user_agent_rejected(self) -> None:
        with pytest.raises(ValueError):
            replace(DEFAULT_SEC_EDGAR_CONFIG, user_agent="")

    def test_empty_base_url_rejected(self) -> None:
        with pytest.raises(ValueError):
            replace(DEFAULT_SEC_EDGAR_CONFIG, base_url="")

    def test_non_positive_timeout_rejected(self) -> None:
        with pytest.raises(ValueError):
            replace(DEFAULT_SEC_EDGAR_CONFIG, timeout_seconds=0.0)


class TestConfigurationVersion:
    def test_differing_configs_have_differing_versions(self) -> None:
        a = SecEdgarConfig()
        b = replace(a, user_agent="Different Agent x@example.com")
        assert a.configuration_version() != b.configuration_version()

    def test_identical_configs_have_identical_versions(self) -> None:
        assert SecEdgarConfig().configuration_version() == SecEdgarConfig().configuration_version()
