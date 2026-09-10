"""Category: a general-purpose lookahead-bias audit (Session 36, the
third of 5 items found while comparing this project against an external
repository, dragon1086/prism-insight, per the account owner's "전부
적용" instruction).

**What this is actually testing, precisely stated so it is not read as
broader than it is**: every fundamentals-family repository this project
has (`DuckDBFundamentalsRepository.get_fundamentals`,
`DuckDBInsiderRepository.get_insider_transactions`) already enforces
`available_time <= as_of_time` as a hard SQL `WHERE` clause -- a
STRUCTURAL guard, exactly like `AsOfDataView`'s guard on price/benchmark
data (ADR-0004), already covered by that repository layer's own tests.
A future-dated record physically cannot be returned by those queries no
matter what a calling score function does. So the residual risk this
audit targets is NOT "did the repository forget to filter" -- it is
"does this specific score FUNCTION forward the exact `as_of_time` it
was given into every one of its own sub-queries, rather than some other
value (a stale local variable, a wrong argument position, a hardcoded
date)." This project has hit exactly that class of wiring bug twice
already this session in a different subsystem (the "매매 근거 기록 후
재학습" pipeline, PROJECT_STATUS.md Session 36) -- a bug that a
structural per-repository guard cannot catch by itself, because the
guard only protects a query that is actually given the right time.

**Mechanism**: for a score function that produces a real (non-`None`)
baseline at some `as_of_time`, add exactly one additional record dated
AFTER that `as_of_time`, with a value that would visibly change the
score if it leaked -- then assert the score, recomputed with the exact
same arguments, is unchanged. Reusable across every call shape this
module has (`FundamentalsScoreFn`, `HybridScoreFn`, `UniverseScoreFn`,
and the insider-repository variant of `FundamentalsScoreFn`) via one
shared assertion helper.

**Deliberately NOT exhaustive over every one of the ~28 registered
fundamentals-family score functions in `compute_fundamentals_ic_from_
catalog.py` -- one representative per DISTINCT code path instead**,
stated honestly rather than implied:

- `roe_score` -- the `_fy_ratio`/`_fy_records`/`_latest_fiscal_year_
  value` plumbing shared verbatim by `roa_score`/`net_margin_score`/
  `leverage_score`/`gross_profitability_score`.
- `asset_growth_score` -- the year-over-year `_fy_records` pattern
  (two fiscal years of the same concept), a genuinely different code
  path from a single-period ratio.
- `sue_score` -- `_quarterly_records`, the only quarterly-granularity
  path in this module.
- `insider_buying_score` -- the only score reading a DIFFERENT
  repository type (`DuckDBInsiderRepository`, not
  `DuckDBFundamentalsRepository`) and the only one this module never
  had a dedicated unit test file for at all until now.
- `shareholder_yield_score` -- `HybridScoreFn`: fundamentals AND price
  (`_latest_price`), representative of every hybrid score.
- `quality_minus_junk_score` -- `UniverseScoreFn`: the cross-sectional
  call shape, representative of the 3 universe-level candidates.

A newly-added factor that reuses one of these code paths inherits this
audit's assurance; a genuinely new code path (a new primitive helper,
a new repository type) should get its own entry here, the same
"new candidate needs its own decision" discipline this project already
applies to ADRs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from storage_helpers import new_engine

from data_infra.fundamentals_models import FundamentalRecord
from data_infra.insider_models import InsiderTransaction
from data_infra.models import PriceBar, Provenance
from data_infra.repository import InMemoryDataRepository

from storage.fundamentals_repository import DuckDBFundamentalsRepository
from storage.insider_repository import DuckDBInsiderRepository

from strategy_research.factor_scores import (
    asset_growth_score,
    insider_buying_score,
    quality_minus_junk_score,
    roe_score,
    shareholder_yield_score,
    sue_score,
)


def _utc(y, m, d):
    return datetime(y, m, d, tzinfo=timezone.utc)


def _assert_unaffected_by_a_future_record(compute: Callable[[], object], add_future_record: Callable[[], None]) -> None:
    """The audit's one shared assertion: `compute()` must return the
    exact same value before and after `add_future_record()` adds a
    record dated strictly after the `as_of_time` `compute` uses -- any
    difference is lookahead bias, full stop, regardless of which score
    function or repository is involved."""
    baseline = compute()
    assert baseline is not None, "fixture bug: the baseline score must be real (non-None) for this audit to mean anything"
    add_future_record()
    after = compute()
    assert after == baseline, (
        "score changed after adding a record dated strictly after as_of_time -- lookahead bias "
        f"(baseline={baseline!r}, after={after!r})"
    )


def _fy_record(security_id, record_id, *, concept, value, period_end, available_time=None):
    available_time = available_time or period_end
    return FundamentalRecord(
        security_id=security_id, concept=concept, period_end=period_end, fiscal_year=period_end.year,
        fiscal_period="FY", form_type="10-K", value=value, unit="USD",
        available_time=available_time, ingestion_time=available_time,
        provenance=Provenance(
            source="sec_edgar", source_dataset=f"sec_edgar_companyfacts_{security_id}",
            source_record_id=record_id, retrieved_at=available_time, data_version="v1",
        ),
    )


def _q_record(security_id, record_id, *, concept, value, period_end, available_time=None, fiscal_period="Q2"):
    available_time = available_time or period_end
    return FundamentalRecord(
        security_id=security_id, concept=concept, period_end=period_end, fiscal_year=period_end.year,
        fiscal_period=fiscal_period, form_type="10-Q", value=value, unit="USD",
        available_time=available_time, ingestion_time=available_time,
        provenance=Provenance(
            source="sec_edgar", source_dataset=f"sec_edgar_companyfacts_{security_id}",
            source_record_id=record_id, retrieved_at=available_time, data_version="v1",
        ),
    )


def _price_bar(security_id, record_id, *, close, timestamp):
    return PriceBar(
        security_id=security_id, timestamp=timestamp, open=close, high=close, low=close, close=close,
        volume=1000.0, available_time=timestamp, ingestion_time=timestamp,
        provenance=Provenance(
            source="test_provider", source_dataset=f"test_{security_id}",
            source_record_id=record_id, retrieved_at=timestamp, data_version="v1",
        ),
    )


def _insider_txn(security_id, record_id, *, transaction_date, transaction_code, shares):
    return InsiderTransaction(
        security_id=security_id, reporting_owner_cik="0001000000", reporting_owner_name="Test Insider",
        is_officer=True, is_director=False, is_ten_percent_owner=False, officer_title="CEO",
        transaction_date=transaction_date, transaction_code=transaction_code,
        acquired_disposed_code="A" if transaction_code == "P" else "D",
        shares=shares, price_per_share=50.0, is_10b5_1_plan=False,
        accession_number=f"ACCN-{record_id}", available_time=transaction_date, ingestion_time=transaction_date,
        provenance=Provenance(
            source="sec_edgar", source_dataset=f"sec_edgar_form4_{security_id}",
            source_record_id=record_id, retrieved_at=transaction_date, data_version="v1",
        ),
    )


class TestFyRatioFamilyLookaheadSafety:
    """`roe_score`, representative of `_fy_ratio`/`_fy_records` (also
    `roa_score`/`net_margin_score`/`leverage_score`/
    `gross_profitability_score`)."""

    def test_a_future_fiscal_year_record_does_not_change_the_score(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_fy_record("AAA", "ni", concept="NetIncomeLoss", value=20.0, period_end=_utc(2022, 12, 31)))
        repo.add_fundamental(_fy_record("AAA", "eq", concept="StockholdersEquity", value=100.0, period_end=_utc(2022, 12, 31)))
        as_of_time = _utc(2023, 6, 1)

        def add_future_record() -> None:
            # A dramatically different FY2023 NetIncomeLoss, filed well
            # after as_of_time -- if `_latest_fiscal_year_value` ever
            # forwarded the wrong as_of_time (or none at all) to
            # `get_fundamentals`, this record's later `period_end` would
            # make it win the "most recent" selection and visibly change
            # the ratio.
            repo.add_fundamental(_fy_record(
                "AAA", "ni_future", concept="NetIncomeLoss", value=99999.0,
                period_end=_utc(2023, 12, 31), available_time=_utc(2024, 2, 1),
            ))

        _assert_unaffected_by_a_future_record(
            lambda: roe_score("AAA", as_of_time, repo), add_future_record,
        )


class TestFyYoyFamilyLookaheadSafety:
    """`asset_growth_score` -- a year-over-year `_fy_records` comparison,
    a distinct code path from a single-period ratio."""

    def test_a_future_fiscal_year_record_does_not_change_the_score(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_fy_record("AAA", "assets_2021", concept="Assets", value=500.0, period_end=_utc(2021, 12, 31)))
        repo.add_fundamental(_fy_record("AAA", "assets_2022", concept="Assets", value=600.0, period_end=_utc(2022, 12, 31)))
        as_of_time = _utc(2023, 3, 1)

        def add_future_record() -> None:
            repo.add_fundamental(_fy_record(
                "AAA", "assets_2023_future", concept="Assets", value=9_999_999.0,
                period_end=_utc(2023, 12, 31), available_time=_utc(2024, 2, 1),
            ))

        _assert_unaffected_by_a_future_record(
            lambda: asset_growth_score("AAA", as_of_time, repo), add_future_record,
        )


class TestQuarterlyFamilyLookaheadSafety:
    """`sue_score` -- `_quarterly_records`, the only quarterly-
    granularity code path in this module."""

    def test_a_future_quarterly_record_does_not_change_the_score(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        values = [1.00, 1.05, 1.10, 1.15, 1.10, 1.15, 1.20, 1.25, 1.20, 1.25, 1.30, 1.35]
        for i, value in enumerate(values):
            year = 2020 + i // 4
            month = 3 + 3 * (i % 4)
            repo.add_fundamental(_q_record(
                "AAA", f"eps_{i}", concept="EarningsPerShareDiluted", value=value, period_end=_utc(year, month, 28),
            ))
        as_of_time = _utc(2023, 2, 1)  # after the 12th quarter (period_end 2022-12-28), before any 13th

        def add_future_record() -> None:
            # A wildly different 13th-quarter value, filed after
            # as_of_time -- if leaked, it would enter `_quarterly_
            # records`'s output and shift the trailing-8-diffs window.
            repo.add_fundamental(_q_record(
                "AAA", "eps_future", concept="EarningsPerShareDiluted", value=50.0,
                period_end=_utc(2023, 3, 28), available_time=_utc(2023, 5, 1),
            ))

        _assert_unaffected_by_a_future_record(
            lambda: sue_score("AAA", as_of_time, repo), add_future_record,
        )


class TestInsiderRepositoryLookaheadSafety:
    """`insider_buying_score` -- the only score reading `DuckDBInsider
    Repository` rather than `DuckDBFundamentalsRepository`, and (until
    this audit) the only one in this module with no dedicated unit
    test file of its own at all."""

    def test_a_future_transaction_does_not_change_the_score(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInsiderRepository(engine)
        repo.add_insider_transaction(_insider_txn(
            "AAA", "buy1", transaction_date=_utc(2023, 3, 1), transaction_code="P", shares=100.0,
        ))
        repo.add_insider_transaction(_insider_txn(
            "AAA", "sell1", transaction_date=_utc(2023, 3, 15), transaction_code="S", shares=40.0,
        ))
        as_of_time = _utc(2023, 6, 1)

        def add_future_record() -> None:
            # A large future sale, transacted (and filed) after
            # as_of_time -- if leaked, it would flip the net-purchase
            # ratio's sign.
            repo.add_insider_transaction(_insider_txn(
                "AAA", "sell_future", transaction_date=_utc(2023, 8, 1), transaction_code="S", shares=10_000.0,
            ))

        _assert_unaffected_by_a_future_record(
            lambda: insider_buying_score("AAA", as_of_time, repo), add_future_record,
        )


class TestHybridPriceFamilyLookaheadSafety:
    """`shareholder_yield_score` -- `HybridScoreFn`: reads BOTH a
    fundamentals repository AND a price repository (via `_latest_
    price`), representative of every hybrid score (also
    `earnings_yield_score`/`size_score`/`altman_z_score`/
    `book_to_market_score`/`sales_yield_score`/`cashflow_yield_score`)."""

    def test_a_future_price_bar_does_not_change_the_score(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        fundamentals_repo = DuckDBFundamentalsRepository(engine)
        fundamentals_repo.add_fundamental(_fy_record("AAA", "shares", concept="CommonStockSharesOutstanding", value=1000.0, period_end=_utc(2022, 12, 31)))
        fundamentals_repo.add_fundamental(_fy_record("AAA", "div", concept="PaymentsOfDividends", value=200.0, period_end=_utc(2022, 12, 31)))
        price_repo = InMemoryDataRepository(bars=[_price_bar("AAA", "p1", close=10.0, timestamp=_utc(2023, 5, 25))])
        as_of_time = _utc(2023, 6, 1)

        def add_future_record() -> None:
            # A wildly different future close -- if `_latest_price`
            # forwarded the wrong as_of_time, this would change the
            # market-cap denominator.
            price_repo.append_bars([_price_bar("AAA", "p_future", close=9999.0, timestamp=_utc(2023, 8, 1))])

        _assert_unaffected_by_a_future_record(
            lambda: shareholder_yield_score("AAA", as_of_time, fundamentals_repo, price_repo), add_future_record,
        )


class TestUniverseCrossSectionalFamilyLookaheadSafety:
    """`quality_minus_junk_score` -- `UniverseScoreFn`: the cross-
    sectional call shape (computes every security's score for the whole
    universe at once), representative of the 3 universe-level
    candidates (also `value_composite_score`/`combined_factor_score`)."""

    def test_a_future_record_does_not_change_the_cross_section(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        for security_id in ("GOOD", "JUNK"):
            income = 50.0 if security_id == "GOOD" else 5.0
            repo.add_fundamental(_fy_record(security_id, f"{security_id}:ni", concept="NetIncomeLoss", value=income, period_end=_utc(2022, 12, 31)))
            repo.add_fundamental(_fy_record(security_id, f"{security_id}:eq", concept="StockholdersEquity", value=100.0, period_end=_utc(2022, 12, 31)))
            repo.add_fundamental(_fy_record(security_id, f"{security_id}:liab", concept="Liabilities", value=100.0, period_end=_utc(2022, 12, 31)))
            repo.add_fundamental(_fy_record(security_id, f"{security_id}:cfo", concept="NetCashProvidedByUsedInOperatingActivities", value=60.0, period_end=_utc(2022, 12, 31)))
            repo.add_fundamental(_fy_record(security_id, f"{security_id}:assets_prior", concept="Assets", value=500.0, period_end=_utc(2021, 12, 31)))
            repo.add_fundamental(_fy_record(security_id, f"{security_id}:assets_current", concept="Assets", value=500.0, period_end=_utc(2022, 12, 31)))
        as_of_time = _utc(2023, 6, 1)
        security_ids = ["GOOD", "JUNK"]

        def add_future_record() -> None:
            # A future NetIncomeLoss for GOOD that would, if leaked,
            # dominate the profitability ranking.
            repo.add_fundamental(_fy_record(
                "GOOD", "ni_future", concept="NetIncomeLoss", value=999999.0,
                period_end=_utc(2023, 12, 31), available_time=_utc(2024, 2, 1),
            ))

        _assert_unaffected_by_a_future_record(
            lambda: quality_minus_junk_score(security_ids, as_of_time, repo, price_repository=None),
            add_future_record,
        )
