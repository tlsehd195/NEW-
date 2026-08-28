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
