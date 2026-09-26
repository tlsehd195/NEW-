"""Pure (no network) parsing/dedup/aggregation logic for SEC's real
BULK Form 13F structured data set -- one ZIP per ~3-month FILING
window (`SUBMISSION.tsv`/`INFOTABLE.tsv` covering EVERY institutional
filer's Information Table submitted in that window), as opposed to
`sec_13f_infotable_parser.py` (one filer's own individual XML filing).

**Real, verified facts this module depends on**
(`scripts/verify_sec_13f_bulk_dataset.py`, 2026-09-26, run
https://github.com/tlsehd195/NEW-/actions/runs/36232909780):

1. **A "window" file is named by FILING date range, not reporting
   quarter** (e.g. `01jun2025-31aug2025_form13f.zip`), and real,
   confirmed URL pattern: `https://www.sec.gov/files/structureddata/
   data/form-13f-data-sets/{DDmonYYYY}-{DDmonYYYY}_form13f.zip`. Real
   confirmed windows tile the calendar year as `01mar-31may`,
   `01jun-31aug`, `01sep-30nov`, `01dec-*feb` (45-day 13F deadline
   pushes each quarter's PRIMARY filings roughly two months later).
2. **One window file's real `PERIODOFREPORT` values span two DECADES**
   (2006 through the window's own filing period, confirmed real: the
   `01jun2025-31aug2025` window contained periods from `31-DEC-2006`
   to `30-JUN-2025`) -- late/amended `13F-HR` filings for old periods
   land in whatever window they were ACTUALLY filed in, not the
   window contemporaneous with the period they report. A single
   recent window is therefore NOT a substitute for a real historical
   backfill across many windows: an old period's coverage in a recent
   window reflects only whichever filers happened to amend that old
   period recently, not that period's true contemporaneous
   institutional coverage (confirmed real and stark: AAPL showed only
   1-2 filers for 2010-2020 periods inside the `01jun2025-31aug2025`
   window, vs. 5,576 filers for the window's own contemporaneous
   `30-JUN-2025` period).
3. **Real, confirmed column names**: `SUBMISSION.tsv` =
   `ACCESSION_NUMBER, FILING_DATE, SUBMISSIONTYPE, CIK, PERIODOFREPORT`.
   `INFOTABLE.tsv` = `ACCESSION_NUMBER, INFOTABLE_SK, NAMEOFISSUER,
   TITLEOFCLASS, CUSIP, FIGI, VALUE, SSHPRNAMT, SSHPRNAMTTYPE, PUTCALL,
   INVESTMENTDISCRETION, OTHERMANAGER, VOTING_AUTH_SOLE,
   VOTING_AUTH_SHARED, VOTING_AUTH_NONE`.
4. **`PERIODOFREPORT` is real-confirmed as `DD-MON-YYYY`** (e.g.
   `30-JUN-2025`). `FILING_DATE`'s own exact format was NOT directly
   observed by that verification run (it printed real column NAMES,
   not a raw `FILING_DATE` value) -- `parse_submission_rows` below
   tries `PERIODOFREPORT`'s own confirmed format first, then two other
   plausible SEC conventions, and raises loudly (never guesses) if
   none parse a real value. Update this docstring once a real backfill
   run confirms which one it actually is.

**Real, disclosed limitation this module's dedup logic addresses**: a
filer can submit an ORIGINAL `13F-HR` and one or more `13F-HR/A`
amendments for the SAME `(CIK, PERIODOFREPORT)`, potentially across
DIFFERENT window files -- summing every submission naively would
double-count. `latest_submission_per_period` keeps only the
latest-`FILING_DATE` submission per `(CIK, PERIODOFREPORT)` (ties
broken by `ACCESSION_NUMBER`, which SEC's own accession-number format
is itself chronologically sortable within one filer) -- this project's
own real, disclosed answer to a well-known real-world 13F data-
engineering problem, not guessed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

# Real, confirmed real URL pattern and 4 fixed filing-window boundaries
# per calendar year (see this module's own docstring, point 1).
_BULK_DATASET_BASE_URL = "https://www.sec.gov/files/structureddata/data/form-13f-data-sets"
_WINDOW_BOUNDARIES = (
    (3, 1, 5, 31),   # 01mar - 31may
    (6, 1, 8, 31),   # 01jun - 31aug
    (9, 1, 11, 30),  # 01sep - 30nov
    (12, 1, 2, 28),  # 01dec - *feb (next year; Feb 29 on a leap year, handled below)
)
_MONTH_ABBR = (
    "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec",
)


def _is_leap_year(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def _fmt(d: date) -> str:
    return f"{d.day:02d}{_MONTH_ABBR[d.month - 1]}{d.year}"


@dataclass(frozen=True)
class FilingWindow:
    start: date
    end: date
    url: str


def generate_filing_windows(first_start_year: int, through_date: date) -> list[FilingWindow]:
    """Every real ~3-month filing window from `01mar<first_start_year>`
    through whichever window covers `through_date`, inclusive -- see
    this module's own docstring point 1 for the real, confirmed URL
    pattern and window boundaries. Never fetches anything -- callers
    decide which of these real URLs to actually download, and must
    handle a 404 for any window SEC has not yet published or never
    published this far back (this module does not itself know how far
    back SEC's real archive goes)."""
    windows: list[FilingWindow] = []
    year = first_start_year
    while True:
        for start_month, start_day, end_month, end_day in _WINDOW_BOUNDARIES:
            start = date(year, start_month, start_day)
            end_year = year + 1 if end_month < start_month else year
            if end_month == 2 and end_day == 28 and _is_leap_year(end_year):
                end_day = 29
            end = date(end_year, end_month, end_day)
            if start > through_date:
                return windows
            windows.append(FilingWindow(start=start, end=end, url=f"{_BULK_DATASET_BASE_URL}/{_fmt(start)}-{_fmt(end)}_form13f.zip"))
        year += 1


_DATE_FORMATS_TO_TRY = ("%d-%b-%Y", "%Y%m%d", "%m/%d/%Y", "%Y-%m-%d")


def _parse_sec_date(raw: str, *, field_name: str) -> date:
    from datetime import datetime as _dt

    raw = raw.strip()
    for fmt in _DATE_FORMATS_TO_TRY:
        try:
            return _dt.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ValueError(
        f"unparseable real SEC {field_name} value {raw!r} -- none of {_DATE_FORMATS_TO_TRY} matched; "
        "this is a real, previously-unobserved format, not a bug in the caller -- update "
        "_DATE_FORMATS_TO_TRY (and this module's own docstring point 4) once confirmed, never guess silently"
    )


@dataclass(frozen=True)
class SubmissionRecord:
    accession_number: str
    cik: str
    period_of_report: date
    filing_date: date
    submission_type: str


def parse_submission_rows(rows: list[dict]) -> list[SubmissionRecord]:
    """13F-HR / 13F-HR/A submissions only (a `13F-NT`/`13F-NT/A` "notice"
    filer reports no holdings and has no real `INFOTABLE.tsv` rows to
    join against anyway) -- real, malformed, or otherwise-unparseable
    date values raise immediately (`ValueError`, never silently
    skipped or defaulted), since a real backfill run silently dropping
    real submissions would understate real institutional coverage
    without any trace."""
    records: list[SubmissionRecord] = []
    for row in rows:
        submission_type = row.get("SUBMISSIONTYPE", "")
        if not submission_type.startswith("13F-HR"):
            continue
        records.append(
            SubmissionRecord(
                accession_number=row["ACCESSION_NUMBER"],
                cik=row["CIK"],
                period_of_report=_parse_sec_date(row["PERIODOFREPORT"], field_name="PERIODOFREPORT"),
                filing_date=_parse_sec_date(row["FILING_DATE"], field_name="FILING_DATE"),
                submission_type=submission_type,
            )
        )
    return records


def latest_submission_per_period(submissions: list[SubmissionRecord]) -> dict[str, date]:
    """`{winning_accession_number: period_of_report}` -- exactly one
    entry per real `(cik, period_of_report)` pair, keeping whichever
    submission has the latest `filing_date` (ties broken by the larger
    `accession_number` string, itself chronologically sortable within
    one filer -- SEC's own real accession-number format is
    `{10-digit-filer-or-agent-CIK}-{2-digit-year}-{6-digit-sequence}`).
    See this module's own docstring for why this dedup exists at all
    (amendments, possibly filed in a LATER window file)."""
    best: dict[tuple[str, date], SubmissionRecord] = {}
    for record in submissions:
        key = (record.cik, record.period_of_report)
        current_best = best.get(key)
        if current_best is None:
            best[key] = record
            continue
        is_better = (record.filing_date, record.accession_number) > (current_best.filing_date, current_best.accession_number)
        if is_better:
            best[key] = record
    return {record.accession_number: period for (_, period), record in best.items()}


@dataclass(frozen=True)
class AggregatedHolding:
    security_id: str
    quarter_end: date
    institutional_shares: float
    num_institutions: int


def aggregate_holdings(
    infotable_rows: list[dict], winning_period_by_accession: dict[str, date], cusip_to_security_id: dict[str, str],
) -> list[AggregatedHolding]:
    """Sums `SSHPRNAMT` and counts distinct `ACCESSION_NUMBER` per
    `(security_id, quarter_end)`, restricted to CUSIPs this caller has
    already resolved to a `security_id` (see `openfigi_cusip_
    resolution`'s real-verified CUSIP->ticker direction) -- never
    attempts to resolve an unknown CUSIP itself, so a full-market
    INFOTABLE.tsv (millions of rows, thousands of distinct CUSIPs) is
    filtered down to only this project's own universe without any
    per-row network call."""
    totals: dict[tuple[str, date], dict[str, object]] = {}
    for row in infotable_rows:
        accession_number = row["ACCESSION_NUMBER"]
        quarter_end = winning_period_by_accession.get(accession_number)
        if quarter_end is None:
            continue  # not a winning (latest) 13F-HR submission -- a superseded amendment or a 13F-NT
        security_id = cusip_to_security_id.get(row.get("CUSIP", "").strip())
        if security_id is None:
            continue  # not one of this project's own known, confirmed securities
        try:
            shares = float(row.get("SSHPRNAMT", 0) or 0)
        except ValueError:
            continue
        key = (security_id, quarter_end)
        entry = totals.setdefault(key, {"shares": 0.0, "filers": set()})
        entry["shares"] += shares  # type: ignore[operator]
        entry["filers"].add(accession_number)  # type: ignore[attr-defined]
    return [
        AggregatedHolding(security_id=sid, quarter_end=qe, institutional_shares=v["shares"], num_institutions=len(v["filers"]))  # type: ignore[arg-type]
        for (sid, qe), v in totals.items()
    ]
