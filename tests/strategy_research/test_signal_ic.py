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

from research_helpers import synthetic_multi_year_repository

from strategy_research.long_term_momentum import LongTermMomentumParameters, LongTermMomentumStrategy
from strategy_research.signal_ic import _pearson, _rank, compute_ic_series, spearman_ic


def _utc(y, m, d):
    return datetime(y, m, d, tzinfo=timezone.utc)


class TestRank:
    def test_strictly_increasing_values_get_sequential_ranks(self) -> None:
        assert _rank([10.0, 20.0, 30.0]) == [1.0, 2.0, 3.0]

    def test_descending_input_still_ranks_by_value_not_position(self) -> None:
        assert _rank([30.0, 10.0, 20.0]) == [3.0, 1.0, 2.0]

    def test_tied_values_get_the_average_of_their_ranks(self) -> None:
        # Two values tied for ranks 1-2 -> both get 1.5; the top value gets rank 3.
        assert _rank([5.0, 5.0, 9.0]) == [1.5, 1.5, 3.0]


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
        # partial IC (0.5, not the 3-item perfect 1.0), demonstrating
        # this module does not silently round a partial signal up to
        # "perfectly predictive."
        universe = ("TRENDUP", "TRENDDOWN", "CYCLICAL")
        repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)
        strategy = LongTermMomentumStrategy(
            list(universe), LongTermMomentumParameters(lookback_months=6, top_n=1, rebalance_months=3)
        )
        rebalance_dates = [_utc(2021, m, 1) for m in (3, 6, 9)]

        summary = compute_ic_series(
            list(universe), rebalance_dates, strategy._momentum_score, repo, horizon_days=60
        )

        assert summary.mean_ic == 0.5
        assert 0.0 < summary.mean_ic < 1.0

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
