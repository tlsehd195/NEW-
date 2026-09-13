"""Tests for `data_infra.providers.openfigi_cusip_resolution` (Session
37 continued, SEC 13F work). No network call in this module -- fixture
responses are shaped exactly like the real OpenFIGI `/v3/mapping`
response the account owner fetched this session for the real CUSIP
`02005N100` (Ally Financial), both with and without the `exchCode:
"US"` filter."""

from __future__ import annotations

import pytest

from data_infra.providers.openfigi_cusip_resolution import (
    build_mapping_request,
    parse_mapping_response,
)


def _real_ally_financial_us_response() -> dict:
    """The real response confirmed this session with exchCode: "US" in
    the request -- exactly one entry, the real US-primary listing."""
    return {
        "data": [
            {
                "figi": "BBG000BC2R71", "name": "ALLY FINANCIAL INC", "ticker": "ALLY",
                "exchCode": "US", "compositeFIGI": "BBG000BC2R71", "securityType": "Common Stock",
                "marketSector": "Equity", "shareClassFIGI": "BBG001S5RLN4",
                "securityType2": "Common Stock", "securityDescription": "ALLY",
            }
        ]
    }


class TestBuildMappingRequest:
    def test_includes_exch_code_us_filter(self) -> None:
        """The real, confirmed difference: without this filter, the
        same real CUSIP returned 100+ entries across every exchange/
        currency variant worldwide."""
        request = build_mapping_request(["02005N100"])
        assert request == [{"idType": "ID_CUSIP", "idValue": "02005N100", "exchCode": "US"}]

    def test_preserves_input_order(self) -> None:
        request = build_mapping_request(["AAA", "BBB", "CCC"])
        assert [r["idValue"] for r in request] == ["AAA", "BBB", "CCC"]

    def test_builds_a_request_of_any_size_batching_is_the_callers_job(self) -> None:
        """This pure function never enforces OpenFIGI's real per-request
        limit (confirmed 10, not the 100 secondary sources suggested,
        ADR-0131) -- that policy lives in the CLI script's own
        --batch-size, so a real limit change only needs updating in
        one place."""
        request = build_mapping_request([f"CUSIP{i}" for i in range(37)])
        assert len(request) == 37


class TestParseMappingResponse:
    def test_real_ally_financial_case_resolves_to_the_real_ticker(self) -> None:
        result = parse_mapping_response(["02005N100"], [_real_ally_financial_us_response()])
        assert result == {"02005N100": "ALLY"}

    def test_unresolvable_cusip_maps_to_none_not_fabricated(self) -> None:
        result = parse_mapping_response(["NOSUCHCUSIP"], [{"data": []}])
        assert result == {"NOSUCHCUSIP": None}

    def test_error_entry_maps_to_none(self) -> None:
        result = parse_mapping_response(["BADCUSIP"], [{"error": "No identifier found."}])
        assert result == {"BADCUSIP": None}

    def test_multiple_cusips_matched_by_position_not_value(self) -> None:
        responses = [_real_ally_financial_us_response(), {"data": []}]
        result = parse_mapping_response(["02005N100", "UNKNOWNCUSIP"], responses)
        assert result == {"02005N100": "ALLY", "UNKNOWNCUSIP": None}

    def test_mismatched_lengths_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            parse_mapping_response(["A", "B"], [_real_ally_financial_us_response()])

    def test_multiple_data_entries_uses_the_first(self) -> None:
        response = {
            "data": [
                {"ticker": "PRIMARY", "exchCode": "US"},
                {"ticker": "SECONDARY", "exchCode": "US"},
            ]
        }
        result = parse_mapping_response(["X"], [response])
        assert result == {"X": "PRIMARY"}
