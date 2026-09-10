"""Category: institutional_ownership_change_score factor (Session 36
continued, ADR-0104) -- Chen, Jegadeesh & Wermers 2000 "smart money"
institutional-holdings-change anomaly. Mirrors
`test_short_interest_score.py`'s style, applied to the new SEC Form
13F-sourced factor."""

from __future__ import annotations

import math

from helpers import utc as _utc

from data_infra.institutional_holding_models import InstitutionalHoldingRecord
from data_infra.models import Provenance

from storage.institutional_holding_repository import DuckDBInstitutionalHoldingRepository
from storage_helpers import new_engine

from strategy_research.factor_scores import institutional_ownership_change_score


def _add_quarter(
    repo: DuckDBInstitutionalHoldingRepository, security_id: str, record_id: str, *,
    quarter_end, available_time=None, institutional_shares: float = 1_000_000.0, num_institutions=42,
) -> None:
    repo.add_institutional_holding(
        InstitutionalHoldingRecord(
            security_id=security_id, quarter_end=quarter_end,
            institutional_shares=institutional_shares, num_institutions=num_institutions,
            available_time=available_time or quarter_end,
            ingestion_time=available_time or quarter_end,
            provenance=Provenance(
                source="sec_13f_manual_aggregation", source_dataset=f"sec_13f_manual_aggregation_{security_id}",
                source_record_id=record_id, retrieved_at=available_time or quarter_end, data_version="v1",
            ),
        )
    )


class TestInstitutionalOwnershipChangeScore:
    def test_score_is_the_raw_log_change_not_negated(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInstitutionalHoldingRepository(engine)
        _add_quarter(repo, "AAA", "q1", quarter_end=_utc(2024, 3, 31), available_time=_utc(2024, 5, 15), institutional_shares=1_000_000.0)
        _add_quarter(repo, "AAA", "q2", quarter_end=_utc(2024, 6, 30), available_time=_utc(2024, 8, 14), institutional_shares=1_200_000.0)

        score = institutional_ownership_change_score("AAA", _utc(2024, 9, 1), repo)
        assert score == math.log(1_200_000.0 / 1_000_000.0)

    def test_increasing_ownership_scores_higher_matching_the_more_buying_is_more_attractive_convention(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInstitutionalHoldingRepository(engine)
        _add_quarter(repo, "BUYING", "b1", quarter_end=_utc(2024, 3, 31), available_time=_utc(2024, 5, 15), institutional_shares=1_000_000.0)
        _add_quarter(repo, "BUYING", "b2", quarter_end=_utc(2024, 6, 30), available_time=_utc(2024, 8, 14), institutional_shares=1_500_000.0)
        _add_quarter(repo, "SELLING", "s1", quarter_end=_utc(2024, 3, 31), available_time=_utc(2024, 5, 15), institutional_shares=1_000_000.0)
        _add_quarter(repo, "SELLING", "s2", quarter_end=_utc(2024, 6, 30), available_time=_utc(2024, 8, 14), institutional_shares=700_000.0)

        buying_score = institutional_ownership_change_score("BUYING", _utc(2024, 9, 1), repo)
        selling_score = institutional_ownership_change_score("SELLING", _utc(2024, 9, 1), repo)

        assert buying_score is not None and selling_score is not None
        assert buying_score > selling_score  # more institutional buying -> higher (more attractive) score

    def test_only_one_quarter_known_returns_none(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInstitutionalHoldingRepository(engine)
        _add_quarter(repo, "AAA", "q1", quarter_end=_utc(2024, 6, 30), available_time=_utc(2024, 8, 14))

        assert institutional_ownership_change_score("AAA", _utc(2024, 9, 1), repo) is None

    def test_no_report_at_all_returns_none_not_a_fabricated_score(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInstitutionalHoldingRepository(engine)

        assert institutional_ownership_change_score("AAA", _utc(2024, 9, 1), repo) is None

    def test_zero_prior_quarter_shares_returns_none(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInstitutionalHoldingRepository(engine)
        _add_quarter(repo, "AAA", "q1", quarter_end=_utc(2024, 3, 31), available_time=_utc(2024, 5, 15), institutional_shares=0.0)
        _add_quarter(repo, "AAA", "q2", quarter_end=_utc(2024, 6, 30), available_time=_utc(2024, 8, 14), institutional_shares=1_000_000.0)

        assert institutional_ownership_change_score("AAA", _utc(2024, 9, 1), repo) is None

    def test_a_not_yet_filed_quarter_is_excluded_point_in_time(self, tmp_path) -> None:
        # The look-ahead guard: available AFTER as_of_time must not leak
        # in, exactly like every other point-in-time-critical factor.
        engine = new_engine(tmp_path)
        repo = DuckDBInstitutionalHoldingRepository(engine)
        _add_quarter(repo, "AAA", "q1", quarter_end=_utc(2024, 3, 31), available_time=_utc(2024, 5, 15), institutional_shares=1_000_000.0)
        _add_quarter(repo, "AAA", "q2", quarter_end=_utc(2024, 6, 30), available_time=_utc(2024, 9, 15), institutional_shares=1_500_000.0)

        # As of 2024-09-01, only the Q1 2024-03-31 quarter is known --
        # the Q2 report doesn't become available until 2024-09-15.
        assert institutional_ownership_change_score("AAA", _utc(2024, 9, 1), repo) is None

    def test_different_security_ids_are_isolated(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInstitutionalHoldingRepository(engine)
        _add_quarter(repo, "AAA", "a1", quarter_end=_utc(2024, 3, 31), available_time=_utc(2024, 5, 15), institutional_shares=1_000_000.0)
        _add_quarter(repo, "AAA", "a2", quarter_end=_utc(2024, 6, 30), available_time=_utc(2024, 8, 14), institutional_shares=1_100_000.0)
        _add_quarter(repo, "BBB", "b1", quarter_end=_utc(2024, 3, 31), available_time=_utc(2024, 5, 15), institutional_shares=2_000_000.0)
        _add_quarter(repo, "BBB", "b2", quarter_end=_utc(2024, 6, 30), available_time=_utc(2024, 8, 14), institutional_shares=1_800_000.0)

        aaa_score = institutional_ownership_change_score("AAA", _utc(2024, 9, 1), repo)
        bbb_score = institutional_ownership_change_score("BBB", _utc(2024, 9, 1), repo)
        assert aaa_score == math.log(1_100_000.0 / 1_000_000.0)
        assert bbb_score == math.log(1_800_000.0 / 2_000_000.0)
