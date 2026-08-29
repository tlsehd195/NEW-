"""Point-in-time S&P 500 index membership from a THIRD-PARTY, MIT-licensed
scrape of Wikipedia's "List of S&P 500 companies" page
(`hanshof/sp500_constituents`, https://github.com/hanshof/sp500_constituents,
verified this session: real MIT LICENSE file, an auditable ~60-line scraper
script with no fabrication, 50+ consecutive real automated commits, and 3
spot-checked facts all correct -- Bear Stearns removed 2008-06-02, Lehman
removed 2008-09-17, Tesla added 2020-12-21).

This module exists because this project's biggest standing data gap
(ADR-0034 Decision 4, `EXTERNAL_DATASET_REQUIRED`) is having no
point-in-time record of S&P 500 membership -- every universe used so
far reflects today's survivors projected backward
(`audit_survivorship` correctly classifies this `CURRENT-UNIVERSE-ONLY`).
This dataset is a real, if imperfect, step toward closing that gap for
S&P 500 membership specifically -- it does NOT provide a full delisted-
securities list across all US exchanges (that candidate,
`BlackFalconData-org/delisted-stocks-list`, was verified this session
to contain no actual data at all, just a paid-product landing page --
rejected).

**Honesty discipline -- read before using this data for anything:**

1. **Not an official source.** The ultimate source is Wikipedia's
   crowd-maintained table, not S&P Global. `Provenance.source` for any
   record built from this module must say exactly that (e.g.
   `"hanshof_sp500_constituents_wikipedia_scrape"`), never something
   that implies official/paid-vendor provenance.

2. **Real, documented coverage gaps -- verified by actually counting
   rows per year in the real file this session:**

   ```
   1996-2018: ~90-133 rows/year (roughly one snapshot every 2-3 trading days)
   2019: 27 rows   2020: 13 rows   2021: 14 rows   2022: 20 rows
   2023: 234 rows  2024: 363 rows  2025: 222 rows (through Aug)
   ```

   2019-2022 is a real, severe gap (the automation was largely dormant
   for ~4 years) that falls squarely inside this project's own
   2010-2026 backtest window. A membership change that happened and
   reversed within one of those gaps would never be captured. Every
   function below reports its own uncertainty explicitly (staleness
   days / censoring flags) rather than silently presenting a stale or
   interpolated answer as precise.

3. **Snapshot rows are NOT one-per-trading-day.** The underlying script
   just appends whatever Wikipedia showed whenever someone happened to
   run it -- there is no daily cron guarantee, confirmed by the uneven
   year-by-year counts above.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional, Sequence

_REQUIRED_COLUMNS = ("date", "tickers")


@dataclass(frozen=True)
class MembershipSnapshot:
    """One row of the source CSV: what the scraper saw the S&P 500's
    membership to be on `as_of` (the scrape date, not necessarily a
    trading day and not necessarily the date any change actually took
    effect)."""

    as_of: date
    tickers: frozenset


def parse_snapshots(csv_path: Path) -> tuple:
    """Parses `sp_500_historical_components.csv` (header `date,tickers`,
    `tickers` a comma-joined ticker string per row) into sorted
    `MembershipSnapshot`s. Raises `ValueError` on a header mismatch --
    never silently guesses a different schema (this project's
    never-fabricate-provider-shape discipline, same as
    `data_infra.providers.file_import`)."""
    rows = []
    with csv_path.open(newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = set(reader.fieldnames or ())
        if not set(_REQUIRED_COLUMNS) <= fieldnames:
            raise ValueError(
                f"expected columns {_REQUIRED_COLUMNS}, got {sorted(fieldnames)}"
            )
        for row in reader:
            as_of = datetime.strptime(row["date"], "%Y-%m-%d").date()
            tickers = frozenset(t for t in row["tickers"].split(",") if t)
            rows.append(MembershipSnapshot(as_of=as_of, tickers=tickers))
    rows.sort(key=lambda s: s.as_of)
    return tuple(rows)


@dataclass(frozen=True)
class MembershipQueryResult:
    """`staleness_days` is the honest signal for how much to trust this
    answer: 0 means the snapshot is dated exactly `as_of_requested`;
    a large number (the 2019-2022 gap can exceed 300) means the true
    membership on `as_of_requested` could differ from `tickers` and the
    caller should weight this answer accordingly, never treat it as
    exact."""

    as_of_requested: date
    snapshot_used: date
    staleness_days: int
    tickers: frozenset


def membership_as_of(
    snapshots: Sequence, as_of: date
) -> Optional[MembershipQueryResult]:
    """Forward-fill: the nearest snapshot at or before `as_of`. Returns
    `None` if `as_of` predates every snapshot -- never fabricates a
    membership answer for a date the data cannot speak to. `snapshots`
    must already be sorted ascending by `as_of` (as `parse_snapshots`
    returns them)."""
    candidate: Optional[MembershipSnapshot] = None
    for snap in snapshots:
        if snap.as_of > as_of:
            break
        candidate = snap
    if candidate is None:
        return None
    return MembershipQueryResult(
        as_of_requested=as_of,
        snapshot_used=candidate.as_of,
        staleness_days=(as_of - candidate.as_of).days,
        tickers=candidate.tickers,
    )


@dataclass(frozen=True)
class ReconstructedMembershipInterval:
    """One ticker's apparent membership span, reconstructed by walking
    the snapshot sequence. `left_censored`/`right_censored` and the two
    `*_uncertainty_days` fields are the honest uncertainty bounds --
    this is deliberately NOT a claim of the exact addition/removal
    date, which this sparse, gapped dataset cannot support.

    `left_censored=True`: the ticker was already present in the very
    FIRST snapshot -- its true addition date is unknown and may predate
    the dataset entirely (`added_uncertainty_days` is 0 and not
    meaningful in this case).

    `right_censored=True`: the ticker was still present in the very
    LAST snapshot -- it may still be a current member, or may have left
    after the dataset's last scrape date; either way its true removal
    date (if any) is unknown (`removed_uncertainty_days` is 0 and not
    meaningful in this case).

    When neither flag is set, `*_uncertainty_days` is the real gap (in
    days) between the snapshot bracketing the ticker's apparent entry/
    exit -- the true event could have happened anywhere in that window.
    """

    ticker: str
    first_seen: date
    last_seen: date
    left_censored: bool
    added_uncertainty_days: int
    right_censored: bool
    removed_uncertainty_days: int


def reconstruct_intervals(snapshots: Sequence) -> tuple:
    """Builds one `ReconstructedMembershipInterval` per ticker that
    appears anywhere in `snapshots`. `snapshots` need not be pre-sorted
    (this function sorts its own working copy)."""
    if not snapshots:
        return ()
    ordered = sorted(snapshots, key=lambda s: s.as_of)
    first_snapshot_date = ordered[0].as_of
    last_snapshot_date = ordered[-1].as_of

    first_seen: dict = {}
    first_seen_gap: dict = {}
    last_seen: dict = {}
    prev: Optional[MembershipSnapshot] = None
    all_tickers: set = set()

    for snap in ordered:
        all_tickers |= snap.tickers
        for t in snap.tickers:
            if t not in first_seen:
                first_seen[t] = snap.as_of
                first_seen_gap[t] = (snap.as_of - prev.as_of).days if prev is not None else 0
            last_seen[t] = snap.as_of
        prev = snap

    results = []
    for t in sorted(all_tickers):
        left_censored = first_seen[t] == first_snapshot_date
        right_censored = last_seen[t] == last_snapshot_date
        removed_gap = 0
        if not right_censored:
            idx = next(i for i, s in enumerate(ordered) if s.as_of == last_seen[t])
            removed_gap = (ordered[idx + 1].as_of - ordered[idx].as_of).days
        results.append(
            ReconstructedMembershipInterval(
                ticker=t,
                first_seen=first_seen[t],
                last_seen=last_seen[t],
                left_censored=left_censored,
                added_uncertainty_days=0 if left_censored else first_seen_gap[t],
                right_censored=right_censored,
                removed_uncertainty_days=removed_gap,
            )
        )
    return tuple(results)
