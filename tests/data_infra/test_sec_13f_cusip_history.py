"""ADR-0231: point-in-time CUSIP lists for the 13F ownership map."""

from __future__ import annotations

import json

import pytest

from data_infra.providers.sec_13f_cusip_history import (
    company_names,
    confirm_cusips,
    core_name,
    load_cusip_to_ticker,
    name_matches,
)


class TestNames:
    def test_core_name_strips_suffixes_and_the(self) -> None:
        assert core_name("Exxon Mobil Corp") == "EXXON MOBIL"
        assert core_name("The Walt Disney Co.") == "WALT DISNEY"
        assert core_name("EXXON MOBIL CORP NEW") == "EXXON MOBIL"

    def test_former_names_are_included(self) -> None:
        submissions = {"formerNames": [
            {"name": "GOOGLE INC.", "from": "2004-04-29", "to": "2015-09-01"},
            {"name": "Alphabet Inc.", "from": "2015-09-02", "to": "2026-01-01"},
        ]}
        assert company_names("Alphabet Inc.", submissions) == ["ALPHABET", "GOOGLE"]

    def test_no_submissions_means_current_name_only(self) -> None:
        assert company_names("Apple Inc.", None) == ["APPLE"]

    def test_match_is_whole_word(self) -> None:
        assert name_matches("GENERAL ELECTRIC CO", ["GENERAL ELECTRIC"])
        assert not name_matches("GENERAL MILLS INC", ["GE"])
        assert not name_matches("APPLE HOSPITALITY REIT INC", ["APPLE HOSPITALITY REIT INC X"])


class TestConfirm:
    def test_openfigi_ticker_or_former_ticker_is_accepted(self) -> None:
        confirmed = confirm_cusips(
            {"RTX": {"75513E101", "913017109", "999999999"}},
            {"75513E101": "RTX", "913017109": "UTX", "999999999": "OTHER"},
            {"RTX": {"UTX"}},
        )
        assert confirmed == {"RTX": ["75513E101", "913017109"]}

    def test_unresolved_cusip_with_a_confirmed_issuer_prefix_is_accepted(self) -> None:
        # GE's reverse split: same issuer prefix, new issue number.
        confirmed = confirm_cusips(
            {"GE": {"369604301", "369604103", "123456789"}},
            {"369604301": "GE", "369604103": None, "123456789": None},
            {},
        )
        assert confirmed == {"GE": ["369604103", "369604301"]}

    def test_unresolved_cusips_alone_are_never_accepted(self) -> None:
        assert confirm_cusips({"XOM": {"30231G102"}}, {"30231G102": None}, {}) == {}

    def test_a_cusip_claimed_by_two_tickers_is_dropped(self) -> None:
        confirmed = confirm_cusips(
            {"AAA": {"111111111", "222222222"}, "BBB": {"222222222", "333333333"}},
            {"111111111": "AAA", "222222222": "AAA", "333333333": "BBB"},
            {"BBB": {"AAA"}},
        )
        assert confirmed == {"AAA": ["111111111"], "BBB": ["333333333"]}


class TestLoadMap:
    def test_reads_lists_and_old_single_values(self) -> None:
        text = json.dumps({"GOOGL": ["02079K305", "38259P508"], "AAPL": "037833100"})
        assert load_cusip_to_ticker(text) == {"02079K305": "GOOGL", "38259P508": "GOOGL", "037833100": "AAPL"}

    def test_shared_cusip_is_refused(self) -> None:
        with pytest.raises(ValueError, match="both"):
            load_cusip_to_ticker(json.dumps({"A": ["111111111"], "B": ["111111111"]}))
