"""Fundamentals data model (Phase 33 -- ADR-0042), parallel to
`data_infra.models` but for financial-statement line items rather than
price bars. Kept in its own module rather than added to `models.py`
directly, since fundamentals data has a point-in-time pitfall price
data does not: `available_time` here is one of the class's own fields
supplied verbatim by the caller, not derivable from anything else on
the record, exactly like `PriceBar.available_time` is -- see the
warning below.

**The pitfall this model exists to prevent**: a company's Q4 2022 net
income is not knowable on 2022-12-31 (the reporting period's own end
date) -- it only becomes public when the 10-K/10-Q *reporting* it is
actually filed with the SEC, typically weeks later. A fundamentals
feature computed `as_of` some date between period-end and the actual
filing date must never see that value, or every backtest using it
leaks the future exactly the way ADR-0004 already prevents for prices.
`FundamentalRecord.available_time` is therefore always the real filing
date/time (SEC EDGAR's own `filed` field), never `period_end` --
`SecEdgarFundamentalsProvider.normalize_company_facts` is the one place
this project maps EDGAR's raw shape onto this rule, mirroring how
`tiingo.py` isolates its own unverified field-mapping assumptions in
one place.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from data_infra.models import Provenance


def _require_aware(name: str, value: Optional[datetime]) -> None:
    # Local copy, not an import from data_infra.models -- this project's
    # established convention (data_infra.repository, storage.data_repository,
    # broker.live.*, broker.paper.performance all keep their own copy
    # rather than sharing one across modules).
    if value is None:
        return
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{name} must be timezone-aware: {value!r}")


@dataclass(frozen=True)
class FundamentalRecord:
    """One financial-statement line item observation (e.g. one
    company's `Revenues` for fiscal year 2022, as reported in its
    10-K). `concept` is the raw XBRL/us-gaap tag name (e.g.
    `"Revenues"`, `"NetIncomeLoss"`, `"Assets"`) -- kept as the
    provider's own vocabulary rather than mapped onto a project-defined
    enum, since only a small, task-driven subset of the thousands of
    XBRL concepts a filing can carry will ever be consumed by this
    project, and a rigid full enum is not yet justified by a concrete
    need (same reasoning ADR-0039 already applied to a portfolio-
    optimization library and `CorporateAction.details` already applied
    to event-type payload fields)."""

    security_id: str
    concept: str
    period_end: datetime
    fiscal_year: int
    fiscal_period: str  # "FY", "Q1", "Q2", "Q3", "Q4" -- SEC EDGAR's own `fp` field
    form_type: str  # "10-K", "10-Q", ...
    value: float
    unit: str  # "USD", "shares", "USD/shares", ...
    available_time: datetime  # the actual SEC filing date/time -- see module docstring
    ingestion_time: datetime
    provenance: Provenance
    period_start: Optional[datetime] = None  # None for instant concepts (e.g. balance-sheet items); set for duration concepts (e.g. income-statement items)

    def __post_init__(self) -> None:
        for name, value in (
            ("period_end", self.period_end),
            ("period_start", self.period_start),
            ("available_time", self.available_time),
            ("ingestion_time", self.ingestion_time),
        ):
            _require_aware(f"FundamentalRecord.{name}", value)
        if not self.security_id:
            raise ValueError("FundamentalRecord.security_id must not be empty")
        if not self.concept:
            raise ValueError("FundamentalRecord.concept must not be empty")
        if not self.form_type:
            raise ValueError("FundamentalRecord.form_type must not be empty")
        if self.available_time < self.period_end:
            # A filing cannot report on a period that had not yet ended
            # when the filing itself was made -- catches a normalize()
            # bug (e.g. accidentally swapping filed/period fields)
            # before it ever reaches storage, mirroring PriceBar's own
            # available_time/publication_time ordering guard.
            raise ValueError(
                "FundamentalRecord.available_time must not be earlier than period_end "
                "(a filing cannot report on a period that had not yet ended)"
            )
