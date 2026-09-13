"""Tests for `data_infra.providers.sec_13f_infotable_parser` (Session
37 continued, SEC 13F work). Fixture XML is shaped exactly like the
real Form 13F Information Table the account owner fetched this session
(Berkshire Hathaway, CIK 0001067983, accession 0001193125-26-352200) --
real CUSIP, real issuer name, real share counts (six real line items
for CUSIP 02005N100/Ally Financial, summing to a real, round 27,000,000
shares)."""

from __future__ import annotations

import pytest

from data_infra.providers.sec_13f_infotable_parser import (
    aggregate_shares_by_cusip,
    parse_13f_infotable_xml,
)

_NS = "http://www.sec.gov/edgar/document/thirteenf/informationtable"


def _info_table_entry(cusip: str, name: str, shares: int, other_manager: str = "4") -> str:
    return f"""
  <infoTable>
    <nameOfIssuer>{name}</nameOfIssuer>
    <titleOfClass>COM</titleOfClass>
    <cusip>{cusip}</cusip>
    <value>577211815</value>
    <shrsOrPrnAmt>
      <sshPrnamt>{shares}</sshPrnamt>
      <sshPrnamtType>SH</sshPrnamtType>
    </shrsOrPrnAmt>
    <investmentDiscretion>DFND</investmentDiscretion>
    <otherManager>{other_manager}</otherManager>
    <votingAuthority>
      <Sole>{shares}</Sole>
      <Shared>0</Shared>
      <None>0</None>
    </votingAuthority>
  </infoTable>"""


def _real_ally_financial_infotable_xml() -> bytes:
    """The exact real six line items for CUSIP 02005N100 (Ally
    Financial) from Berkshire Hathaway's real 2026-08-14 13F-HR filing
    -- real share counts, summing to a real, round 27,000,000."""
    shares_values = [12561737, 2803875, 4228200, 1707580, 4423608, 1275000]
    entries = "".join(_info_table_entry("02005N100", "ALLY FINL INC", s) for s in shares_values)
    xml = f'<informationTable xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns="{_NS}">{entries}\n</informationTable>'
    return xml.encode("utf-8")


class TestParse13fInfotableXml:
    def test_parses_every_real_line_item(self) -> None:
        records = parse_13f_infotable_xml(_real_ally_financial_infotable_xml())
        assert len(records) == 6
        assert all(r["cusip"] == "02005N100" for r in records)
        assert all(r["name_of_issuer"] == "ALLY FINL INC" for r in records)

    def test_parses_real_share_counts(self) -> None:
        records = parse_13f_infotable_xml(_real_ally_financial_infotable_xml())
        assert sorted(r["shares"] for r in records) == sorted([12561737, 2803875, 4228200, 1707580, 4423608, 1275000])

    def test_multiple_distinct_cusips_all_parsed(self) -> None:
        xml = f'<informationTable xmlns="{_NS}">{_info_table_entry("02005N100", "ALLY FINL INC", 100)}{_info_table_entry("38141G104", "GOLDMAN SACHS GROUP INC", 200)}\n</informationTable>'
        records = parse_13f_infotable_xml(xml.encode("utf-8"))
        assert {r["cusip"] for r in records} == {"02005N100", "38141G104"}

    def test_wrong_root_element_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="informationTable"):
            parse_13f_infotable_xml(b"<somethingElse></somethingElse>")

    def test_entry_missing_cusip_raises_value_error(self) -> None:
        xml = f"""<informationTable xmlns="{_NS}">
  <infoTable>
    <nameOfIssuer>ALLY FINL INC</nameOfIssuer>
    <shrsOrPrnAmt><sshPrnamt>100</sshPrnamt></shrsOrPrnAmt>
  </infoTable>
</informationTable>"""
        with pytest.raises(ValueError):
            parse_13f_infotable_xml(xml.encode("utf-8"))

    def test_empty_information_table_returns_empty_list(self) -> None:
        xml = f'<informationTable xmlns="{_NS}"></informationTable>'
        assert parse_13f_infotable_xml(xml.encode("utf-8")) == []


class TestAggregateSharesByCusip:
    def test_real_ally_financial_line_items_sum_to_the_real_total(self) -> None:
        """The real, documented fact this test is built from: Berkshire's
        six real line items for Ally Financial summed to exactly
        27,000,000 shares -- summing (not picking one line item) is
        the only way to get this real total."""
        records = parse_13f_infotable_xml(_real_ally_financial_infotable_xml())
        totals = aggregate_shares_by_cusip(records)
        assert totals == {"02005N100": 27_000_000}

    def test_distinct_cusips_are_not_mixed_together(self) -> None:
        records = [
            {"cusip": "AAA", "name_of_issuer": "A", "shares": 100},
            {"cusip": "BBB", "name_of_issuer": "B", "shares": 50},
            {"cusip": "AAA", "name_of_issuer": "A", "shares": 25},
        ]
        assert aggregate_shares_by_cusip(records) == {"AAA": 125, "BBB": 50}

    def test_empty_records_returns_empty_dict(self) -> None:
        assert aggregate_shares_by_cusip([]) == {}
