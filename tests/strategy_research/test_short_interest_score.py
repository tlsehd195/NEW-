"""Category: short_interest_score factor (Session 36 continued,
ADR-0099) -- Asquith, Pathak & Ritter 2005 short interest anomaly.
Mirrors `test_insider_buying_score.py`'s style, applied to the new
FINRA-sourced factor."""

from __future__ import annotations

from helpers import utc as _utc

from data_infra.models import Provenance
from data_infra.short_interest_models import ShortInterestRecord

from storage.short_interest_repository import DuckDBShortInterestRepository
from storage_helpers import new_engine

from strategy_research.factor_scores import short_interest_score


def _add_report(
    repo: DuckDBShortInterestRepository, security_id: str, record_id: str, *,
    settlement_date, available_time=None, short_interest_quantity: float = 100_000.0,
    average_daily_volume=50_000.0, days_to_cover=2.0,
) -> None:
    repo.add_short_interest(
        ShortInterestRecord(
            security_id=security_id, settlement_date=settlement_date,
            short_interest_quantity=short_interest_quantity, average_daily_volume=average_daily_volume,
            days_to_cover=days_to_cover, available_time=available_time or settlement_date,
            ingestion_time=available_time or settlement_date,
            provenance=Provenance(
                source="finra_manual_export", source_dataset=f"finra_manual_export_{security_id}",
                source_record_id=record_id, retrieved_at=available_time or settlement_date, data_version="v1",
            ),
        )
    )


class TestShortInterestScore:
    def test_score_is_the_negative_of_days_to_cover(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBShortInterestRepository(engine)
        _add_report(repo, "AAA", "r1", settlement_date=_utc(2024, 8, 15), available_time=_utc(2024, 8, 26), days_to_cover=3.5)

        score = short_interest_score("AAA", _utc(2024, 9, 1), repo)
        assert score == -3.5

    def test_higher_days_to_cover_scores_lower(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBShortInterestRepository(engine)
        _add_report(repo, "HIGH", "h1", settlement_date=_utc(2024, 8, 15), available_time=_utc(2024, 8, 26), days_to_cover=8.0)
        _add_report(repo, "LOW", "l1", settlement_date=_utc(2024, 8, 15), available_time=_utc(2024, 8, 26), days_to_cover=1.0)

        high_score = short_interest_score("HIGH", _utc(2024, 9, 1), repo)
        low_score = short_interest_score("LOW", _utc(2024, 9, 1), repo)

        assert high_score is not None and low_score is not None
        assert low_score > high_score  # lower days-to-cover (less crowded short) -> more attractive

    def test_no_report_at_all_returns_none_not_a_fabricated_score(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBShortInterestRepository(engine)

        assert short_interest_score("AAA", _utc(2024, 9, 1), repo) is None

    def test_a_report_missing_days_to_cover_returns_none(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBShortInterestRepository(engine)
        _add_report(repo, "AAA", "r1", settlement_date=_utc(2024, 8, 15), available_time=_utc(2024, 8, 26), days_to_cover=None)

        assert short_interest_score("AAA", _utc(2024, 9, 1), repo) is None

    def test_a_not_yet_disseminated_report_is_excluded_point_in_time(self, tmp_path) -> None:
        # The look-ahead guard: available AFTER as_of_time must not leak
        # in, exactly like every other point-in-time-critical factor.
        engine = new_engine(tmp_path)
        repo = DuckDBShortInterestRepository(engine)
        _add_report(repo, "AAA", "r1", settlement_date=_utc(2024, 8, 15), available_time=_utc(2024, 9, 5), days_to_cover=3.5)

        assert short_interest_score("AAA", _utc(2024, 9, 1), repo) is None

    def test_uses_the_most_recent_available_report(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBShortInterestRepository(engine)
        _add_report(repo, "AAA", "r1", settlement_date=_utc(2024, 7, 31), available_time=_utc(2024, 8, 11), days_to_cover=5.0)
        _add_report(repo, "AAA", "r2", settlement_date=_utc(2024, 8, 15), available_time=_utc(2024, 8, 26), days_to_cover=2.0)

        score = short_interest_score("AAA", _utc(2024, 9, 1), repo)
        assert score == -2.0

    def test_different_security_ids_are_isolated(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBShortInterestRepository(engine)
        _add_report(repo, "AAA", "r1", settlement_date=_utc(2024, 8, 15), available_time=_utc(2024, 8, 26), days_to_cover=2.0)
        _add_report(repo, "BBB", "r2", settlement_date=_utc(2024, 8, 15), available_time=_utc(2024, 8, 26), days_to_cover=6.0)

        assert short_interest_score("AAA", _utc(2024, 9, 1), repo) == -2.0
        assert short_interest_score("BBB", _utc(2024, 9, 1), repo) == -6.0
