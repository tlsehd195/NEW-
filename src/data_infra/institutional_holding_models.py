"""Institutional holding data model (Session 36 continued -- the
account owner's own idea: "기관투자자 움직임을 추적할 순 없을까?", "can't
we track institutional investor movement?"). SEC Rule 13f-1 requires
every institutional investment manager with >= $100M in qualifying
assets under management to publicly disclose its US equity LONG
holdings quarterly on Form 13F. This model represents one security's
AGGREGATE reported institutional position for one calendar quarter --
summed across every 13F filer that reported a position in it that
quarter -- parallel in spirit to `data_infra.short_interest_models.
ShortInterestRecord` (a security's aggregate reported short position)
rather than to `data_infra.insider_models.InsiderTransaction` (one
person's one trade): Form 13F, unlike Form 4, is filed BY the
institution ABOUT its entire portfolio, not BY (or about) one company,
so there is no natural "one record per company filing" granularity the
way Form 4's own per-issuer index gives insider trading -- the
aggregation across all reporting filers has to happen before a
per-security record like this one is even meaningful.

**The same point-in-time pitfall `ShortInterestRecord`/`InsiderTransaction`
exist to prevent, restated for this data**: a quarter's `quarter_end`
(the date holdings are AS OF) is not when that fact became public. SEC
Rule 13f-1 gives every 13F filer 45 CALENDAR DAYS after a calendar
quarter's end to file -- a hard regulatory deadline, not an estimate --
so `available_time` is never `quarter_end` itself; see
`thirteen_f_available_time` below.

**Why this project does not parse SEC's own real Form 13F bulk
structured data set directly, mirroring `short_interest_models`'s own
stated reasoning verbatim**: this sandboxed session's outbound network
is confirmed blocked to both `www.sec.gov` and `data.sec.gov` this
session (re-verified while researching this factor -- the same class of
blocker `sec_edgar.py`'s own module docstring already documents for
Form 4/company-facts access), so this project has not independently
verified SEC's real quarterly INFOTABLE structured-data-set file byte-
for-byte from a live sample -- only secondary descriptions (a web
search summary, and a real open-source parser's own canonical-field
comment, `dgunning/edgartools`) of the field names SEC publishes, which
agree with each other but are not the same as having seen a real file.
There is also a genuine, separate gap this project has never needed to
solve before: SEC's own 13F data is keyed by CUSIP, and this project's
`SecurityMaster` has never carried a CUSIP field (Form 4/fundamentals/
short-interest data are all already keyed by CIK or `security_id`
directly, needing no CUSIP resolution at all). Guessing either the
exact byte-level file format or a CUSIP-to-`security_id` mapping this
project cannot independently verify would violate this project's "never
fabricate provider capabilities" discipline the same way
`LocalFileDataProvider`'s own docstring already refuses to guess a
CRSP/Nasdaq Data Link bulk-file layout it has never seen. This module
instead defines ONE simple, explicit, project-owned schema
(`data_infra.providers.institutional_holding_file_import`'s
`_REQUIRED_COLUMNS`) that a user's own external preprocessing step
(aggregating SEC's real per-filer CUSIP-keyed 13F data down to one
row per `security_id` per quarter, in an environment that CAN reach
`sec.gov` and already knows the CUSIP for each of its own universe
securities) is responsible for producing -- the identical division of
responsibility `file_import.py`/`short_interest_file_import.py` already
established."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from data_infra.models import Provenance

# SEC Rule 13f-1(a): every Form 13F must be filed "within 45 days after
# the end of" the calendar quarter it covers -- a fixed regulatory
# deadline, not an estimate (unlike `SHORT_INTEREST_DISSEMINATION_LAG_
# DAYS`, which is this project's own conservative rounding of FINRA's
# published dissemination SCHEDULE). Using the deadline itself as the
# available_time lag is deliberately conservative in the OTHER direction
# a look-ahead guard must never err in: some filers file earlier than
# the deadline, so this may occasionally be a few days later than a
# given filer's real filing date -- never earlier, which is the only
# direction that would leak the future.
THIRTEEN_F_FILING_DEADLINE_DAYS = 45


def _require_aware(name: str, value: Optional[datetime]) -> None:
    if value is None:
        return
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{name} must be timezone-aware: {value!r}")


def thirteen_f_available_time(quarter_end: datetime) -> datetime:
    """The conservative, never-too-early `available_time` for an
    aggregate institutional-holding record covering the quarter ending
    `quarter_end` -- see module docstring and
    `THIRTEEN_F_FILING_DEADLINE_DAYS`."""
    _require_aware("quarter_end", quarter_end)
    return quarter_end + timedelta(days=THIRTEEN_F_FILING_DEADLINE_DAYS)


@dataclass(frozen=True)
class InstitutionalHoldingRecord:
    """One security's AGGREGATE reported Form 13F institutional position
    for one calendar quarter -- summed across every 13F filer that
    reported a position in it that quarter, not one filer's individual
    position (see module docstring)."""

    security_id: str
    quarter_end: datetime
    institutional_shares: float
    num_institutions: Optional[int]
    available_time: datetime
    ingestion_time: datetime
    provenance: Provenance

    def __post_init__(self) -> None:
        for name, value in (
            ("quarter_end", self.quarter_end),
            ("available_time", self.available_time),
            ("ingestion_time", self.ingestion_time),
        ):
            _require_aware(f"InstitutionalHoldingRecord.{name}", value)
        if not self.security_id:
            raise ValueError("InstitutionalHoldingRecord.security_id must not be empty")
        if self.institutional_shares < 0:
            raise ValueError("InstitutionalHoldingRecord.institutional_shares must not be negative")
        if self.num_institutions is not None and self.num_institutions < 0:
            raise ValueError("InstitutionalHoldingRecord.num_institutions must not be negative")
        if self.available_time < self.quarter_end:
            # A quarter's aggregate position cannot become public before
            # the date it is as of -- mirrors ShortInterestRecord's
            # identical available_time/settlement_date ordering guard.
            raise ValueError(
                "InstitutionalHoldingRecord.available_time must not be earlier than quarter_end "
                "(a report cannot become public before the date it is as of)"
            )
