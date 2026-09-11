"""Point-in-time S&P 500 index constituent history from a THIRD-PARTY,
MIT-licensed dataset (`fja05680/sp500`,
https://github.com/fja05680/sp500), verified this session via
WebFetch/WebSearch plus a direct HTTPS fetch of the real file
(`raw.githubusercontent.com` is reachable from this sandboxed session,
unlike every commercial market-data provider host -- the same
GitHub-only-reachability finding ADR-0037/ADR-0061 already established
for `hanshof/sp500_constituents`).

This module complements (does not replace)
`data_infra.providers.sp500_pit_membership` (ADR-0037):

- `hanshof/sp500_constituents` is raw scraped SNAPSHOTS (date,
  ticker-set) requiring uncertainty-windowed reconstruction, with a
  severe 2019-2022 coverage gap (documented in that module).
- `fja05680/sp500`'s `sp500_ticker_start_end.csv` is the maintainer's
  OWN already-reconstructed per-ticker join/leave INTERVALS
  (`ticker,start_date,end_date`), actively maintained through the
  present (commit history verified through 2026-09-07 this session),
  and -- critically -- includes tickers that have LEFT the index
  entirely (a real `end_date`). This is exactly the "historical index
  constituent universe" concept ADR-0033 Decision 1 named as "not
  modeled by this project at all": every `UniverseDefinition` built so
  far (`PILOT_UNIVERSE_V1`/`RESEARCH_UNIVERSE_STAGE*`) only ever
  contains TODAY's current holdings, annotated (ADR-0061) with a
  confirmed join date for the subset still present -- it never
  includes a ticker that left the index and is therefore absent from
  those lists entirely. `constituents_as_of` below is the first
  primitive in this project that can answer "which tickers were index
  members on this historical date" without that current-survivor bias.

**Cross-verified against `hanshof/sp500_constituents`'s own confirmed
fact this session**: ADR-0061 flagged `META`'s confirmed
`listed_from=2022-06-09` as "very plausibly the FB->META ticker
rename, not Facebook's original 2013 index addition" but declined to
assert it without a verified source. This dataset independently
confirms it exactly: `FB` has `end_date=2022-06-09` and `META` has
`start_date=2022-06-09` in the same file -- two independent
third-party sources now agree on the same date for the same event.

**Honesty discipline -- read before using this data for anything:**

1. **Not an official source.** Single-maintainer (`fja05680`),
   cross-references Wikipedia's "Selected Changes" section with
   independent research; the maintainer's own README states Wikipedia's
   changes list is incomplete ("You can't reconstruct the past with
   only the Wikipedia changes mentioned") and that the earliest years
   (1996-2001) undercounted constituents (487 vs. the standard ~500,
   "no way to independently check"). `Provenance.source` for any
   record built from this module must say exactly
   `"fja05680_sp500_ticker_start_end"`, never implying an official S&P
   Global source.
2. **A ticker can appear multiple times** (re-entered the index after
   leaving -- e.g. `AAL`: 1996-01-02 to 1997-01-15, then 2015-03-23 to
   2024-09-23). `parse_ticker_intervals` returns every interval,
   never collapses or picks only one.
3. **`end_date` empty means still a current member** as of the source
   file's last update -- represented as `end_date=None`, never a
   fabricated date.
4. **`start_date` for a ticker already present at the dataset's very
   first row (1996-01-02, e.g. `GE`) is left-censored** -- it is the
   dataset's own coverage start, not that ticker's real S&P 500 join
   date (GE has been a member since long before 1996). This module
   does not flag left-censoring explicitly (unlike
   `sp500_pit_membership.reconstruct_intervals`, which does) -- a
   caller treating every `start_date == 1996-01-02` as a real join
   date would be wrong; this caveat is the enforcement point until a
   future phase adds an explicit flag.
5. **Ticker-keyed, not corporate-identity-keyed** -- identical caveat
   `sp500_pit_membership.py`/ADR-0061 already documented: a ticker
   rename (e.g. `FB`->`META`) looks like one ticker leaving and a
   different one joining, not the same company continuing.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional, Sequence

_REQUIRED_COLUMNS = ("ticker", "start_date", "end_date")


@dataclass(frozen=True)
class TickerMembershipInterval:
    """One contiguous span during which `ticker` was an S&P 500
    constituent. `end_date=None` means still a member as of the source
    file's last update -- never inferred to mean "removed today"."""

    ticker: str
    start_date: date
    end_date: Optional[date]

    def __post_init__(self) -> None:
        if not self.ticker:
            raise ValueError("TickerMembershipInterval.ticker must not be empty")
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError(
                f"TickerMembershipInterval for {self.ticker!r}: end_date {self.end_date} "
                f"before start_date {self.start_date}"
            )

    def contains(self, as_of: date) -> bool:
        if as_of < self.start_date:
            return False
        if self.end_date is not None and as_of > self.end_date:
            return False
        return True


