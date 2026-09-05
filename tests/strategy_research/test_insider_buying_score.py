"""Category: insider_buying_score factor (Session 36 continued,
ADR-0086) -- Lakonishok & Lee 2001 / Seyhun 1986 net insider-purchase
ratio. Mirrors `test_factor_scores.py::TestSueScore`'s style, applied
to the new SEC Form 4-sourced factor."""

from __future__ import annotations

from helpers import utc as _utc

from data_infra.insider_models import InsiderTransaction
from data_infra.models import Provenance

from storage.insider_repository import DuckDBInsiderRepository
from storage_helpers import new_engine

from strategy_research.factor_scores import insider_buying_score


def _add_transaction(
    repo: DuckDBInsiderRepository, security_id: str, record_id: str, *,
    transaction_date, transaction_code: str, shares: float, is_10b5_1_plan: bool = False,
    available_time=None, acquired_disposed_code: str = None,
) -> None:
    if acquired_disposed_code is None:
        acquired_disposed_code = "A" if transaction_code == "P" else "D"
    repo.add_insider_transaction(
        InsiderTransaction(
            security_id=security_id, reporting_owner_cik="0001000000", reporting_owner_name="Test Insider",
            is_officer=True, is_director=False, is_ten_percent_owner=False, officer_title="CEO",
            transaction_date=transaction_date, transaction_code=transaction_code,
            acquired_disposed_code=acquired_disposed_code, shares=shares, price_per_share=100.0,
            is_10b5_1_plan=is_10b5_1_plan, accession_number=f"ACCN-{record_id}",
            available_time=available_time or transaction_date, ingestion_time=available_time or transaction_date,
            provenance=Provenance(
                source="sec_edgar", source_dataset=f"sec_edgar_form4_{security_id}",
                source_record_id=record_id, retrieved_at=available_time or transaction_date, data_version="v1",
            ),
        )
    )


