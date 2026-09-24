"""A curated, point-in-time-aware registry of specific, well-known Form
13F institutional filers ("guru investors") this project tracks for
`strategy_research.factor_scores.guru_consensus_score`.

**Origin**: the account owner's own idea this session, following on from
`institutional_ownership_change_score` (aggregate, ALL filers) --
noting that 13F data also lets a security be scored on how many of a
SPECIFIC, well-known subset of "smart money" investors hold a position
in it ("거물투자자들이 공통적으로 구매하는 기업 찾아서 구매하는 전략은
없지?"). Distinct from `institutional_ownership_change_score`: that
factor aggregates across every 13F filer with no identity at all: this
one deliberately keys on a small, named set of filers chosen for their
long, publicly-documented track records, not filer count or AUM alone.

**Why a registry, not a hardcoded list inline in the factor function**:
the account owner raised the obvious risk directly -- a tracked
investor can retire, close their fund, or die, and the factor must not
require rewriting itself (or, worse, silently keep scoring a fund that
no longer represents anyone's real decisions) when that happens
("그 거물투자자가 사망하거나 이러면 다 바꿔야 할 수도 있으니까
지속적으로 업데이트 가능한 형식으로"). This module is a single,
git-tracked, human-editable list update where that happens: add a new
`TrackedFiler`, or set an existing one's `tracked_until`, in one place;
`factor_scores.py` and every repository/import module never change.

**Why `tracked_from`/`tracked_until`, not a simple `active: bool`
flag**: a plain boolean would leak the future the same way a missing
`available_time` guard would elsewhere in this project -- if a filer is
marked inactive TODAY, a naive boolean check would silently exclude
them from every PAST `as_of_time` too, changing historical backtest
results retroactively the moment someone edits this file. `active_
tracked_filers(as_of_time)` below instead answers "which filers were
being tracked AS OF this specific point in time", so editing this
registry today never changes what a backtest computed for
`as_of_time`s before the edit -- the same point-in-time discipline
`AsOfDataView`/`available_time` apply to the underlying data itself,
applied here to the REGISTRY OF WHO COUNTS as a tracked filer.

**How each filer's CIK was chosen**: this sandboxed session's network
egress to `sec.gov` is confirmed blocked (see `institutional_holding_
models` module docstring), so each entry below was verified instead via
web search against real, dated SEC EDGAR filing URLs and index pages
(never guessed) -- see each `TrackedFiler.note` for what was confirmed
and its evidence. `Scion Asset Management LLC` is a real, already-
observed instance of exactly the scenario the account owner raised:
Michael Burry's fund deregistered with the SEC on 2025-11-10, so its
`tracked_until` is set to that date rather than being removed from this
file entirely -- a backtest run for `as_of_time`s before that date
still sees it as tracked, matching what was actually true then.

**Selection criteria (kept deliberately narrow, RULE 0.8 -- decided
before any factor result exists)**: a fixed, small set of investors with
long (>= 10 years), individually well-documented, publicly-attributed
track records under their own name -- not a byte-count-driven "top N by
13F filing size" list, which would silently include index-fund
managers and market-makers with no active stock-picking thesis at all
(BlackRock, Vanguard, State Street, Citadel Securities, etc. all file
13Fs and would dominate any size-based ranking). Expanding this list
later is expected and fine (see module docstring above); shrinking the
SELECTION CRITERIA to "biggest 13F filers" is not, since that would
just reinvent `institutional_ownership_change_score`'s existing
aggregate-across-everyone signal under a different name."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


def _require_aware(name: str, value: Optional[datetime]) -> None:
    if value is None:
        return
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{name} must be timezone-aware: {value!r}")


@dataclass(frozen=True)
class TrackedFiler:
    """One 13F filer this project tracks by name, not just by CIK --
    `name` exists purely for human readability of this file (never
    used to look up data; all queries key on `cik`, matching
    `data_infra.providers.institutional_holding_file_import`'s own
    CIK-keyed convention)."""

    cik: str
    name: str
    tracked_from: datetime
    tracked_until: Optional[datetime]
    note: str

    def __post_init__(self) -> None:
        if not self.cik:
            raise ValueError("TrackedFiler.cik must not be empty")
        if not self.name:
            raise ValueError("TrackedFiler.name must not be empty")
        _require_aware("TrackedFiler.tracked_from", self.tracked_from)
        _require_aware("TrackedFiler.tracked_until", self.tracked_until)
        if self.tracked_until is not None and self.tracked_until < self.tracked_from:
            raise ValueError(
                f"TrackedFiler({self.name!r}).tracked_until must not be earlier than tracked_from"
            )

    def is_tracked_at(self, as_of_time: datetime) -> bool:
        """Whether this filer counted as "tracked" at `as_of_time` --
        the point-in-time check `active_tracked_filers` uses, and the
        one place a `tracked_until` edit made today changes nothing
        about a backtest for an `as_of_time` before that edit."""
        _require_aware("as_of_time", as_of_time)
        if as_of_time < self.tracked_from:
            return False
        if self.tracked_until is not None and as_of_time > self.tracked_until:
            return False
        return True


# CIKs verified via web search against real, dated SEC EDGAR filing
# URLs/index pages this session (direct sec.gov access confirmed
# blocked -- see module docstring). `tracked_from` for the three still-
# active filers is this project's own `RESEARCH_UNIVERSE_STAGE4` price/
# fundamentals data window start (2010-01-01) -- not each fund's real
# founding date, several of which predate this project's own data
# range and so add nothing `is_tracked_at` could ever observe.
TRACKED_FILERS: tuple[TrackedFiler, ...] = (
    TrackedFiler(
        cik="0001067983",
        name="Berkshire Hathaway Inc",
        tracked_from=datetime(2010, 1, 1, tzinfo=timezone.utc),
        tracked_until=None,
        note=(
            "Warren Buffett. CIK confirmed via web search against real, dated "
            "SEC EDGAR 13F-HR filing index URLs (including a 2026 filing), "
            "e.g. sec.gov/Archives/edgar/data/1067983/... -- still an active "
            "13F filer as of the date this registry was built (2026-09-24)."
        ),
    ),
    TrackedFiler(
        cik="0001336528",
        name="Pershing Square Capital Management, L.P.",
        tracked_from=datetime(2010, 1, 1, tzinfo=timezone.utc),
        tracked_until=None,
        note=(
            "Bill Ackman. CIK confirmed via web search against real, dated "
            "SEC EDGAR 13F-HR filing URLs, e.g. "
            "sec.gov/Archives/edgar/data/1336528/... -- still an active 13F "
            "filer as of the date this registry was built (2026-09-24)."
        ),
    ),
    TrackedFiler(
        cik="0001061768",
        name="Baupost Group LLC/MA",
        tracked_from=datetime(2010, 1, 1, tzinfo=timezone.utc),
        tracked_until=None,
        note=(
            "Seth Klarman. CIK confirmed via web search against real, dated "
            "SEC EDGAR filing history, including a real Q2 2026 13F-HR "
            "filing (filed 2026-08-13) -- still an active 13F filer as of "
            "the date this registry was built (2026-09-24)."
        ),
    ),
    TrackedFiler(
        cik="0001649339",
        name="Scion Asset Management, LLC",
        tracked_from=datetime(2013, 5, 1, tzinfo=timezone.utc),
        tracked_until=datetime(2025, 11, 10, tzinfo=timezone.utc),
        note=(
            "Michael Burry. CIK confirmed via web search against real, dated "
            "SEC EDGAR 13F-HR filing URLs, e.g. "
            "sec.gov/Archives/edgar/data/1649339/... . `tracked_from` is this "
            "entity's own founding (May 2013, per public reporting -- a "
            "DIFFERENT, earlier entity, Scion Capital LLC, CIK 1182422, "
            "closed in 2008 and is deliberately NOT tracked here since its "
            "CIK is not the one filing today's data). `tracked_until` is "
            "2025-11-10, the real, confirmed date Scion Asset Management "
            "deregistered as an investment adviser with the SEC and stopped "
            "filing -- a real, already-observed instance of exactly the "
            "'tracked investor retires' scenario this registry's "
            "tracked_from/tracked_until design exists to handle without "
            "retroactively changing any past as_of_time's result."
        ),
    ),
)


def active_tracked_filers(as_of_time: datetime) -> tuple[TrackedFiler, ...]:
    """Every `TrackedFiler` in `TRACKED_FILERS` that was tracked as of
    `as_of_time` (see `TrackedFiler.is_tracked_at`) -- the point-in-time
    view `guru_consensus_score` reads instead of the raw constant."""
    _require_aware("as_of_time", as_of_time)
    return tuple(filer for filer in TRACKED_FILERS if filer.is_tracked_at(as_of_time))
