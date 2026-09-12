"""Parses a real SEC Form 13F Information Table XML file into raw
per-line-item records, and aggregates them per CUSIP within ONE
filer's ONE filing -- the first stage of the two-stage aggregation
`data_infra.institutional_holding_models`'s own module docstring
describes ("summed across every 13F filer that reported a position in
it that quarter"). This module only performs stage one (within a
single filing); combining multiple filers' results into the final
cross-filer aggregate, and resolving each CUSIP to a `security_id`, are
separate concerns handled elsewhere (`sec_13f_cusip_resolution.py` for
the latter).

**Real, verified XML shape** (this session; fetched by the account
owner from a real SEC EDGAR Form 13F-HR filing -- Berkshire Hathaway,
CIK 0001067983, accession 0001193125-26-352200, filed 2026-08-14 --
never guessed from documentation alone, resolving the exact gap
`institutional_holding_models`'s own module docstring names: "this
project has not independently verified SEC's real quarterly INFOTABLE
structured-data-set file byte-for-byte from a live sample"):

    <informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
      <infoTable>
        <nameOfIssuer>ALLY FINL INC</nameOfIssuer>
        <titleOfClass>COM</titleOfClass>
        <cusip>02005N100</cusip>
        <value>577211815</value>
        <shrsOrPrnAmt>
          <sshPrnamt>12561737</sshPrnamt>
          <sshPrnamtType>SH</sshPrnamtType>
        </shrsOrPrnAmt>
        <investmentDiscretion>DFND</investmentDiscretion>
        <otherManager>4</otherManager>
        <votingAuthority>...</votingAuthority>
      </infoTable>
      ...
    </informationTable>

**The SAME CUSIP can legitimately appear multiple times within one
filer's filing** -- confirmed in the real Berkshire filing (CUSIP
`02005N100`/Ally Financial appeared 6+ times, each with a different
`otherManager` combination, representing different sub-managers'
shares of one consolidated position). `aggregate_shares_by_cusip` sums
`sshPrnamt` across every line item for the same CUSIP -- never picks
just one line item, which would silently undercount the filer's real
total position.

**`value` is deliberately never parsed here.** This project's own
`institutional_holding_file_import.py` schema does not use it
(`institutional_shares`/`num_institutions` only), and its real units
are genuinely ambiguous without a per-filing determination (SEC's Form
13F instructions changed the reporting unit from thousands of dollars
to whole dollars for filings after January 2023 -- this project has
not verified which convention any given historical filing used, so
extracting it here would risk silently asserting a wrong unit)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Sequence

_NAMESPACE = {"t": "http://www.sec.gov/edgar/document/thirteenf/informationtable"}


def parse_13f_infotable_xml(xml_bytes: bytes) -> list[dict]:
    """Returns one dict per real `<infoTable>` line item:
    `{"cusip": str, "name_of_issuer": str, "shares": int}`. Raises
    `ValueError` if the root element is not `informationTable` in the
    real, verified namespace above -- never silently parses a
    differently-shaped XML file as if it matched."""
    root = ET.fromstring(xml_bytes)
    expected_tag = f"{{{_NAMESPACE['t']}}}informationTable"
    if root.tag != expected_tag:
        raise ValueError(f"expected root element {expected_tag!r}, got {root.tag!r} -- not a real Form 13F information table")

    records: list[dict] = []
    for info_table in root.findall("t:infoTable", _NAMESPACE):
        cusip = info_table.findtext("t:cusip", namespaces=_NAMESPACE)
        name_of_issuer = info_table.findtext("t:nameOfIssuer", namespaces=_NAMESPACE)
        shares_text = info_table.findtext("t:shrsOrPrnAmt/t:sshPrnamt", namespaces=_NAMESPACE)
        if not cusip or shares_text is None:
            raise ValueError(f"infoTable entry missing required cusip/sshPrnamt: {ET.tostring(info_table, encoding='unicode')}")
        records.append({"cusip": cusip, "name_of_issuer": name_of_issuer, "shares": int(shares_text)})
    return records


def aggregate_shares_by_cusip(records: Sequence[dict]) -> dict[str, int]:
    """Sums `shares` across every record sharing the same `cusip` --
    one filer's TOTAL real position in that security for this filing,
    never just its first-encountered line item."""
    totals: dict[str, int] = {}
    for record in records:
        totals[record["cusip"]] = totals.get(record["cusip"], 0) + record["shares"]
    return totals