class TestInsiderBuyingScore:
    def test_pure_net_buying_scores_plus_one(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInsiderRepository(engine)
        _add_transaction(repo, "AAA", "r1", transaction_date=_utc(2024, 3, 1), transaction_code="P", shares=1000.0)

        score = insider_buying_score("AAA", _utc(2024, 6, 1), repo)
        assert score == 1.0

    def test_pure_net_selling_scores_minus_one(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInsiderRepository(engine)
        _add_transaction(repo, "AAA", "r1", transaction_date=_utc(2024, 3, 1), transaction_code="S", shares=1000.0)

        score = insider_buying_score("AAA", _utc(2024, 6, 1), repo)
        assert score == -1.0

    def test_balanced_buying_and_selling_scores_zero(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInsiderRepository(engine)
        _add_transaction(repo, "AAA", "r1", transaction_date=_utc(2024, 3, 1), transaction_code="P", shares=500.0)
        _add_transaction(repo, "AAA", "r2", transaction_date=_utc(2024, 3, 2), transaction_code="S", shares=500.0)

        score = insider_buying_score("AAA", _utc(2024, 6, 1), repo)
        assert score == 0.0

    def test_no_qualifying_transactions_returns_none_not_a_fabricated_zero(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInsiderRepository(engine)

        assert insider_buying_score("AAA", _utc(2024, 6, 1), repo) is None

    def test_rule_10b5_1_purchases_are_excluded(self, tmp_path) -> None:
        # The exact real, directly-observed finding that motivated this
        # exclusion -- a pre-scheduled plan trade must never count.
        engine = new_engine(tmp_path)
        repo = DuckDBInsiderRepository(engine)
        _add_transaction(
            repo, "AAA", "r1", transaction_date=_utc(2024, 3, 1), transaction_code="P",
            shares=1000.0, is_10b5_1_plan=True,
        )

        assert insider_buying_score("AAA", _utc(2024, 6, 1), repo) is None

    def test_rule_10b5_1_sales_are_excluded(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInsiderRepository(engine)
        _add_transaction(
            repo, "AAA", "r1", transaction_date=_utc(2024, 3, 1), transaction_code="S",
            shares=1000.0, is_10b5_1_plan=True,
        )

        assert insider_buying_score("AAA", _utc(2024, 6, 1), repo) is None

    def test_option_exercise_transactions_are_excluded(self, tmp_path) -> None:
        # Code "M" (option exercise) -- compensation mechanics, not a
        # discretionary market trade; must not count toward either leg.
        engine = new_engine(tmp_path)
        repo = DuckDBInsiderRepository(engine)
        _add_transaction(
            repo, "AAA", "r1", transaction_date=_utc(2024, 3, 1), transaction_code="M",
            shares=1000.0, acquired_disposed_code="A",
        )

        assert insider_buying_score("AAA", _utc(2024, 6, 1), repo) is None

    def test_grant_transactions_are_excluded(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInsiderRepository(engine)
        _add_transaction(
            repo, "AAA", "r1", transaction_date=_utc(2024, 3, 1), transaction_code="A",
            shares=1000.0, acquired_disposed_code="A",
        )

        assert insider_buying_score("AAA", _utc(2024, 6, 1), repo) is None

    def test_transaction_outside_the_six_month_window_is_excluded(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInsiderRepository(engine)
        _add_transaction(repo, "AAA", "r1", transaction_date=_utc(2023, 1, 1), transaction_code="P", shares=1000.0)

        assert insider_buying_score("AAA", _utc(2024, 6, 1), repo) is None

    def test_transaction_at_the_six_month_boundary_is_included(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInsiderRepository(engine)
        _add_transaction(repo, "AAA", "r1", transaction_date=_utc(2023, 12, 1), transaction_code="P", shares=1000.0)

        score = insider_buying_score("AAA", _utc(2024, 6, 1), repo)
        assert score == 1.0

    def test_a_not_yet_filed_transaction_is_excluded_point_in_time(self, tmp_path) -> None:
        # The look-ahead guard: filed AFTER as_of_time must not leak in,
        # exactly like every other point-in-time-critical factor here.
        engine = new_engine(tmp_path)
        repo = DuckDBInsiderRepository(engine)
        _add_transaction(
            repo, "AAA", "r1", transaction_date=_utc(2024, 3, 1), transaction_code="P",
            shares=1000.0, available_time=_utc(2024, 7, 1),
        )

        assert insider_buying_score("AAA", _utc(2024, 6, 1), repo) is None

    def test_share_count_weighting_not_transaction_count(self, tmp_path) -> None:
        # One large purchase must outweigh several small sales when the
        # share totals favor buying -- a raw transaction-count ratio
        # would instead show 1 buy vs 3 sells (net negative).
        engine = new_engine(tmp_path)
        repo = DuckDBInsiderRepository(engine)
        _add_transaction(repo, "AAA", "r1", transaction_date=_utc(2024, 3, 1), transaction_code="P", shares=9000.0)
        _add_transaction(repo, "AAA", "r2", transaction_date=_utc(2024, 3, 2), transaction_code="S", shares=100.0)
        _add_transaction(repo, "AAA", "r3", transaction_date=_utc(2024, 3, 3), transaction_code="S", shares=100.0)
        _add_transaction(repo, "AAA", "r4", transaction_date=_utc(2024, 3, 4), transaction_code="S", shares=100.0)

        score = insider_buying_score("AAA", _utc(2024, 6, 1), repo)
        assert score is not None and score > 0.9

    def test_different_security_ids_are_isolated(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInsiderRepository(engine)
        _add_transaction(repo, "AAA", "r1", transaction_date=_utc(2024, 3, 1), transaction_code="P", shares=1000.0)
        _add_transaction(repo, "BBB", "r2", transaction_date=_utc(2024, 3, 1), transaction_code="S", shares=1000.0)

        assert insider_buying_score("AAA", _utc(2024, 6, 1), repo) == 1.0
        assert insider_buying_score("BBB", _utc(2024, 6, 1), repo) == -1.0
