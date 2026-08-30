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
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
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
        SymbolMetadata(symbol=s)
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
        SymbolMetadata(symbol=s)
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
        SymbolMetadata(symbol=s)
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
