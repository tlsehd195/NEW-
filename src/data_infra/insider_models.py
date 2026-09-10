"""Insider transaction data model (Session 36 continued, ADR-0086) --
SEC Form 4 ("Statement of Changes in Beneficial Ownership") filings,
parallel in spirit to `data_infra.fundamentals_models.FundamentalRecord`
but for a company insider's own reported trades rather than a
financial-statement line item.

**The same point-in-time pitfall `FundamentalRecord` exists to
prevent, restated for this data**: a transaction's `transaction_date`
(when the insider actually traded) is NOT when that fact became public
-- SEC rules require a Form 4 be filed within 2 business days of the
transaction, but "within 2 business days" is not "instantly," and real
filings occasionally arrive later than that. `available_time` is
therefore always the real SEC filing date (the Atom feed's own
`filing-date` field for that accession number), never
`transaction_date` -- a feature computed `as_of` some date between the
trade and the actual filing must never see it, exactly the same rule
`FundamentalRecord.available_time`'s own docstring states for
financial-statement facts.

**Why `is_10b5_1_plan` is its own field, not folded into
`transaction_code`**: Rule 10b5-1 lets an insider pre-schedule trades
months in advance specifically so a later trade cannot be read as
reacting to non-public information at the time it executes. A
Rule 10b5-1 sale/purchase and a genuinely discretionary one share the
same `transaction_code` (e.g. both are Code "S" sales) but are not the
same signal -- the insider-trading literature this project's own
`insider_buying_score` will build on (Lakonishok & Lee 2001; Seyhun
1986) is about DISCRETIONARY trading conveying private information,
which a pre-scheduled 10b5-1 transaction structurally cannot. SEC's
own `aff10b5One` XML field (added to the ownership-document schema in a
2023 rule amendment) is the only place this distinction is directly
observable, so it is preserved here rather than discarded."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from data_infra.models import Provenance


def _require_aware(name: str, value: Optional[datetime]) -> None:
    if value is None:
        return
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{name} must be timezone-aware: {value!r}")


@dataclass(frozen=True)
class InsiderTransaction:
    """One non-derivative transaction row from one Form 4 filing's
    `nonDerivativeTable` (derivative transactions -- options, RSUs --
    are a distinct table this project does not yet parse; see
    `SecEdgarFundamentalsProvider.normalize_form4_document`'s own
    docstring for why non-derivative-only is the deliberate starting
    scope, not an oversight)."""

    security_id: str  # issuer's own trading symbol (issuerTradingSymbol)
    reporting_owner_cik: str
    reporting_owner_name: str
    is_officer: bool
    is_director: bool
    is_ten_percent_owner: bool
    transaction_date: datetime
    transaction_code: str  # SEC Table I code: "P" (open-market purchase), "S" (sale), "A" (grant/award), "M" (option exercise), ...
    acquired_disposed_code: str  # "A" (acquired) or "D" (disposed)
    shares: float
    price_per_share: Optional[float]  # None for codes where SEC does not require a reported price (e.g. some "A" grants)
    is_10b5_1_plan: bool
    accession_number: str  # this filing's unique SEC accession number -- the natural key alongside transaction-row identity
    available_time: datetime  # the real SEC filing date/time -- see module docstring
    ingestion_time: datetime
    provenance: Provenance
    officer_title: Optional[str] = None

    def __post_init__(self) -> None:
        for name, value in (
            ("transaction_date", self.transaction_date),
            ("available_time", self.available_time),
            ("ingestion_time", self.ingestion_time),
        ):
            _require_aware(f"InsiderTransaction.{name}", value)
        if not self.security_id:
            raise ValueError("InsiderTransaction.security_id must not be empty")
        if not self.reporting_owner_cik:
            raise ValueError("InsiderTransaction.reporting_owner_cik must not be empty")
        if not self.transaction_code:
            raise ValueError("InsiderTransaction.transaction_code must not be empty")
        if self.acquired_disposed_code not in ("A", "D"):
            raise ValueError(f"InsiderTransaction.acquired_disposed_code must be 'A' or 'D', got {self.acquired_disposed_code!r}")
        if self.shares < 0:
            raise ValueError("InsiderTransaction.shares must not be negative")
        if self.price_per_share is not None and self.price_per_share < 0:
            raise ValueError("InsiderTransaction.price_per_share must not be negative")
        if self.available_time < self.transaction_date:
            # A filing cannot report a trade that had not yet happened
            # when the filing itself was made -- mirrors
            # FundamentalRecord's identical available_time/period_end
            # ordering guard.
            raise ValueError(
                "InsiderTransaction.available_time must not be earlier than transaction_date "
                "(a filing cannot report a trade that had not yet happened)"
            )
