"""ADR-0231: point-in-time CUSIP lists for the 13F ownership map."""

from __future__ import annotations

import json

import pytest

from data_infra.providers.sec_13f_cusip_history import (
    company_names,
    confirm_cusips,
    core_name,
    cusip_check_digit_ok,
    dominant_cusip,
    is_share_row,
    load_cusip_to_ticker,
    name_matches,
    normalize,
    read_overrides,
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


class TestRowFilters:
    def test_check_digit(self) -> None:
        for good in ("037833100", "38259P508", "02079K305", "30231G102", "369604301"):
            assert cusip_check_digit_ok(good), good
        assert not cusip_check_digit_ok("037833101")
        assert not cusip_check_digit_ok("03783310")

    def test_only_plain_share_rows(self) -> None:
        assert is_share_row("SH", "")
        assert not is_share_row("PRN", "")
        assert not is_share_row("SH", "Put")

    def test_dominant_is_largest_valid_cusip(self) -> None:
        # The common line dwarfs a preferred and a typo CUSIP.
        assert dominant_cusip({"037833100": 5e9, "037833101": 9e9, "060505682": 1e6}) == "037833100"
        assert dominant_cusip({"BAD": 1.0}) is None

    def test_debt_issues_are_never_dominant(self) -> None:
        # Tesla's convertible notes carry letter issue numbers.
        assert dominant_cusip({"88160R101": 1e6, "88160RAB7": 9e9}) == "88160R101"

    def test_overrides(self) -> None:
        names, excluded = read_overrides([
            {"ticker": "GOOGL", "kind": "predecessor_name", "value": "GOOGLE INC"},
            {"ticker": "LIN", "kind": "exclude_cusip", "value": "d50348107"},
        ])
        assert names == {"GOOGL": ["GOOGLE"]}
        assert excluded == {"LIN": {"D50348107"}}
        with pytest.raises(ValueError):
            read_overrides([{"ticker": "X", "kind": "typo", "value": "Y"}])

    def test_normalize_splits_state_suffix(self) -> None:
        assert normalize("QUALCOMM INC/DE") == "QUALCOMM INC DE"
        assert core_name("QUALCOMM INC/DE") == "QUALCOMM"
        assert normalize("AT&T INC") == "ATT INC"


class TestConfirm:
    def test_own_or_former_ticker_and_unresolved_are_kept(self) -> None:
        confirmed, notes = confirm_cusips(
            {"RTX": {"75513E101", "913017109"}, "XOM": {"30231G102"}},
            {"75513E101": "RTX", "913017109": "UTX", "30231G102": None},
            {"RTX": {"UTX"}},
        )
        assert confirmed == {"RTX": ["75513E101", "913017109"], "XOM": ["30231G102"]}
        assert "RTX" not in notes
        assert notes["XOM"] == "kept without OpenFIGI confirmation"

    def test_cusip_resolving_to_unrelated_ticker_is_rejected(self) -> None:
        confirmed, notes = confirm_cusips({"GE": {"369604301", "370334104"}}, {"369604301": "GE", "370334104": "GIS"}, {})
        assert confirmed == {"GE": ["369604301"]}
        assert notes["GE"] == "rejected 370334104->GIS"

    def test_a_cusip_kept_for_two_tickers_is_dropped(self) -> None:
        confirmed, _ = confirm_cusips(
            {"AAA": {"111111111", "222222222"}, "BBB": {"222222222", "333333333"}},
            {"111111111": "AAA", "222222222": None, "333333333": "BBB"},
            {},
        )
        assert confirmed == {"AAA": ["111111111"], "BBB": ["333333333"]}


class TestLoadMap:
    def test_reads_lists_and_old_single_values(self) -> None:
        text = json.dumps({"GOOGL": ["02079K305", "38259P508"], "AAPL": "037833100"})
        assert load_cusip_to_ticker(text) == {"02079K305": "GOOGL", "38259P508": "GOOGL", "037833100": "AAPL"}

    def test_shared_cusip_is_refused(self) -> None:
        with pytest.raises(ValueError, match="both"):
            load_cusip_to_ticker(json.dumps({"A": ["111111111"], "B": ["111111111"]}))


def test_committed_overrides_file_parses() -> None:
    # *.csv is gitignored; this fails if the reviewed file is not tracked.
    import csv
    import subprocess
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "docs" / "research" / "reference" / "sec_13f_cusip_overrides.csv"
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", str(path)], cwd=path.parent, capture_output=True)
    assert tracked.returncode == 0, "sec_13f_cusip_overrides.csv must be committed (git add -f)"
    with path.open() as fh:
        names, excluded = read_overrides(csv.DictReader(fh))
    assert "GOOGL" in names and "LIN" in excluded
