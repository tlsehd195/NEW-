"""Point-in-time CUSIP lists for the 13F institutional-ownership map
(ADR-0231).

ADR-0131 mapped each ticker to the ONE CUSIP its shares carry today. A
company whose CUSIP changed (Google -> Alphabet 2015, a reverse split,
a REIT conversion, a rename) therefore had no 13F holdings before the
change: the 2026-09-26 backfill started GOOGL in 2015-09, WELL in
2015-09, GE in 2021-06, AVGO in 2018-03 and RTX in 2020-03.

This module keeps every CUSIP a ticker's company has used, so
`backfill_institutional_holdings_from_sec_bulk.py` sums all of them per
quarter (`aggregate_holdings` already counts filers by accession, so a
filer reporting both lines in a transition quarter is counted once).

A CUSIP is accepted for a ticker only when its 13F issuer name matches
the company's current or former SEC name AND one of:

1. OpenFIGI resolves it to the ticker or one of its former tickers, or
2. OpenFIGI no longer resolves it, and it shares the 6-character issuer
   prefix of a CUSIP already accepted by rule 1 (same issuer, new issue
   number, e.g. after a reverse split).

Pure functions only; the network calls live in
`scripts/build_institutional_ownership_cusip_map.py`.
"""

from __future__ import annotations

import json
from typing import Iterable, Mapping, Optional

_TRAILING_TOKENS_TO_STRIP = frozenset({
    "INC", "INCORPORATED", "CORP", "CORPORATION", "CO", "COMPANY", "LTD", "LIMITED",
    "LLC", "PLC", "GROUP", "HOLDINGS", "HOLDING", "COM", "NEW", "DEL",
})


def normalize(text: str) -> str:
    return " ".join("".join(ch for ch in text.upper() if ch.isalnum() or ch.isspace()).split())


def core_name(title: str) -> str:
    """Strips a leading "THE " and trailing corporate-suffix tokens, so
    "Exxon Mobil Corp" and "EXXON MOBIL CORP NEW" both become
    "EXXON MOBIL"."""
    text = normalize(title)
    if text.startswith("THE "):
        text = text[4:]
    tokens = text.split()
    while tokens and tokens[-1] in _TRAILING_TOKENS_TO_STRIP:
        tokens.pop()
    return " ".join(tokens)


def company_names(current_title: str, submissions: Optional[Mapping]) -> list[str]:
    """Core names for the company: today's title plus every
    `formerNames[].name` in its EDGAR submissions summary. Empty cores
    (a title that is all suffixes) are dropped."""
    names = [current_title]
    for former in (submissions or {}).get("formerNames") or []:
        if isinstance(former, Mapping) and former.get("name"):
            names.append(str(former["name"]))
    cores: list[str] = []
    for name in names:
        core = core_name(name)
        if core and core not in cores:
            cores.append(core)
    return cores


def name_matches(issuer_name: str, cores: Iterable[str]) -> bool:
    """Whole-word containment, so "GE" does not match "GENERAL MILLS" and
    "AT&T" style short cores do not match inside longer words."""
    padded = f" {normalize(issuer_name)} "
    return any(f" {core} " in padded for core in cores)


def confirm_cusips(
    candidates_by_ticker: Mapping[str, set[str]],
    resolved: Mapping[str, Optional[str]],
    aliases_by_ticker: Mapping[str, set[str]],
) -> dict[str, list[str]]:
    """Applies the two acceptance rules in the module docstring.
    `resolved` is OpenFIGI's CUSIP -> ticker (None when unresolved);
    `aliases_by_ticker` holds former tickers (the ticker itself is always
    included). A CUSIP accepted for two tickers is dropped from both."""
    accepted: dict[str, set[str]] = {}
    for ticker, cusips in candidates_by_ticker.items():
        names = {ticker} | set(aliases_by_ticker.get(ticker, ()))
        direct = {c for c in cusips if resolved.get(c) in names}
        prefixes = {c[:6] for c in direct}
        inactive = {c for c in cusips if resolved.get(c) is None and c[:6] in prefixes}
        if direct:
            accepted[ticker] = direct | inactive
    owners: dict[str, list[str]] = {}
    for ticker, cusips in accepted.items():
        for c in cusips:
            owners.setdefault(c, []).append(ticker)
    return {
        ticker: sorted(c for c in cusips if len(owners[c]) == 1)
        for ticker, cusips in sorted(accepted.items())
    }


def load_cusip_to_ticker(map_json: str) -> dict[str, str]:
    """Reads the map file. Values are a CUSIP list (ADR-0231) or a single
    CUSIP string (the ADR-0131 format). Raises on a CUSIP claimed by two
    tickers, which would double-count holdings."""
    raw = json.loads(map_json)
    result: dict[str, str] = {}
    for ticker, value in raw.items():
        for cusip in ([value] if isinstance(value, str) else value):
            if cusip in result and result[cusip] != ticker:
                raise ValueError(f"CUSIP {cusip} mapped to both {result[cusip]} and {ticker}")
            result[cusip] = ticker
    return result
