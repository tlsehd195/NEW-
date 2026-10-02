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

A CUSIP is accepted for a ticker only when, in at least one yearly 13F
file, it is the ticker's DOMINANT line: among share (not principal, not
option) rows whose issuer name matches the company's current or former
SEC name, the valid 9-character CUSIP with the most shares held. The
company's common stock dwarfs its preferreds, notes and misspelled
CUSIPs, so this picks the common line in each era. A dominant CUSIP is
then kept unless OpenFIGI resolves it to a different, unrelated ticker
(a name collision). The first 2026-10-02 build accepted every CUSIP
sharing an issuer prefix and pulled in preferreds, notes and option
lines (43 for AT&T), which this replaces.

Pure functions only; the network calls live in
`scripts/build_institutional_ownership_cusip_map.py`.
"""

from __future__ import annotations

import json
from typing import Iterable, Mapping, Optional

_TRAILING_TOKENS_TO_STRIP = frozenset({
    "INC", "INCORPORATED", "CORP", "CORPORATION", "CO", "COMPANY", "LTD", "LIMITED",
    "LLC", "PLC", "GROUP", "HOLDINGS", "HOLDING", "COM", "NEW", "DEL",
    # EDGAR former names carry a state suffix, e.g. "QUALCOMM INC/DE".
    "DE", "MD", "MN", "NJ", "NY", "PA", "OH", "TX", "CA", "VA", "NC", "GA", "IL", "MA", "WA",
})


def normalize(text: str) -> str:
    """Uppercase; "&" is dropped, any other punctuation becomes a space
    ("INC/DE" -> "INC DE", "AT&T" -> "ATT")."""
    text = text.upper().replace("&", "")
    return " ".join("".join(ch if ch.isalnum() else " " for ch in text).split())


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


def cusip_check_digit_ok(cusip: str) -> bool:
    """Standard CUSIP check digit (modulus 10, double-add-double)."""
    if len(cusip) != 9 or not cusip[8].isdigit():
        return False
    total = 0
    for i, ch in enumerate(cusip[:8]):
        if ch.isdigit():
            v = int(ch)
        elif ch.isalpha():
            v = ord(ch) - ord("A") + 10
        elif ch in "*@#":
            v = {"*": 36, "@": 37, "#": 38}[ch]
        else:
            return False
        if i % 2 == 1:
            v *= 2
        total += v // 10 + v % 10
    return (10 - total % 10) % 10 == int(cusip[8])


def is_share_row(shares_type: str, put_call: str) -> bool:
    """Shares, not a principal amount and not an option position."""
    return not put_call.strip() and shares_type.strip().upper() in ("SH", "")


def is_equity_issue(cusip: str) -> bool:
    """Equity issue numbers (CUSIP characters 7-8) are digits; debt
    issues use letters (Tesla's convertible notes are 88160RAB7 etc.)."""
    return cusip[6:8].isdigit()


def dominant_cusip(shares_by_cusip: Mapping[str, float]) -> Optional[str]:
    """The valid CUSIP with the most shares in one file, or None."""
    valid = {c: v for c, v in shares_by_cusip.items() if cusip_check_digit_ok(c) and is_equity_issue(c) and v > 0}
    if not valid:
        return None
    return max(sorted(valid), key=lambda c: valid[c])


def confirm_cusips(
    dominant_by_ticker: Mapping[str, set[str]],
    resolved: Mapping[str, Optional[str]],
    aliases_by_ticker: Mapping[str, set[str]],
) -> tuple[dict[str, list[str]], dict[str, str]]:
    """Keeps each ticker's per-file dominant CUSIPs unless OpenFIGI
    resolves one to a ticker that is neither this one nor a former one.
    A CUSIP kept for two tickers is dropped from both. Returns the map
    and, per ticker, a note when nothing was kept or when no CUSIP was
    confirmed by OpenFIGI (only unresolved ones were kept)."""
    kept: dict[str, set[str]] = {}
    notes: dict[str, str] = {}
    for ticker, cusips in dominant_by_ticker.items():
        names = {ticker} | set(aliases_by_ticker.get(ticker, ()))
        rejected = {c: resolved.get(c) for c in cusips if resolved.get(c) not in names and resolved.get(c) is not None}
        good = set(cusips) - set(rejected)
        if rejected:
            notes[ticker] = "rejected " + ", ".join(f"{c}->{t}" for c, t in sorted(rejected.items()))
        if good:
            kept[ticker] = good
            if not any(resolved.get(c) in names for c in good):
                notes[ticker] = (notes.get(ticker, "") + "; " if ticker in notes else "") + "kept without OpenFIGI confirmation"
    owners: dict[str, list[str]] = {}
    for ticker, cusips in kept.items():
        for c in cusips:
            owners.setdefault(c, []).append(ticker)
    confirmed = {
        ticker: sorted(c for c in cusips if len(owners[c]) == 1)
        for ticker, cusips in sorted(kept.items())
    }
    return {t: c for t, c in confirmed.items() if c}, notes


def read_overrides(rows: Iterable[Mapping[str, str]]) -> tuple[dict[str, list[str]], dict[str, set[str]]]:
    """Reviewed per-ticker corrections (`sec_13f_cusip_overrides.csv`):
    `predecessor_name` adds an issuer name EDGAR does not list (a new
    CIK took over the seat, e.g. Alphabet from Google), and
    `exclude_cusip` removes a CUSIP that belongs to a different company
    sharing the name (Linde AG before Linde plc)."""
    names: dict[str, list[str]] = {}
    excluded: dict[str, set[str]] = {}
    for row in rows:
        ticker, kind, value = row["ticker"].strip(), row["kind"].strip(), row["value"].strip()
        if kind == "predecessor_name":
            names.setdefault(ticker, []).append(core_name(value))
        elif kind == "exclude_cusip":
            excluded.setdefault(ticker, set()).add(value.upper())
        else:
            raise ValueError(f"unknown override kind {kind!r} for {ticker}")
    return names, excluded


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