def parse_ticker_intervals(csv_path: Path) -> tuple[TickerMembershipInterval, ...]:
    """Parses `sp500_ticker_start_end.csv` (header `ticker,start_date,
    end_date`). Raises `ValueError` on a header mismatch -- never
    silently guesses a different schema (this project's
    never-fabricate-provider-shape discipline, same as
    `data_infra.providers.file_import`/`sp500_pit_membership`)."""
    rows: list[TickerMembershipInterval] = []
    with csv_path.open(newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = set(reader.fieldnames or ())
        if not set(_REQUIRED_COLUMNS) <= fieldnames:
            raise ValueError(f"expected columns {_REQUIRED_COLUMNS}, got {sorted(fieldnames)}")
        for row in reader:
            ticker = row["ticker"].strip()
            start_date = datetime.strptime(row["start_date"].strip(), "%Y-%m-%d").date()
            end_raw = row["end_date"].strip()
            end_date = datetime.strptime(end_raw, "%Y-%m-%d").date() if end_raw else None
            rows.append(TickerMembershipInterval(ticker=ticker, start_date=start_date, end_date=end_date))
    rows.sort(key=lambda r: (r.ticker, r.start_date))
    return tuple(rows)


def constituents_as_of(intervals: Sequence[TickerMembershipInterval], as_of: date) -> frozenset:
    """Every ticker that was an index member on `as_of`, INCLUDING
    tickers no longer in today's index if `as_of` falls inside one of
    their historical membership intervals -- the capability
    `sp500_pit_membership.membership_as_of` cannot offer, since that
    module only ever answers from the nearest snapshot's CURRENT
    ticker set at that snapshot date, not this file's pre-computed,
    continuously-valid intervals. Returns an empty frozenset (never
    `None`) for a date outside every interval -- an empty answer is
    still a real, meaningful answer here (unlike
    `sp500_pit_membership.membership_as_of`, which returns `None` for
    a date predating the dataset because THAT source genuinely has no
    snapshot to forward-fill from)."""
    return frozenset(iv.ticker for iv in intervals if iv.contains(as_of))


def history_for_ticker(
    intervals: Sequence[TickerMembershipInterval], ticker: str
) -> tuple[TickerMembershipInterval, ...]:
    """All membership intervals for one ticker (0, 1, or more -- a
    ticker can leave and re-enter the index), sorted ascending by
    `start_date`."""
    return tuple(sorted((iv for iv in intervals if iv.ticker == ticker), key=lambda iv: iv.start_date))


def removed_since(
    intervals: Sequence[TickerMembershipInterval], since: date
) -> tuple[TickerMembershipInterval, ...]:
    """Every interval whose `end_date` falls on or after `since` and is
    not `None` -- i.e., tickers that left the index at some point on or
    after `since`. This is the query that actually surfaces the class
    of survivorship bias `audit_survivorship` (`universe.py`) cannot
    detect on its own: a ticker that left the index and is therefore
    simply absent from every `UniverseDefinition` this project builds.
    Sorted ascending by `end_date`."""
    return tuple(
        sorted(
            (iv for iv in intervals if iv.end_date is not None and iv.end_date >= since),
            key=lambda iv: iv.end_date,
        )
    )
