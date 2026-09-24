"""Category: guru_consensus_score factor (ADR-0194) -- a curated,
named-filer 13F agreement count. Mirrors
`test_institutional_ownership_change_score.py`'s style, applied to the
new per-filer factor. Uses real CIKs from
`data_infra.tracked_institutional_filers.TRACKED_FILERS` where the
point-in-time registry behavior itself matters (the Scion tests), and
synthetic CIKs elsewhere for isolation from that registry's real
contents changing in the future."""

from __future__ import annotations

from helpers import utc

from data_infra.institutional_holding_models import InstitutionalFilerHoldingRecord
from data_infra.models import Provenance
from data_infra.tracked_institutional_filers import TRACKED_FILERS

from storage.institutional_filer_holding_repository import DuckDBInstitutionalFilerHoldingRepository
from storage_helpers import new_engine

from strategy_research.factor_scores import guru_consensus_score


def _add(
    repo: DuckDBInstitutionalFilerHoldingRepository, security_id: str, filer_cik: str, record_id: str, *,
    quarter_end, available_time=None, shares_held: float = 100_000.0,
) -> None:
    repo.add_institutional_filer_holding(
        InstitutionalFilerHoldingRecord(
            security_id=security_id, filer_cik=filer_cik, quarter_end=quarter_end,
            shares_held=shares_held, available_time=available_time or quarter_end,
            ingestion_time=available_time or quarter_end,
            provenance=Provenance(
                source="sec_13f_tracked_filer_positions", source_dataset=f"sec_13f_tracked_filer_positions_{security_id}",
                source_record_id=record_id, retrieved_at=available_time or quarter_end, data_version="v1",
            ),
        )
    )


# Two of TRACKED_FILERS' real CIKs, used only where the test cares about
# the real registry's own point-in-time contents (Scion's real
# deregistration date).
_BERKSHIRE_CIK = next(f.cik for f in TRACKED_FILERS if f.name == "Berkshire Hathaway Inc")
_SCION_CIK = next(f.cik for f in TRACKED_FILERS if f.name == "Scion Asset Management, LLC")


class TestGuruConsensusScore:
    def test_counts_tracked_filers_with_a_known_positive_position(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInstitutionalFilerHoldingRepository(engine)
        as_of = utc(2020, 1, 1)
        _add(repo, "AAA", _BERKSHIRE_CIK, "r1", quarter_end=utc(2019, 9, 30), available_time=utc(2019, 11, 14), shares_held=1000.0)

        score = guru_consensus_score("AAA", as_of, repo)
        assert score == 1.0

    def test_no_known_positions_but_filers_are_tracked_returns_zero_not_none(self, tmp_path) -> None:
        # A real, meaningful "no consensus" result -- distinct from "no
        # filer was tracked at all", which returns None below.
        engine = new_engine(tmp_path)
        repo = DuckDBInstitutionalFilerHoldingRepository(engine)
        assert guru_consensus_score("AAA", utc(2020, 1, 1), repo) == 0.0

    def test_before_any_tracked_filer_existed_returns_none(self, tmp_path) -> None:
        # Before TRACKED_FILERS' own earliest tracked_from -- nothing
        # this factor could possibly have measured.
        engine = new_engine(tmp_path)
        repo = DuckDBInstitutionalFilerHoldingRepository(engine)
        assert guru_consensus_score("AAA", utc(1990, 1, 1), repo) is None

    def test_a_zero_share_position_does_not_count_as_held(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInstitutionalFilerHoldingRepository(engine)
        _add(repo, "AAA", _BERKSHIRE_CIK, "r1", quarter_end=utc(2019, 9, 30), available_time=utc(2019, 11, 14), shares_held=0.0)

        assert guru_consensus_score("AAA", utc(2020, 1, 1), repo) == 0.0

    def test_a_not_yet_filed_position_is_excluded_point_in_time(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInstitutionalFilerHoldingRepository(engine)
        _add(repo, "AAA", _BERKSHIRE_CIK, "r1", quarter_end=utc(2019, 9, 30), available_time=utc(2019, 12, 1), shares_held=1000.0)

        # available_time is 2019-12-01 -- as of 2019-11-15 it has not
        # been filed yet.
        assert guru_consensus_score("AAA", utc(2019, 11, 15), repo) == 0.0

    def test_more_agreement_scores_higher_matching_the_more_attractive_convention(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInstitutionalFilerHoldingRepository(engine)
        as_of = utc(2020, 1, 1)
        _add(repo, "WIDELY_HELD", _BERKSHIRE_CIK, "r1", quarter_end=utc(2019, 9, 30), available_time=utc(2019, 11, 14), shares_held=1000.0)
        # A second, still-active tracked filer besides Berkshire.
        second_cik = next(f.cik for f in TRACKED_FILERS if f.name == "Pershing Square Capital Management, L.P.")
        _add(repo, "WIDELY_HELD", second_cik, "r2", quarter_end=utc(2019, 9, 30), available_time=utc(2019, 11, 14), shares_held=500.0)
        _add(repo, "SPARSELY_HELD", _BERKSHIRE_CIK, "r3", quarter_end=utc(2019, 9, 30), available_time=utc(2019, 11, 14), shares_held=1000.0)

        widely_held_score = guru_consensus_score("WIDELY_HELD", as_of, repo)
        sparsely_held_score = guru_consensus_score("SPARSELY_HELD", as_of, repo)
        assert widely_held_score > sparsely_held_score

    def test_a_deregistered_filers_last_known_position_is_excluded_after_deregistration(self, tmp_path) -> None:
        # Real, verified event: Scion Asset Management deregistered
        # 2025-11-10 and is no longer a TRACKED_FILERS member as of
        # any as_of_time after that -- its last reported position must
        # not count toward the score for a much-later as_of_time, even
        # though the position record itself would still be point-in-time
        # visible.
        engine = new_engine(tmp_path)
        repo = DuckDBInstitutionalFilerHoldingRepository(engine)
        _add(repo, "AAA", _SCION_CIK, "r1", quarter_end=utc(2025, 6, 30), available_time=utc(2025, 8, 14), shares_held=1000.0)

        before_deregistration = guru_consensus_score("AAA", utc(2025, 9, 1), repo)
        long_after_deregistration = guru_consensus_score("AAA", utc(2026, 6, 1), repo)

        assert before_deregistration == 1.0
        assert long_after_deregistration == 0.0

    def test_different_security_ids_are_isolated(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInstitutionalFilerHoldingRepository(engine)
        as_of = utc(2020, 1, 1)
        _add(repo, "AAA", _BERKSHIRE_CIK, "r1", quarter_end=utc(2019, 9, 30), available_time=utc(2019, 11, 14), shares_held=1000.0)

        assert guru_consensus_score("AAA", as_of, repo) == 1.0
        assert guru_consensus_score("BBB", as_of, repo) == 0.0
