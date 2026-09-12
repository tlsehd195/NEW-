"""Builds `SecurityMaster` records for securities whose real price
history already exists in a `DataRepository` but which have no
`SecurityMaster` of their own -- exactly the state `scripts/import_
external_market_data.py --symbols` (used for ADR-0126/ADR-0128's 59
recovered delisted tickers) leaves behind: real bars are persisted,
but `repository.get_security(...)` returns `None` for them, since that
script only builds `SecurityMaster` records when run in `--universe`
mode (`build_security_masters`, `data_infra.universe`).

Deliberately derives `valid_from`/`valid_to` from the security's own
REAL PERSISTED BARS (first/last bar timestamp), never from a different
dataset's dates -- an S&P 500 index MEMBERSHIP interval
(`data_infra.providers.sp500_index_constituent_history`) measures a
different concept (was this ticker a member of an INDEX, not whether
the security was LISTED/traded at all). Conflating the two would be
exactly the kind of value-mislabeling this project's discipline
forbids elsewhere (`ADR-0125` Decision 3's identical reasoning for
`averageShortShareNumber` vs. `average_daily_volume`).

Every record built here has `status=SecurityStatus.DELISTED` -- this
module's only intended use is backfilling securities already known to
have stopped trading; a still-active security should go through the
normal `data_infra.universe.build_security_masters` path instead,
which this function does not replace or modify.

`exchange`/`company_id` follow `build_security_masters`'s own,
identical honest-sentinel convention (`exchange="UNKNOWN"`,
`company_id=f"COMPANY-{security_id}"`) -- no real exchange data exists
for these tickers in either `ADR-0126` (Quandl WIKI Prices has no
exchange field) or `ADR-0128` (FMP's `historical-price-eod/full`
response also carries no exchange field)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Sequence

from data_infra.enums import InstrumentType, SecurityStatus
from data_infra.models import SecurityMaster


def build_delisted_security_masters_from_bars(
    repository,
    security_ids: Sequence[str],
    *,
    price_history_start: datetime,
    as_of_time: datetime,
) -> list[SecurityMaster]:
    """For each `security_id`, queries `repository.get_bars(security_id,
    price_history_start, as_of_time, as_of_time)` (the same generic
    `get_bars` protocol `price_data_coverage_for_removed_securities`
    already relies on) and, if any real bar exists, builds one
    `SecurityMaster` spanning the earliest to the latest observed bar.
    `valid_to` is set one day PAST the last real bar's own timestamp --
    matching this project's project-wide EXCLUSIVE `valid_to`/`valid_from`
    convention (`UniverseMembership.valid_to`/`SecurityMaster.valid_to`
    both documented elsewhere as `[valid_from, valid_to)`) -- so the
    security's own real last trading day itself still correctly reads
    as valid, not excluded by an off-by-one boundary error.

    A `security_id` with zero real bars is silently skipped (not an
    error) -- this function only ever backfills securities this
    project can already show real data for; it never fabricates a
    record for one it cannot."""
    records: list[SecurityMaster] = []
    for security_id in security_ids:
        bars = repository.get_bars(security_id, price_history_start, as_of_time, as_of_time)
        if not bars:
            continue
        timestamps = [b.timestamp for b in bars]
        valid_from = min(timestamps)
        valid_to = max(timestamps) + timedelta(days=1)
        records.append(
            SecurityMaster(
                security_id=security_id,
                ticker=security_id,
                exchange="UNKNOWN",
                currency="USD",
                company_id=f"COMPANY-{security_id}",
                instrument_type=InstrumentType.EQUITY,
                valid_from=valid_from,
                valid_to=valid_to,
                status=SecurityStatus.DELISTED,
            )
        )
    return records
