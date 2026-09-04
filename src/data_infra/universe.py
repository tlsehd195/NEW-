"""Universe architecture (Phase 24). See
docs/decisions/ADR-0030-universe-architecture.md for the full design
rationale.

This module does NOT replace Phase 1's `UniverseMembership`/
`DataRepository.get_universe(market, universe, as_of_time)` -- that
mechanism is already point-in-time-safe by construction
(`valid_from`/`valid_to` interval membership, "used to support
survivorship-bias-free historical universe queries," Phase 1 spec
section 8) and is reused here unchanged. What this module adds is one
layer above it: a **named, versioned `UniverseDefinition`** with
per-symbol metadata, and converter functions that turn a definition
into the actual `UniverseMembership`/`SecurityMaster` records a
`DataRepository` stores -- so a caller (a script, a test, a future
orchestrator) has exactly one place to look up "what symbols are in
PILOT_UNIVERSE v1" instead of that list being copy-pasted across
multiple files.

**No strategy, backtest, or Paper Trading code in this repository
hardcodes a symbol list.** `strategy_research`'s strategies take
`security_ids: Sequence[str]` as a plain constructor argument (Phase
23, unchanged) -- the CALLER decides what that sequence is, and this
module is now the source callers should use instead of inventing their
own literal tuple (`scripts/ingest_real_market_data.py` and
`tests/strategy_research/*` both do, as of this phase).

**Honesty discipline (instruction section 4/6)**: every `SymbolMetadata`
field below that this session cannot verify against an actual provider
response is left `None` rather than filled from general knowledge --
even a widely-known fact like "AAPL trades on NASDAQ" is left
unconfirmed here, because this module's job is to describe what THIS
SYSTEM has actually verified, not what is true in the world. Once real
ingestion (`scripts/ingest_real_market_data.py`) actually runs against
a live provider and that provider's response includes exchange/sector
data, a future phase should populate these fields from that real
response -- not from this module's authors' background knowledge.

**Session 36 (ADR-0058) fulfilled this promise for `sector`/`exchange`**:
`_REAL_SEC_SECTOR_AND_EXCHANGE` below holds real SEC EDGAR SIC data,
fetched via `scripts/fetch_sector_classifications.py` in the user's own
real environment, not from background knowledge -- the first fields in
this module ever populated from a real provider response. Every symbol
this session did not confirm (`AVB`, whose CIK lookup did not resolve
on that run) is still left `None` via `_real_symbol_metadata`'s own
"unresolved -> honest default" fallback, not silently skipped or
guessed.

**Session 36 continued (ADR-0061) partially fulfills this promise for
`listed_from`**: `_SP500_PIT_CONFIRMED_LISTED_FROM` below holds real
S&P 500 index-membership join dates for 32 symbols, computed by
`scripts/compute_sp500_pit_listed_from.py` from the real, MIT-licensed
`hanshof/sp500_constituents` scrape (ADR-0037). This is a genuine,
real-data-sourced improvement, moving `audit_survivorship`'s
classification of the universes below from `CURRENT-UNIVERSE-ONLY`
toward `PARTIALLY_MITIGATED` -- but it is NOT a claim that
survivorship bias is resolved: every symbol in these universes was
selected because it is a CURRENT holding, so this data can only ever
confirm WHEN a still-surviving symbol joined the index, never restore
a company that was removed and is therefore absent from these universes
entirely (ADR-0037 Decision 3's limitation, unchanged). `listed_to` is
never set from this data -- every one of these symbols is still an
S&P 500 member as of the source dataset's last snapshot, so a
`listed_to` value would be a fabricated delisting. See
`_real_symbol_metadata`'s own docstring for the ticker-vs-corporate-
identity caveat that applies to every `listed_from` value below.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Sequence

from data_infra.enums import InstrumentType, SecurityStatus
from data_infra.models import SecurityMaster, UniverseMembership

# The benchmark symbol is deliberately never a member of any
# UniverseDefinition below -- instruction section 32/13: "전략
# universe와 benchmark를 혼동하지 않는다." SPY is ingested through the
# same DataProvider/PriceBar pipeline as any tradeable symbol (ADR-0025/
# ADR-0026 precedent, unchanged here), but it is tracked as a benchmark
# reference, never included in a UniverseDefinition a strategy would be
# handed as its tradeable security_ids.
BENCHMARK_SYMBOL = "SPY"


@dataclass(frozen=True)
class SymbolMetadata:
    """One symbol's entry in a `UniverseDefinition`. Every field beyond
    `symbol` is optional and defaults to `None` ("not confirmed this
    session") rather than a guessed value -- see module docstring."""

    symbol: str
    exchange: Optional[str] = None
    sector: Optional[str] = None
    market_cap_bucket: Optional[str] = None
    listed_from: Optional[datetime] = None
    listed_to: Optional[datetime] = None
    source: str = "manual_curation"

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("SymbolMetadata.symbol must not be empty")


@dataclass(frozen=True)
class UniverseDefinition:
    """A named, versioned symbol list. `role` is one of `"PILOT"`,
    `"RESEARCH"` -- never `"BENCHMARK"` (the benchmark is
    `BENCHMARK_SYMBOL`, a single symbol tracked separately, not a
    `UniverseDefinition` of its own)."""

    name: str
    version: str
    role: str
    description: str
    symbols: tuple[SymbolMetadata, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("UniverseDefinition.name must not be empty")
        if not self.version:
            raise ValueError("UniverseDefinition.version must not be empty")
        if self.role not in ("PILOT", "RESEARCH"):
            raise ValueError('UniverseDefinition.role must be "PILOT" or "RESEARCH"')
        if not self.symbols:
            raise ValueError("UniverseDefinition.symbols must not be empty")
        ids = [s.symbol for s in self.symbols]
        if len(ids) != len(set(ids)):
            raise ValueError(f"UniverseDefinition {self.name!r} contains a duplicate symbol")
        if BENCHMARK_SYMBOL in ids:
            raise ValueError(
                f"UniverseDefinition {self.name!r} must not include {BENCHMARK_SYMBOL!r} "
                "(the benchmark symbol is tracked separately, never as a tradeable universe member)"
            )

    @property
    def symbol_ids(self) -> tuple[str, ...]:
        return tuple(s.symbol for s in self.symbols)


# Session 36 (ADR-0058) -- REAL, provider-sourced sector/exchange data,
# fetched via `scripts/fetch_sector_classifications.py` against SEC
# EDGAR's `/submissions/` endpoint in the user's own real environment
# on 2026-09-04 (86 of Stage 4's 87 symbols; AVB's ticker-map CIK
# lookup did not resolve on that run, so it is simply absent here --
# not a guess, not a zero). `sector` is the SEC's own SIC classification
# TEXT (`sicDescription`), NOT a GICS sector label -- see
# `SecEdgarFundamentalsProvider.normalize_submissions`'s own docstring
# for why the two taxonomies must not be conflated. Every symbol below
# still keeps `source="manual_curation"` in its own `SymbolMetadata`
# entry (unchanged) -- that field describes this universe's SYMBOL
# SELECTION provenance (hand-curated, per every prior stage's own
# discipline), a genuinely different question from "is this one field's
# VALUE real" that `sector`/`exchange` being provider-sourced answers
# separately. This is the first field in this module ever populated
# from real, verified provider data rather than left `None` -- the
# module's own honesty discipline (see module docstring) is why every
# entry below waited this long rather than being filled from background
# knowledge.
_REAL_SEC_SECTOR_AND_EXCHANGE: dict[str, tuple[str, Optional[str]]] = {
    "AAPL": ("Electronic Computers", "Nasdaq"),
    "MSFT": ("Services-Prepackaged Software", "Nasdaq"),
    "NVDA": ("Semiconductors & Related Devices", "Nasdaq"),
    "AMZN": ("Retail-Catalog & Mail-Order Houses", "Nasdaq"),
    "GOOGL": ("Services-Computer Programming, Data Processing, Etc.", "Nasdaq"),
    "META": ("Services-Computer Programming, Data Processing, Etc.", "Nasdaq"),
    "AVGO": ("Semiconductors & Related Devices", "Nasdaq"),
    "TSLA": ("Motor Vehicles & Passenger Car Bodies", "Nasdaq"),
    "JPM": ("National Commercial Banks", "NYSE"),
    "V": ("Services-Business Services, NEC", "NYSE"),
    "MA": ("Services-Business Services, NEC", "NYSE"),
    "COST": ("Retail-Variety Stores", "Nasdaq"),
    "WMT": ("Retail-Variety Stores", "Nasdaq"),
    "JNJ": ("Pharmaceutical Preparations", "NYSE"),
    "XOM": ("Petroleum Refining", None),
    "CAT": ("Construction Machinery & Equip", "NYSE"),
    "HON": ("Aircraft Engines & Engine Parts", "Nasdaq"),
    "UPS": ("Trucking & Courier Services (No Air)", "NYSE"),
    "BA": ("Aircraft", "NYSE"),
    "UNH": ("Hospital & Medical Service Plans", "NYSE"),
    "PFE": ("Pharmaceutical Preparations", "NYSE"),
    "ABBV": ("Pharmaceutical Preparations", "NYSE"),
    "MRK": ("Pharmaceutical Preparations", "NYSE"),
    "BAC": ("National Commercial Banks", "NYSE"),
    "GS": ("Security Brokers, Dealers & Flotation Companies", "NYSE"),
    "PG": ("Soap, Detergents, Cleang Preparations, Perfumes, Cosmetics", "NYSE"),
    "KO": ("Beverages", "NYSE"),
    "PEP": ("Beverages", "Nasdaq"),
    "HD": ("Retail-Lumber & Other Building Materials Dealers", "NYSE"),
    "MCD": ("Retail-Eating  Places", "NYSE"),
    "NKE": ("Rubber & Plastics Footwear", "NYSE"),
    "CVX": ("Petroleum Refining", "NYSE"),
    "VZ": ("Telephone Communications (No Radiotelephone)", "NYSE"),
    "T": ("Telephone Communications (No Radiotelephone)", "NYSE"),
    "DIS": ("Services-Miscellaneous Amusement & Recreation", "NYSE"),
    "ORCL": ("Services-Prepackaged Software", "NYSE"),
    "IBM": ("Computer & office Equipment", "NYSE"),
    "CSCO": ("Computer Communications Equipment", "Nasdaq"),
    "NEE": ("Electric Services", "NYSE"),
    "PLD": ("Real Estate Investment Trusts", "NYSE"),
    "AMT": ("Real Estate Investment Trusts", "NYSE"),
    "EQIX": ("Real Estate Investment Trusts", "Nasdaq"),
    "SPG": ("Real Estate Investment Trusts", "NYSE"),
    "LIN": ("Industrial Inorganic Chemicals", "Nasdaq"),
    "APD": ("Industrial Inorganic Chemicals", "NYSE"),
    "ECL": ("Soap, Detergents, Cleang Preparations, Perfumes, Cosmetics", "NYSE"),
    "NEM": ("Gold and Silver Ores", "NYSE"),
    "DUK": ("Electric & Other Services Combined", "NYSE"),
    "SO": ("Electric Services", "NYSE"),
    "D": ("Electric Services", "NYSE"),
    "SLB": ("Oil & Gas Field Services, NEC", "NYSE"),
    "COP": ("Petroleum Refining", "NYSE"),
    "MS": ("Security Brokers, Dealers & Flotation Companies", "NYSE"),
    "WFC": ("National Commercial Banks", "NYSE"),
    "AXP": ("Finance Services", "NYSE"),
    "LLY": ("Pharmaceutical Preparations", "NYSE"),
    "TMO": ("Measuring & Controlling Devices, NEC", "NYSE"),
    "ABT": ("Pharmaceutical Preparations", "NYSE"),
    "ADBE": ("Services-Prepackaged Software", "Nasdaq"),
    "CRM": ("Services-Prepackaged Software", "NYSE"),
    "QCOM": ("Radio & Tv Broadcasting & Communications Equipment", "Nasdaq"),
    "LOW": ("Retail-Lumber & Other Building Materials Dealers", "NYSE"),
    "PM": ("Cigarettes", "NYSE"),
    "PSX": ("Petroleum Refining", "NYSE"),
    "VLO": ("Petroleum Refining", "NYSE"),
    "OXY": ("Crude Petroleum & Natural Gas", "NYSE"),
    "WMB": ("Natural Gas Transmission", "NYSE"),
    "KMI": ("Natural Gas Transmission", "NYSE"),
    "GE": ("Electronic & Other Electrical Equipment (No Computer Equip)", "NYSE"),
    "RTX": ("Aircraft Engines & Engine Parts", "NYSE"),
    "LMT": ("Guided Missiles & Space Vehicles & Parts", "NYSE"),
    "DE": ("Farm Machinery & Equipment", "NYSE"),
    "EMR": ("Electronic & Other Electrical Equipment (No Computer Equip)", "NYSE"),
    "AEP": ("Electric Services", None),
    "EXC": ("Electric & Other Services Combined", "Nasdaq"),
    "SRE": ("Gas & Other Services Combined", "NYSE"),
    "XEL": ("Electric & Other Services Combined", "Nasdaq"),
    "ED": ("Electric & Other Services Combined", "NYSE"),
    "O": ("Real Estate Investment Trusts", "NYSE"),
    "PSA": ("Real Estate Investment Trusts", "NYSE"),
    "WELL": ("Real Estate Investment Trusts", "NYSE"),
    "DLR": ("Real Estate Investment Trusts", "NYSE"),
    "SHW": ("Retail-Building Materials, Hardware, Garden Supply", "NYSE"),
    "FCX": ("Metal Mining", "NYSE"),
    "DOW": ("Plastic Materials, Synth Resins & Nonvulcan Elastomers", "NYSE"),
    "NUE": ("Steel Works, Blast Furnaces & Rolling Mills (Coke Ovens)", "NYSE"),
}


# Real S&P 500 index-membership join dates (ADR-0061), computed by
# `scripts/compute_sp500_pit_listed_from.py` from the real, MIT-
# licensed `hanshof/sp500_constituents` scrape (ADR-0037). Only the 32
# symbols (of 87 in RESEARCH_UNIVERSE_STAGE4) for which the source data
# was NOT left-censored -- i.e. the symbol was NOT already present in
# the dataset's very first (1996-01-02) snapshot, so its apparent join
# date is a real, dateable event rather than "unknown, predates the
# dataset." Every one of these 32 symbols is still an S&P 500 member as
# of the source dataset's last snapshot (2025-08-23) -- none has a
# `listed_to` value, since none has actually left the index.
#
# **Ticker-vs-corporate-identity caveat (see module docstring):** this
# dataset tracks TICKER STRINGS, not durable corporate identity. For a
# ticker that changed name, or was newly issued after a merger/spinoff/
# restructuring, `listed_from` reflects when THAT TICKER STRING first
# appeared in an S&P 500 snapshot -- which is not always the same thing
# as "when this business first became part of the S&P 500" (e.g. a
# renamed ticker for an already-included company would show the RENAME
# date here, not the company's true original inclusion date). This
# project does not attempt to classify which of the 32 symbols below
# fall into that category from background knowledge -- doing so without
# a verified source would itself be exactly the fabrication this
# project's discipline forbids. Every value here is a REAL date from a
# REAL, licensed dataset; it is the INTERPRETATION ("this is when the
# company itself joined") that carries this caveat, not the date itself.
_SP500_PIT_CONFIRMED_LISTED_FROM: dict[str, str] = {
    "ABBV": "2013-01-02", "ADBE": "1997-05-06", "AMT": "2007-11-19", "AMZN": "2005-11-21",
    "AVB": "2007-01-10", "AVGO": "2014-05-08", "CRM": "2008-09-15", "DLR": "2016-05-18",
    "DOW": "2023-05-17", "EQIX": "2015-03-23", "GOOGL": "2006-04-03", "GS": "2002-07-22",
    "KMI": "2000-12-12", "LIN": "2018-11-06", "MA": "2008-07-18", "META": "2022-06-09",
    "NVDA": "2001-11-30", "O": "2015-04-07", "PLD": "2003-07-17", "PM": "2008-03-31",
    "PSA": "2005-08-19", "PSX": "2012-05-01", "QCOM": "1999-07-22", "RTX": "2020-04-03",
    "SPG": "2002-06-26", "SRE": "1998-06-29", "TMO": "1997-01-02", "TSLA": "2020-12-21",
    "UPS": "2002-07-22", "V": "2009-12-21", "VLO": "2004-04-29", "WELL": "2009-01-30",
}


def _real_symbol_metadata(symbol: str) -> SymbolMetadata:
    """Builds one `SymbolMetadata` using `_REAL_SEC_SECTOR_AND_EXCHANGE`
    when this symbol was actually resolved (real `sector`/`exchange`),
    or the honest all-`None` default otherwise (e.g. `AVB`, unresolved
    on the fetch run above) -- never a fabricated value for a symbol
    this session did not actually confirm. Separately merges in a real
    `listed_from` from `_SP500_PIT_CONFIRMED_LISTED_FROM` when
    available (ADR-0061) -- an independent data source from `sector`/
    `exchange`, so a symbol can have either, both, or neither
    populated. `listed_to` is never set here (see that dict's own
    comment for why)."""
    found = _REAL_SEC_SECTOR_AND_EXCHANGE.get(symbol)
    sector, exchange = found if found is not None else (None, None)
    listed_from_str = _SP500_PIT_CONFIRMED_LISTED_FROM.get(symbol)
    listed_from = (
        datetime.strptime(listed_from_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if listed_from_str is not None else None
    )
    return SymbolMetadata(symbol=symbol, sector=sector, exchange=exchange, listed_from=listed_from)


# -- PILOT_UNIVERSE v1 -- Phase 22's original 16-symbol US long-term
# pilot universe (docs/operations/MARKET-DATA-PROVIDER.md), preserved
# here unchanged as ONE named, versioned universe -- not the system's
# only possible universe. Every SymbolMetadata field beyond the symbol
# itself is left unconfirmed (None) per this module's honesty
# discipline above.
PILOT_UNIVERSE_V1 = UniverseDefinition(
    name="PILOT_UNIVERSE",
    version="v1",
    role="PILOT",
    description=(
        "Phase 22's original 16-symbol US large-cap pilot universe, selected for "
        "data-pipeline validation and long-term/low-turnover Paper Trading -- not a "
        "claim of index representativeness or survivorship-bias-free construction "
        "(see docs/decisions/ADR-0030-universe-architecture.md section on "
        "survivorship limitations)."
    ),
    symbols=tuple(
        _real_symbol_metadata(s)
        for s in (
            "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AVGO", "TSLA",
            "JPM", "V", "MA", "COST", "WMT", "JNJ", "XOM",
        )
    ),
)

# -- RESEARCH_UNIVERSE -- staged expansion point (instruction section
# 31). Stage 1 is intentionally identical in membership to
# PILOT_UNIVERSE_V1: this session could not verify Tiingo's or Stooq's
# actual free-tier symbol/request limits (both providers' documentation
# domains are themselves network-BLOCKED from this environment, the
# same constraint that blocks real ingestion -- see
# docs/operations/MARKET-DATA-PROVIDER.md). Instruction section 31
# explicitly forbids assuming a limit ("임의로 '50개 가능'이라고
# 가정하지 않는다") -- so Stage 2+ is a documented, ready extension
# point (add more `SymbolMetadata` entries and bump `version`) rather
# than a populated list of unverified additional tickers. A distinct
# name from PILOT_UNIVERSE_V1 lets a caller opt into "the research
# universe, whatever it currently is" without needing to change call
# sites again once Stage 2 is actually populated.
RESEARCH_UNIVERSE_STAGE1 = UniverseDefinition(
    name="RESEARCH_UNIVERSE",
    version="stage1",
    role="RESEARCH",
    description=(
        "Staged expansion point for the research universe (instruction section 31). "
        "Stage 1 is identical to PILOT_UNIVERSE_V1's membership -- provider free-tier "
        "limits are unverifiable from this environment this phase, so no additional "
        "symbols were added. Stage 2 (~30-50 symbols) requires a confirmed provider "
        "limit before population, per this project's own no-guessing discipline."
    ),
    symbols=PILOT_UNIVERSE_V1.symbols,
)

# -- RESEARCH_UNIVERSE Stage 2 -- populated once Stage 1's own stated
# precondition was met: the user's actual Tiingo account dashboard
# confirmed real free-tier limits this session (50 requests/hour,
# 1,000 requests/day, 2.00 GB/month bandwidth) -- the first time in
# this project's history these numbers came from a real confirmed
# source rather than being left UNKNOWN (ADR-0030 discipline).
#
# Purpose, stated precisely: this stage addresses CONCENTRATION RISK
# (PILOT_UNIVERSE_V1 is 15/16 mega-cap tech/growth names, so a walk-
# forward result can be dominated by a handful of outsized movers) --
# it does NOT address survivorship bias. Every symbol below still has
# `listed_from=listed_to=None`, so `audit_survivorship` still correctly
# classifies this universe as `CURRENT-UNIVERSE-ONLY`
# (today's constituents projected across the whole backtest range) --
# no delisted/failed company is included, by construction, same as
# Stage 1. Fixing that is a separate, deliberately deferred decision
# (paid historical-constituent data), not something a wider symbol list
# alone can fix.
#
# Selection criterion, fixed BEFORE any Stage 2 backtest is ever run
# (RULE 0.8 -- never choose or adjust a universe after seeing a
# result): 24 additional, long-established large-cap US companies,
# hand-picked (`source="manual_curation"`, same convention as
# PILOT_UNIVERSE_V1) to cover GICS sectors PILOT_UNIVERSE_V1 under-
# represents or omits (Industrials, Health Care, Utilities, plus more
# breadth in Financials/Staples/Discretionary/Communication Services/
# Energy/Info Tech). This is deliberately NOT presented as "the current
# S&P 500" or "the current Dow" -- this session cannot verify live
# index membership (no network access), and doing so from training-
# data recall would risk stating a stale fact as if it were confirmed,
# which this module's own honesty discipline (see module docstring)
# forbids. It is exactly what PILOT_UNIVERSE_V1 already is: a
# deliberate, disclosed, hand-curated list -- just wider and more
# sector-balanced.
#
# Request-budget arithmetic (decided from the confirmed limits above,
# not guessed): ingestion costs 2 Tiingo requests per symbol (one price
# history fetch, one corporate-actions fetch --
# `scripts/ingest_real_market_data.py`, unmodified). The 16
# PILOT_UNIVERSE_V1 symbols are already ingested in the user's existing
# `--db-path`; only these 24 NEW symbols need fetching. 24 x 2 = 48
# requests, which fits inside the confirmed 50-requests/hour cap in a
# SINGLE hourly window (2-request margin), and is trivial against the
# 1,000/day and 2.00 GB/month caps. No batching/multi-hour split is
# required for this stage.
RESEARCH_UNIVERSE_STAGE2 = UniverseDefinition(
    name="RESEARCH_UNIVERSE",
    version="stage2",
    role="RESEARCH",
    description=(
        "Stage 2 of the research universe (instruction section 31): PILOT_UNIVERSE_V1's "
        "16 symbols plus 24 additional hand-curated large-cap US companies chosen to "
        "reduce mega-cap-tech concentration and broaden GICS sector coverage. Selection "
        "was fixed before any Stage 2 backtest was run (RULE 0.8). Addresses "
        "concentration risk only -- NOT survivorship bias (every symbol still has "
        "listed_from=listed_to=None; see this definition's own module-level comment)."
    ),
    symbols=PILOT_UNIVERSE_V1.symbols
    + tuple(
        _real_symbol_metadata(s)
        for s in (
            # Industrials
            "CAT", "HON", "UPS", "BA",
            # Health Care
            "UNH", "PFE", "ABBV", "MRK",
            # Financials
            "BAC", "GS",
            # Consumer Staples
            "PG", "KO", "PEP",
            # Consumer Discretionary
            "HD", "MCD", "NKE",
            # Energy
            "CVX",
            # Communication Services
            "VZ", "T", "DIS",
            # Information Technology
            "ORCL", "IBM", "CSCO",
            # Utilities
            "NEE",
        )
    ),
)


# -- RESEARCH_UNIVERSE Stage 3 -- built per the user's own explicit
# direction ("네가 프로젝트 완성에 더 가까운 방향으로 진행해줘" --
# proceed in whichever direction brings the project closer to
# completion), after 9 independently-motivated hypotheses tested
# against Stage 2's 40 symbols all failed to reach CANDIDATE (see
# docs/decisions/ADR-0043-ml-first-model.md, docs/research/
# STRATEGY-VALIDATION-REPORT.md Section G). Universe breadth was
# identified as the highest-expected-impact remaining lever: every
# cross-sectional Signal IC/walk-forward result to date has been
# computed over a 39-40-symbol universe, a real, structural limit on
# statistical power distinct from "which model combines the signals" --
# the four levers already tried (regularization, ensembling, caching,
# a longer training window) only ever squeeze more out of that same
# small cross-section.
#
# Same discipline as Stage 2, unchanged: hand-curated
# (`source="manual_curation"`), deliberately NOT presented as "the
# current S&P 500" or any other verified live index membership -- this
# session still has no network access to confirm real index
# constituents, and stating one from training-data recall as if
# verified would violate this module's own honesty discipline (module
# docstring). Selection criterion, fixed BEFORE any Stage 3 backtest is
# ever run (RULE 0.8): 24 additional real, long-established, liquid
# US large/mid-cap companies chosen specifically to cover the two GICS
# sectors Stage 2 has ZERO representation in (Real Estate, Materials)
# and to add depth to its thinnest sector (Utilities, 1 symbol before
# this addition) -- not an arbitrary or convenience list, and not
# re-adjusted after seeing any result from it.
#
# Request-budget arithmetic (reuses Stage 2's own confirmed Tiingo
# free-tier numbers -- 50 requests/hour, 1,000 requests/day, 2.00
# GB/month -- this session cannot re-verify them independently; if the
# user's actual account limits have since changed, re-check before
# running ingestion): 24 new symbols x 2 requests/symbol (price +
# corporate actions, scripts/ingest_real_market_data.py, unmodified)
# = 48 requests, fitting inside the confirmed 50-requests/hour cap in a
# SINGLE hourly window (2-request margin) -- the identical arithmetic
# shape as Stage 2's own addition, deliberately sized to match it
# rather than push past a window boundary this project has not
# verified the ingestion script paces around.
RESEARCH_UNIVERSE_STAGE3 = UniverseDefinition(
    name="RESEARCH_UNIVERSE",
    version="stage3",
    role="RESEARCH",
    description=(
        "Stage 3 of the research universe: Stage 2's 40 symbols plus 24 additional "
        "hand-curated large/mid-cap US companies chosen to add Real Estate and Materials "
        "coverage (both absent from Stage 2) and deepen Utilities (1 symbol before this "
        "addition). Selection was fixed before any Stage 3 backtest was run (RULE 0.8). "
        "Addresses cross-sectional breadth/concentration risk only -- NOT survivorship "
        "bias (every symbol still has listed_from=listed_to=None, same as every prior "
        "stage; see this definition's own module-level comment)."
    ),
    symbols=RESEARCH_UNIVERSE_STAGE2.symbols
    + tuple(
        _real_symbol_metadata(s)
        for s in (
            # Real Estate (absent from Stage 2)
            "PLD", "AMT", "EQIX", "SPG",
            # Materials (absent from Stage 2)
            "LIN", "APD", "ECL", "NEM",
            # Utilities (1 symbol in Stage 2 -- thinnest sector)
            "DUK", "SO", "D",
            # Energy (2 symbols in Stage 2)
            "SLB", "COP",
            # Financials
            "MS", "WFC", "AXP",
            # Health Care
            "LLY", "TMO", "ABT",
            # Information Technology
            "ADBE", "CRM", "QCOM",
            # Consumer Discretionary
            "LOW",
            # Consumer Staples
            "PM",
        )
    ),
)


# -- RESEARCH_UNIVERSE Stage 4 -- built as part of Session 36's
# explicit "전부 다 진행하는건?" 3-part request (universe expansion is
# item #3, alongside factor combination and sector neutralization).
# Same discipline as every prior stage, unchanged: hand-curated
# (`source="manual_curation"`), NOT presented as a verified live index
# membership snapshot.
#
# Selection criterion, fixed BEFORE any Stage 4 backtest is ever run
# (RULE 0.8): deepen the 5 GICS-style sectors Stage 3 leaves thinnest
# among its own explicitly-curated (Stage 2 + Stage 3) additions --
# Energy, Industrials, Utilities, Real Estate, Materials, each sitting
# at exactly 4 explicitly-tracked symbols after Stage 3 (see the
# section comments on Stage 2/Stage 3 above for the per-sector tallies
# this counts). This is not an arbitrary choice: Energy's thinness is
# the DIRECTLY DIAGNOSED root cause of a real finding this same session
# -- `size_score` reaching walk-forward CANDIDATE at top_n=5 turned out
# to be SLB (Energy's only other liquid name besides XOM/CVX at the
# time) supplying 76.3% of its positive TEST PnL, a concentration
# artifact rather than a genuine size effect (`docs/research/
# STRATEGY-VALIDATION-REPORT.md`'s "Phase 33 Addendum" section E). The
# other 4 sectors are included because they are equally thin by the
# same count, not because any of them individually showed a problem --
# this is pre-registered breadth, not a reaction to something observed
# in this stage's own future backtest.
#
# Request-budget arithmetic (reuses the same confirmed Tiingo free-tier
# numbers Stage 2/Stage 3 already established -- 50 requests/hour,
# 1,000 requests/day, 2.00 GB/month; re-check the user's actual account
# limits before running if they may have changed): 24 new symbols x 2
# requests/symbol (price + corporate actions,
# `scripts/ingest_real_market_data.py`, unmodified) = 48 requests,
# fitting inside the confirmed 50-requests/hour cap in a SINGLE hourly
# window -- identical shape to Stage 2's and Stage 3's own additions.
#
# NOT YET the active `RESEARCH_UNIVERSE` binding any script resolves by
# default (`scripts/compute_signal_ic_from_catalog.py`/
# `compute_fundamentals_ic_from_catalog.py`/`run_long_horizon_
# validation.py` all still import `RESEARCH_UNIVERSE_STAGE3` by name)
# -- switching those imports to Stage 4 requires the user to first run
# real ingestion for these 24 new symbols in their own environment
# (this session/environment has no network access to do so), the same
# sequencing every prior stage already followed.
RESEARCH_UNIVERSE_STAGE4 = UniverseDefinition(
    name="RESEARCH_UNIVERSE",
    version="stage4",
    role="RESEARCH",
    description=(
        "Stage 4 of the research universe: Stage 3's 63 symbols plus 24 additional "
        "hand-curated large-cap US companies deepening the 5 sectors Stage 3 leaves "
        "thinnest (Energy, Industrials, Utilities, Real Estate, Materials -- each at 4 "
        "explicitly-curated symbols after Stage 3). Energy specifically was the diagnosed "
        "root cause of a real Session 36 finding: size_score's walk-forward CANDIDATE "
        "result at top_n=5 turned out to be SLB alone supplying 76.3% of its positive TEST "
        "PnL, a concentration artifact rather than a genuine size effect. Selection was "
        "fixed before any Stage 4 backtest was run (RULE 0.8). Addresses cross-sectional "
        "breadth/concentration risk only -- NOT survivorship bias (every symbol still has "
        "listed_from=listed_to=None, same as every prior stage; see this definition's own "
        "module-level comment)."
    ),
    symbols=RESEARCH_UNIVERSE_STAGE3.symbols
    + tuple(
        _real_symbol_metadata(s)
        for s in (
            # Energy (4 symbols after Stage 3 -- the diagnosed SLB
            # concentration root cause; deepened most deliberately)
            "PSX", "VLO", "OXY", "WMB", "KMI",
            # Industrials (4 symbols, unchanged since Stage 2)
            "GE", "RTX", "LMT", "DE", "EMR",
            # Utilities (4 symbols after Stage 3)
            "AEP", "EXC", "SRE", "XEL", "ED",
            # Real Estate (4 symbols, all from Stage 3)
            "O", "PSA", "WELL", "DLR", "AVB",
            # Materials (4 symbols, all from Stage 3)
            "SHW", "FCX", "DOW", "NUE",
        )
    ),
)


def build_universe_memberships(universe: UniverseDefinition, *, valid_from: datetime) -> list[UniverseMembership]:
    """Converts a `UniverseDefinition` into the `UniverseMembership`
    records `DataRepository.add_universe_membership`/`get_universe`
    (Phase 1, unmodified) actually store and query. `valid_from` is the
    caller-supplied fallback point-in-time a membership becomes
    effective when a symbol's own `listed_from` is unconfirmed (`None`)
    -- never `datetime.now()`.

    Phase 29: a symbol whose `SymbolMetadata.listed_from`/`listed_to`
    ARE confirmed uses those real dates instead of the caller's
    uniform `valid_from`/an open-ended `valid_to=None` -- this is what
    makes `DataRepository.get_universe(..., as_of_time=...)` (already
    point-in-time-safe since Phase 1, unmodified here) actually
    survivorship-aware once real historical listing/delisting dates are
    populated: a security delisted before `as_of_time` is correctly
    excluded, one not yet listed is correctly excluded, matching
    `docs/decisions/ADR-0032-security-identity-and-survivorship-aware-universe.md`.
    Every `SymbolMetadata` in this project with `listed_from`/`listed_to`
    still `None` today (e.g. `PILOT_UNIVERSE_V1`) behaves byte-for-byte
    identically to before this change -- this is purely additive."""
    return [
        UniverseMembership(
            security_id=s.symbol, universe=universe.name,
            valid_from=s.listed_from or valid_from, valid_to=s.listed_to,
        )
        for s in universe.symbols
    ]


def build_security_masters(universe: UniverseDefinition, *, valid_from: datetime) -> list[SecurityMaster]:
    """Converts a `UniverseDefinition` into `SecurityMaster` records.
    `exchange` falls back to the literal string `"UNKNOWN"` (a
    `SecurityMaster.exchange: str` field cannot be `None`) whenever a
    symbol's metadata does not carry a confirmed value -- an honest
    sentinel, never a guessed exchange name. `company_id` is a synthetic
    internal key (`f"COMPANY-{symbol}"`, the same convention this
    project's own test helpers already use), not a real external
    company identifier.

    Phase 29: `valid_from`/`valid_to`/`status` now come from the
    symbol's own `listed_from`/`listed_to` when confirmed (see
    `build_universe_memberships` above for the identical rationale) --
    `status` is derived as `DELISTED` when `listed_to` is set, `ACTIVE`
    otherwise. This cannot distinguish `RENAMED`/`MERGED` from a plain
    `DELISTED` from just two dates -- that finer distinction requires an
    explicit provider-confirmed reason this module does not have
    (`SymbolMetadata` carries no such field), so `DELISTED` is used as
    the honest, least-specific-that-is-still-correct default rather
    than guessing a more specific reason."""
    return [
        SecurityMaster(
            security_id=s.symbol,
            ticker=s.symbol,
            exchange=s.exchange or "UNKNOWN",
            currency="USD",
            company_id=f"COMPANY-{s.symbol}",
            instrument_type=InstrumentType.EQUITY,
            valid_from=s.listed_from or valid_from,
            valid_to=s.listed_to,
            status=SecurityStatus.DELISTED if s.listed_to is not None else SecurityStatus.ACTIVE,
        )
        for s in universe.symbols
    ]


def detect_ticker_collisions(security_masters: Sequence[SecurityMaster]) -> list[str]:
    """Phase 29 (instruction sections 8, 20, 57-B): a *legitimate*
    ticker reuse (e.g. ticker "ABC" delisted by company A in 2015, then
    reassigned to unrelated company B in 2019) is two `SecurityMaster`
    records sharing a `ticker` string with NON-overlapping
    `[valid_from, valid_to)` windows -- this is normal and not flagged.
    A genuine *collision* (a data bug: two different `security_id`
    values claiming the same ticker at the same real point in time) is
    two records sharing a `ticker` with OVERLAPPING windows. This
    function returns one human-readable message per overlapping pair
    found; an empty list means no collision was detected. It does not
    itself raise -- callers (ingestion scripts, tests) decide whether a
    finding is fatal."""
    findings: list[str] = []
    by_ticker: dict[str, list[SecurityMaster]] = {}
    for sm in security_masters:
        by_ticker.setdefault(sm.ticker, []).append(sm)

    for ticker, records in by_ticker.items():
        for i in range(len(records)):
            for j in range(i + 1, len(records)):
                a, b = records[i], records[j]
                if a.security_id == b.security_id:
                    continue  # same identity re-listed under an unchanged ticker -- not a collision
                a_end = a.valid_to or datetime.max.replace(tzinfo=a.valid_from.tzinfo)
                b_end = b.valid_to or datetime.max.replace(tzinfo=b.valid_from.tzinfo)
                overlaps = a.valid_from < b_end and b.valid_from < a_end
                if overlaps:
                    findings.append(
                        f"ticker {ticker!r} claimed by both security_id={a.security_id!r} "
                        f"(valid {a.valid_from.isoformat()}..{a.valid_to.isoformat() if a.valid_to else 'open'}) "
                        f"and security_id={b.security_id!r} "
                        f"(valid {b.valid_from.isoformat()}..{b.valid_to.isoformat() if b.valid_to else 'open'}) "
                        "during an overlapping window"
                    )
    return findings


_SurvivorshipClassification = str  # one of the four literal values below, kept as str (not an Enum) since this is a diagnostic report field, not a domain model concept Phase 1 ever defined.


@dataclass(frozen=True)
class SurvivorshipAudit:
    """Phase 31 (instruction section 28): answers the ten survivorship
    diagnostic questions the instruction requires, and produces one of
    four classifications -- never the bare, unqualified claim
    "survivorship bias solved" the instruction explicitly forbids."""

    as_of_time: datetime
    total_securities: int
    active_count: int
    delisted_count: int
    renamed_or_merged_count: int
    ticker_collision_count: int
    ticker_reuse_count: int
    universe_membership_interval_count: int
    permanent_id_percentage: float
    securities_relying_only_on_ticker_percentage: float
    classification: _SurvivorshipClassification
    classification_reason: str


def audit_survivorship(
    universe: UniverseDefinition,
    security_masters: Sequence[SecurityMaster],
    universe_memberships: Sequence,
    *,
    as_of_time: datetime,
) -> SurvivorshipAudit:
    """Answers instruction section 28's ten questions against one
    ingested universe. Takes the ORIGINAL `UniverseDefinition` (not just
    the converted `SecurityMaster` records) because only `SymbolMetadata`
    can honestly distinguish "this security's dates were provider-
    confirmed" from "this security's dates are the uniform caller-
    supplied fallback" -- `SecurityMaster.valid_from`/`valid_to` alone
    cannot tell the two apart once `build_security_masters` has already
    filled the fallback in (Phase 29's `s.listed_from or valid_from`).

    Never fabricates `ticker_changes` -- this project's own
    `build_security_masters` (Phase 29 Decision 2) has no data source
    finer than two dates, so it can never distinguish a genuine
    RENAMED/MERGED event from a plain DELISTED one; `renamed_or_merged_count`
    therefore reports exactly what `SecurityStatus.RENAMED`/`MERGED`
    records exist (currently always 0 for anything this module itself
    builds), documented as a known limitation rather than left silently
    implied to be "no renames happened."""
    total = len(security_masters)
    active = sum(1 for s in security_masters if s.status == SecurityStatus.ACTIVE)
    delisted = sum(1 for s in security_masters if s.status == SecurityStatus.DELISTED)
    renamed_or_merged = sum(
        1 for s in security_masters if s.status in (SecurityStatus.RENAMED, SecurityStatus.MERGED)
    )
    collisions = detect_ticker_collisions(security_masters)

    reuse_count = 0
    by_ticker: dict[str, list[SecurityMaster]] = {}
    for sm in security_masters:
        by_ticker.setdefault(sm.ticker, []).append(sm)
    for records in by_ticker.values():
        distinct_ids = {r.security_id for r in records}
        if len(distinct_ids) > 1:
            reuse_count += len(distinct_ids) - 1  # N distinct identities sharing one ticker => N-1 reuse events

    membership_count = len(universe_memberships)

    # security_id is a permanent identifier by construction in this
    # project's own domain model (Phase 1) -- every SecurityMaster has
    # one, structurally, so this is always 100%. The honest caveat
    # (documented, not hidden) is that build_security_masters currently
    # sets security_id == ticker (Phase 24/29 have not yet wired a
    # provider-confirmed permanent ID distinct from the ticker string),
    # so today's populated data cannot actually survive a ticker reuse
    # by a different company without a human/provider supplying a
    # genuinely distinct security_id.
    permanent_id_percentage = 100.0 if total else 0.0

    confirmed_dates = sum(1 for s in universe.symbols if s.listed_from is not None or s.listed_to is not None)
    relying_only_on_ticker_percentage = (
        100.0 * (len(universe.symbols) - confirmed_dates) / len(universe.symbols) if universe.symbols else 0.0
    )

    if confirmed_dates == 0:
        classification: _SurvivorshipClassification = "CURRENT-UNIVERSE-ONLY"
        reason = (
            "No symbol in this universe carries a provider-confirmed listed_from/listed_to "
            "-- every valid_from/valid_to is the uniform caller-supplied fallback, so this "
            "universe is, in practice, today's constituent list projected across the whole "
            "requested date range, regardless of how many symbols it contains."
        )
    elif confirmed_dates < len(universe.symbols):
        classification = "PARTIALLY_MITIGATED"
        reason = (
            f"{confirmed_dates}/{len(universe.symbols)} symbols carry provider-confirmed "
            "historical dates; the rest still use the uniform fallback and are effectively "
            "current-universe-only within this same dataset."
        )
    elif collisions:
        classification = "PARTIALLY_MITIGATED"
        reason = (
            f"All symbols carry confirmed historical dates, but {len(collisions)} genuine "
            "ticker collision(s) were detected -- unresolved collisions undermine identity "
            "correctness even where dates are confirmed."
        )
    else:
        classification = "PARTIALLY_MITIGATED"
        reason = (
            "All symbols carry provider-confirmed historical dates and no ticker collision "
            "was detected, but permanent identity is not yet distinct from ticker in this "
            "project's own population (security_id == ticker) and delisting-reason "
            "granularity (RENAMED/MERGED vs. plain DELISTED) is not available -- this is not "
            "yet a FULLY_SUPPORTED, CRSP-grade survivorship-bias-free reconstruction."
        )

    return SurvivorshipAudit(
        as_of_time=as_of_time,
        total_securities=total,
        active_count=active,
        delisted_count=delisted,
        renamed_or_merged_count=renamed_or_merged,
        ticker_collision_count=len(collisions),
        ticker_reuse_count=reuse_count,
        universe_membership_interval_count=membership_count,
        permanent_id_percentage=permanent_id_percentage,
        securities_relying_only_on_ticker_percentage=relying_only_on_ticker_percentage,
        classification=classification,
        classification_reason=reason,
    )
