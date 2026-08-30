"""Category: signal predictiveness (Information Coefficient) diagnostic
-- added following a comparison against `quantopian/alphalens`.
Verifies the rank-correlation math directly with hand-computable
values, then end-to-end against `LongTermMomentumStrategy`'s own real
`_momentum_score` on synthetic TRENDUP/TRENDDOWN series (reusing
`research_helpers.synthetic_multi_year_repository`, same fixture
`test_long_term_momentum.py` already uses -- SYNTHETIC/PIPELINE-VALIDATION
ONLY, never real strategy evidence, per that module's own docstring)."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from research_helpers import synthetic_multi_year_repository

from storage_helpers import new_engine

from data_infra.fundamentals_models import FundamentalRecord
from data_infra.models import Provenance

from storage.fundamentals_repository import DuckDBFundamentalsRepository

from strategy_research.long_term_momentum import LongTermMomentumParameters, LongTermMomentumStrategy
from strategy_research.signal_ic import (
    _pearson,
    rank_average,
    bucket_return_analysis,
    compute_fundamentals_ic_series,
    compute_ic_series,
    spearman_ic,
)
from strategy_research.trend_volatility import TrendVolatilityParameters, TrendVolatilityStrategy


def _utc(y, m, d):
    return datetime(y, m, d, tzinfo=timezone.utc)


class TestRank:
    def test_strictly_increasing_values_get_sequential_ranks(self) -> None:
        assert rank_average([10.0, 20.0, 30.0]) == [1.0, 2.0, 3.0]

    def test_descending_input_still_ranks_by_value_not_position(self) -> None:
        assert rank_average([30.0, 10.0, 20.0]) == [3.0, 1.0, 2.0]

    def test_tied_values_get_the_average_of_their_ranks(self) -> None:
        # Two values tied for ranks 1-2 -> both get 1.5; the top value gets rank 3.
        assert rank_average([5.0, 5.0, 9.0]) == [1.5, 1.5, 3.0]


class TestPearson:
    def test_perfect_positive_correlation_is_one(self) -> None:
        assert _pearson([1.0, 2.0, 3.0], [10.0, 20.0, 30.0]) == 1.0

    def test_perfect_negative_correlation_is_minus_one(self) -> None:
        assert _pearson([1.0, 2.0, 3.0], [30.0, 20.0, 10.0]) == -1.0

    def test_constant_series_returns_none_not_a_fabricated_value(self) -> None:
        assert _pearson([1.0, 1.0, 1.0], [5.0, 6.0, 7.0]) is None

    def test_fewer_than_two_points_returns_none(self) -> None:
        assert _pearson([1.0], [1.0]) is None


class TestSpearmanIc:
    def test_perfectly_aligned_rankings_give_ic_of_one(self) -> None:
        scores = {"A": 1.0, "B": 2.0, "C": 3.0}
        forward_returns = {"A": 0.01, "B": 0.02, "C": 0.03}
        assert spearman_ic(scores, forward_returns) == 1.0

    def test_perfectly_inverted_rankings_give_ic_of_minus_one(self) -> None:
        scores = {"A": 1.0, "B": 2.0, "C": 3.0}
        forward_returns = {"A": 0.03, "B": 0.02, "C": 0.01}
        assert spearman_ic(scores, forward_returns) == -1.0

    def test_only_matches_securities_present_in_both_dicts(self) -> None:
        scores = {"A": 1.0, "B": 2.0, "C": 3.0, "EXTRA_IN_SCORES": 99.0}
        forward_returns = {"A": 0.01, "B": 0.02, "C": 0.03, "EXTRA_IN_RETURNS": -5.0}
        assert spearman_ic(scores, forward_returns) == 1.0

    def test_fewer_than_two_common_securities_returns_none(self) -> None:
        assert spearman_ic({"A": 1.0}, {"A": 0.01}) is None
        assert spearman_ic({"A": 1.0, "B": 2.0}, {"B": 0.01}) is None


class TestComputeIcSeriesAgainstRealMomentumScore:
    """End-to-end: uses the ACTUAL `LongTermMomentumStrategy._momentum_score`
    (production code, not a fake scorer) against a deterministic
    synthetic TRENDUP/TRENDDOWN/CYCLICAL universe -- a signal that is
    genuinely, structurally predictive here (TRENDUP's trailing return
    is always higher, and its forward return continues to be higher,
    since the synthetic series has no mean reversion) must show a
    strongly positive mean IC. This is the same kind of known-labeled
    validation `pbo_dsr.py`'s own tests use before trusting the
    machinery on anything real."""

    def test_genuinely_predictive_signal_produces_ic_of_one(self) -> None:
        # TRENDUP/TRENDDOWN only (no CYCLICAL): with just 2 securities
        # whose relative rank never flips (TRENDUP's trailing AND
        # forward return are always higher), IC must be exactly 1.0 at
        # every rebalance date -- the cleanest possible positive case.
        universe = ("TRENDUP", "TRENDDOWN")
        repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)
        strategy = LongTermMomentumStrategy(
            list(universe), LongTermMomentumParameters(lookback_months=6, top_n=1, rebalance_months=3)
        )
        rebalance_dates = [_utc(2021, m, 1) for m in (3, 6, 9)] + [_utc(2022, m, 1) for m in (3, 6)]

        summary = compute_ic_series(
            list(universe), rebalance_dates, strategy._momentum_score, repo, horizon_days=60
        )

        assert summary.mean_ic == 1.0
        assert summary.positive_ic_ratio == 1.0
        assert len(summary.observations) == len(rebalance_dates)

    def test_a_confounding_third_security_can_produce_a_partial_ic(self) -> None:
        # Adding CYCLICAL's oscillation changes rank order between it
        # and TRENDDOWN at some dates -- a real, honestly-computed
        # partial IC (neither the 3-item perfect 1.0 nor a fabricated
        # 0.0), demonstrating this module does not silently round a
        # partial signal to "perfectly predictive." The exact value
        # below (-1/6) reflects _momentum_score's trim_to_lookback fix
        # (strategy_research/_dates.py): the momentum window is now the
        # precisely-sized trailing `lookback_months`, not the wider,
        # unstrimmed padded fetch a prior version of this test was
        # written against -- CYCLICAL's rank relative to TRENDDOWN over
        # that corrected window differs from before, which is expected
        # (a real signal-window bug fix changing a downstream numeric
        # result), not a regression.
        universe = ("TRENDUP", "TRENDDOWN", "CYCLICAL")
        repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)
        strategy = LongTermMomentumStrategy(
            list(universe), LongTermMomentumParameters(lookback_months=6, top_n=1, rebalance_months=3)
        )
        rebalance_dates = [_utc(2021, m, 1) for m in (3, 6, 9)]

        summary = compute_ic_series(
            list(universe), rebalance_dates, strategy._momentum_score, repo, horizon_days=60
        )

        assert summary.mean_ic == -1 / 6
        assert -1.0 < summary.mean_ic < 1.0  # partial, not a clean extreme

    def test_no_rebalance_dates_produces_empty_summary_not_a_fabricated_zero(self) -> None:
        universe = ("TRENDUP", "TRENDDOWN")
        repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2021, 1, 3), symbols=universe)
        strategy = LongTermMomentumStrategy(list(universe))

        summary = compute_ic_series(list(universe), [], strategy._momentum_score, repo, horizon_days=30)

        assert summary.observations == ()
        assert summary.mean_ic is None
        assert summary.ic_information_ratio is None
        assert summary.positive_ic_ratio is None

    def test_score_never_sees_data_past_its_own_as_of_time(self) -> None:
        """Regression guard for the module's core safety property: the
        score computation must stay point-in-time-safe even though this
        module's forward-return check deliberately is not. Verified
        indirectly -- a score computed at an early rebalance date must
        be identical whether or not later dates are also evaluated
        (proving no cross-date leakage through a shared/mutated view)."""
        universe = ("TRENDUP", "TRENDDOWN")
        repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)
        strategy = LongTermMomentumStrategy(list(universe), LongTermMomentumParameters(lookback_months=6))
        early_date = _utc(2021, 3, 1)

        summary_alone = compute_ic_series(
            list(universe), [early_date], strategy._momentum_score, repo, horizon_days=30
        )
        summary_with_later = compute_ic_series(
            list(universe), [early_date, _utc(2022, 3, 1)], strategy._momentum_score, repo, horizon_days=30
        )

        assert summary_alone.observations[0].ic == summary_with_later.observations[0].ic


def _fixed_filter(passing_ids: frozenset):
    def _filter(security_id, as_of_time, data) -> bool:
        return security_id in passing_ids
    return _filter


class TestBucketReturnAnalysis:
    """Boolean-filter analog of IC -- for a filter like
    `TrendVolatilityStrategy._passes_filter` that has no continuous
    score for Spearman IC to apply to. Compares mean forward returns
    of the filter-passing group vs. the filter-failing group."""

    def test_hand_computable_spread_with_a_fixed_filter(self) -> None:
        universe = ("TRENDUP", "TRENDDOWN")
        repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)
        filter_fn = _fixed_filter(frozenset({"TRENDUP"}))
        rebalance_dates = [_utc(2021, 3, 1), _utc(2021, 6, 1)]

        summary = bucket_return_analysis(list(universe), rebalance_dates, filter_fn, repo, horizon_days=30)

        assert summary.dates_with_both_groups == 2
        assert summary.mean_passing_return is not None  # TRENDUP group
        assert summary.mean_failing_return is not None  # TRENDDOWN group
        # TRENDUP trends up, TRENDDOWN trends down -- the filter that
        # always picks TRENDUP must show a positive spread.
        assert summary.mean_spread == pytest.approx(summary.mean_passing_return - summary.mean_failing_return)
        assert summary.mean_spread > 0
        assert summary.positive_spread_ratio == 1.0

    def test_a_real_strategy_filter_favoring_the_uptrend_security_shows_a_positive_spread(self) -> None:
        universe = ("TRENDUP", "TRENDDOWN")
        repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)
        strategy = TrendVolatilityStrategy(
            list(universe), TrendVolatilityParameters(trend_lookback_months=6, vol_threshold=0.45)
        )
        rebalance_dates = [_utc(2021, m, 1) for m in (3, 6, 9)]

        summary = bucket_return_analysis(
            list(universe), rebalance_dates, strategy._passes_filter, repo, horizon_days=30
        )

        assert summary.dates_with_both_groups > 0
        assert summary.mean_spread is not None
        assert summary.mean_spread > 0

    def test_no_rebalance_dates_produces_empty_summary_not_a_fabricated_zero(self) -> None:
        universe = ("TRENDUP", "TRENDDOWN")
        repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2021, 1, 3), symbols=universe)
        summary = bucket_return_analysis(list(universe), [], _fixed_filter(frozenset()), repo, horizon_days=30)
        assert summary.observations == ()
        assert summary.mean_spread is None
        assert summary.dates_with_both_groups == 0

    def test_a_date_where_everything_fails_the_filter_is_excluded_from_aggregate_but_recorded(self) -> None:
        universe = ("TRENDUP", "TRENDDOWN")
        repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)
        filter_fn = _fixed_filter(frozenset())  # nothing ever passes
        rebalance_dates = [_utc(2021, 3, 1)]

        summary = bucket_return_analysis(list(universe), rebalance_dates, filter_fn, repo, horizon_days=30)

        assert len(summary.observations) == 1
        assert summary.observations[0].passing_mean_return is None
        assert summary.observations[0].passing_count == 0
        assert summary.dates_with_both_groups == 0
        assert summary.mean_spread is None  # not fabricated as 0


def _fundamental_record(security_id, record_id, *, value, available_time, fiscal_period="FY", concept="NetIncomeLoss"):
    return FundamentalRecord(
        security_id=security_id, concept=concept, period_end=available_time, fiscal_year=available_time.year,
        fiscal_period=fiscal_period, form_type="10-K", value=value, unit="USD",
        available_time=available_time, ingestion_time=available_time,
        provenance=Provenance(
            source="sec_edgar", source_dataset=f"sec_edgar_companyfacts_{security_id}",
            source_record_id=record_id, retrieved_at=available_time, data_version="v1",
        ),
    )


class TestComputeFundamentalsIcSeries:
    """`compute_fundamentals_ic_series` -- the fundamentals analog of
    `compute_ic_series`, added for Phase 33's ROE factor (ADR-0042).
    Unlike `compute_ic_series`, scoring and forward-return computation
    read from two SEPARATE repositories (fundamentals are ingested into
    their own catalog, entirely separate from price data's)."""

    def test_wiring_a_hand_rolled_score_fn_produces_ic_of_one(self) -> None:
        # Proves the plumbing (two repositories, no AsOfDataView needed
        # for the fundamentals side) independent of any real factor's
        # own correctness -- mirrors compute_ic_series's own
        # "genuinely predictive signal produces ic of 1" style test.
        universe = ("TRENDUP", "TRENDDOWN")
        price_repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)

        def _fixed_score_fn(security_id, as_of_time, fundamentals_repo):
            return {"TRENDUP": 1.0, "TRENDDOWN": 0.0}[security_id]

        summary = compute_fundamentals_ic_series(
            list(universe), [_utc(2021, m, 1) for m in (3, 6, 9)], _fixed_score_fn,
            fundamentals_repository=None, price_repository=price_repo, horizon_days=30,
        )
        assert summary.mean_ic == 1.0

    def test_end_to_end_with_the_real_roe_score_against_a_real_fundamentals_repository(self, tmp_path) -> None:
        from strategy_research.factor_scores import roe_score

        universe = ("TRENDUP", "TRENDDOWN")
        price_repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)

        engine = new_engine(tmp_path)
        fundamentals_repo = DuckDBFundamentalsRepository(engine)
        # TRENDUP: strong ROE (high income, modest equity). TRENDDOWN:
        # weak ROE (small income, same equity) -- filed well before any
        # rebalance date used below.
        for security_id, income in (("TRENDUP", 50.0), ("TRENDDOWN", 5.0)):
            fundamentals_repo.add_fundamental(
                _fundamental_record(security_id, f"{security_id}:income", value=income, available_time=_utc(2020, 3, 1))
            )
            fundamentals_repo.add_fundamental(
                _fundamental_record(
                    security_id, f"{security_id}:equity", value=100.0,
                    available_time=_utc(2020, 3, 1), concept="StockholdersEquity",
                )
            )

        summary = compute_fundamentals_ic_series(
            list(universe), [_utc(2021, m, 1) for m in (3, 6, 9)], roe_score,
            fundamentals_repository=fundamentals_repo, price_repository=price_repo, horizon_days=30,
        )
        assert summary.mean_ic is not None
        assert summary.observations  # at least one date produced a real observation

    def test_no_rebalance_dates_produces_empty_summary_not_a_fabricated_zero(self) -> None:
        universe = ("TRENDUP", "TRENDDOWN")
        price_repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2021, 1, 3), symbols=universe)
        summary = compute_fundamentals_ic_series(
            list(universe), [], lambda sid, t, repo: 1.0,
            fundamentals_repository=None, price_repository=price_repo, horizon_days=30,
        )
        assert summary.observations == ()
        assert summary.mean_ic is None

    def test_a_score_not_yet_knowable_as_of_the_rebalance_date_is_never_used(self, tmp_path) -> None:
        # The point-in-time-critical property: a fundamentals record
        # filed AFTER the rebalance date must not affect that date's
        # score at all -- proven here by comparing against a repository
        # that never got the record in the first place, mirroring
        # compute_ic_series's own "score never sees data past its own
        # as_of_time" regression style.
        from strategy_research.factor_scores import roe_score

        universe = ("TRENDUP",)
        price_repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)
        early_date = _utc(2021, 3, 1)

        engine_without_record = new_engine(tmp_path, name="without")
        repo_without_record = DuckDBFundamentalsRepository(engine_without_record)

        engine_with_later_record = new_engine(tmp_path, name="with_later")
        repo_with_later_record = DuckDBFundamentalsRepository(engine_with_later_record)
        # Filed well AFTER early_date -- must not be visible to a score
        # computed as of early_date.
        for concept, value in (("NetIncomeLoss", 50.0), ("StockholdersEquity", 100.0)):
            repo_with_later_record.add_fundamental(
                _fundamental_record("TRENDUP", f"late:{concept}", value=value, available_time=_utc(2022, 6, 1), concept=concept)
            )

        score_without = roe_score("TRENDUP", early_date, repo_without_record)
        score_with_later = roe_score("TRENDUP", early_date, repo_with_later_record)
        assert score_without is None
        assert score_with_later is None  # the later-filed record is correctly invisible at early_date
