"""Category: generic factor-strategy wrappers (ADR-0051).

Mirrors `test_leverage_strategy.py`'s exact structure and assertions
(top-N selection by score, rebalance cadence, deterministic replay,
missing-data honesty, parameter validation), applied once per variant
(`PriceFactorStrategy`/`FundamentalsFactorStrategy`/
`HybridFactorStrategy`/`UniverseFactorStrategy`) using small fake
score_fns rather than a real `factor_scores.py` function -- these tests
are about the generic wrapper's own order-construction/rebalance
correctness, not about any particular factor's hypothesis. SYNTHETIC/
PIPELINE-VALIDATION fixtures only -- never real strategy evidence (see
`research_helpers.py`'s own docstring)."""

from __future__ import annotations

from datetime import date

import pytest
from research_helpers import synthetic_multi_year_repository

from backtest.engine import BacktestConfig, BacktestEngine

from strategy_research.factor_strategy import (
    FactorStrategyParameters,
    FundamentalsFactorStrategy,
    HybridFactorStrategy,
    PriceFactorStrategy,
    UniverseFactorStrategy,
)


def _config(start, end, universe):
    return BacktestConfig(
        market="US_EQUITY", start_date=start, end_date=end, initial_capital=100_000.0,
        security_ids=tuple(universe), code_version="test",
    )


# A fake price-only score_fn: TRENDDOWN always scores higher than
# TRENDUP, regardless of price data -- isolates "does the wrapper rank
# and rebalance correctly" from any real factor's own logic, matching
# how test_leverage_strategy.py's fixture picks a fixed low/high pair.
_PRICE_SCORES = {"TRENDDOWN": 1.0, "TRENDUP": 0.0, "CYCLICAL": None}


def _fake_price_score_fn(security_id, as_of_time, data):
    return _PRICE_SCORES.get(security_id)


class TestPriceFactorStrategy:
    def test_top_1_selects_the_higher_scored_security(self) -> None:
        universe = ("TRENDUP", "TRENDDOWN")
        start, end = date(2020, 1, 2), date(2020, 6, 1)
        price_repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)

        strategy = PriceFactorStrategy(
            list(universe), _fake_price_score_fn, version="fake_price_v1",
            params=FactorStrategyParameters(top_n=1, rebalance_months=3),
        )
        result = BacktestEngine(price_repo, _config(start, end, universe), strategy).run()

        bought = {f.security_id for f in result.fills if f.side.value == "BUY"}
        assert bought == {"TRENDDOWN"}

    def test_does_not_rebalance_every_daily_checkpoint(self) -> None:
        universe = ("TRENDUP", "TRENDDOWN", "CYCLICAL")
        start, end = date(2020, 1, 2), date(2020, 6, 1)
        price_repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)

        strategy = PriceFactorStrategy(
            list(universe), _fake_price_score_fn, version="fake_price_v1",
            params=FactorStrategyParameters(top_n=1, rebalance_months=3),
        )
        result = BacktestEngine(price_repo, _config(start, end, universe), strategy).run()

        assert 0 < len(result.fills) < 10

    def test_a_security_scoring_none_is_never_ranked(self) -> None:
        universe = ("TRENDUP", "TRENDDOWN", "CYCLICAL")
        start, end = date(2020, 1, 2), date(2020, 6, 1)
        price_repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)

        strategy = PriceFactorStrategy(
            list(universe), _fake_price_score_fn, version="fake_price_v1",
            params=FactorStrategyParameters(top_n=3, rebalance_months=3),
        )
        result = BacktestEngine(price_repo, _config(start, end, universe), strategy).run()

        bought = {f.security_id for f in result.fills if f.side.value == "BUY"}
        assert "CYCLICAL" not in bought

    def test_identical_fills_on_replay(self) -> None:
        universe = ("TRENDUP", "TRENDDOWN", "CYCLICAL")
        start, end = date(2020, 1, 2), date(2021, 1, 4)
        price_repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)
        config = _config(start, end, universe)
        params = FactorStrategyParameters(top_n=1, rebalance_months=3)

        result1 = BacktestEngine(
            price_repo, config, PriceFactorStrategy(list(universe), _fake_price_score_fn, version="fake_price_v1", params=params)
        ).run()
        result2 = BacktestEngine(
            price_repo, config, PriceFactorStrategy(list(universe), _fake_price_score_fn, version="fake_price_v1", params=params)
        ).run()

        def sig(f):
            return (f.security_id, f.side, f.quantity, f.price, f.execution_time)

        assert [sig(f) for f in result1.fills] == [sig(f) for f in result2.fills]
        assert result1.performance == result2.performance


_FUNDAMENTALS_SCORES = {"TRENDDOWN": 1.0, "TRENDUP": 0.0}


def _fake_fundamentals_score_fn(security_id, as_of_time, fundamentals_repository):
    return _FUNDAMENTALS_SCORES.get(security_id)


class TestFundamentalsFactorStrategy:
    def test_top_1_selects_the_higher_scored_security(self) -> None:
        universe = ("TRENDUP", "TRENDDOWN")
        start, end = date(2020, 1, 2), date(2020, 6, 1)
        price_repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)

        strategy = FundamentalsFactorStrategy(
            list(universe), fundamentals_repository=object(), score_fn=_fake_fundamentals_score_fn,
            version="fake_fund_v1", params=FactorStrategyParameters(top_n=1, rebalance_months=3),
        )
        result = BacktestEngine(price_repo, _config(start, end, universe), strategy).run()

        bought = {f.security_id for f in result.fills if f.side.value == "BUY"}
        assert bought == {"TRENDDOWN"}

    def test_a_security_missing_from_the_score_map_is_never_ranked(self) -> None:
        universe = ("TRENDUP", "TRENDDOWN", "CYCLICAL")
        start, end = date(2020, 1, 2), date(2020, 6, 1)
        price_repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)

        strategy = FundamentalsFactorStrategy(
            list(universe), fundamentals_repository=object(), score_fn=_fake_fundamentals_score_fn,
            version="fake_fund_v1", params=FactorStrategyParameters(top_n=3, rebalance_months=3),
        )
        result = BacktestEngine(price_repo, _config(start, end, universe), strategy).run()

        bought = {f.security_id for f in result.fills if f.side.value == "BUY"}
        assert "CYCLICAL" not in bought


class _FakePriceRepository:
    """Stands in for the RAW price repository `HybridFactorStrategy`
    needs -- deliberately NOT `AsOfDataView` (whose `get_bars` takes no
    `as_of_time` kwarg), matching the real `DataRepository.get_bars(...,
    as_of_time=...)` contract `HybridFactorStrategy`'s score_fn expects."""

    def get_bars(self, security_id, start, end, as_of_time=None):
        raise AssertionError("not used by this fixture's fake hybrid score_fn")


_HYBRID_SCORES = {"TRENDDOWN": 1.0, "TRENDUP": 0.0}


def _fake_hybrid_score_fn(security_id, as_of_time, fundamentals_repository, price_repository):
    assert isinstance(price_repository, _FakePriceRepository)
    return _HYBRID_SCORES.get(security_id)


class TestHybridFactorStrategy:
    def test_top_1_selects_the_higher_scored_security_and_uses_the_raw_price_repository(self) -> None:
        universe = ("TRENDUP", "TRENDDOWN")
        start, end = date(2020, 1, 2), date(2020, 6, 1)
        price_repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)

        strategy = HybridFactorStrategy(
            list(universe), fundamentals_repository=object(), price_repository=_FakePriceRepository(),
            score_fn=_fake_hybrid_score_fn, version="fake_hybrid_v1",
            params=FactorStrategyParameters(top_n=1, rebalance_months=3),
        )
        result = BacktestEngine(price_repo, _config(start, end, universe), strategy).run()

        bought = {f.security_id for f in result.fills if f.side.value == "BUY"}
        assert bought == {"TRENDDOWN"}


def _fake_universe_score_fn(security_ids, as_of_time, fundamentals_repository, price_repository):
    assert isinstance(price_repository, _FakePriceRepository)
    return {sid: _HYBRID_SCORES[sid] for sid in security_ids if sid in _HYBRID_SCORES}


class TestUniverseFactorStrategy:
    def test_top_1_selects_the_higher_scored_security(self) -> None:
        universe = ("TRENDUP", "TRENDDOWN")
        start, end = date(2020, 1, 2), date(2020, 6, 1)
        price_repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)

        strategy = UniverseFactorStrategy(
            list(universe), fundamentals_repository=object(), price_repository=_FakePriceRepository(),
            score_fn=_fake_universe_score_fn, version="fake_universe_v1",
            params=FactorStrategyParameters(top_n=1, rebalance_months=3),
        )
        result = BacktestEngine(price_repo, _config(start, end, universe), strategy).run()

        bought = {f.security_id for f in result.fills if f.side.value == "BUY"}
        assert bought == {"TRENDDOWN"}

    def test_a_security_missing_from_the_returned_score_dict_is_never_ranked(self) -> None:
        universe = ("TRENDUP", "TRENDDOWN", "CYCLICAL")
        start, end = date(2020, 1, 2), date(2020, 6, 1)
        price_repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)

        strategy = UniverseFactorStrategy(
            list(universe), fundamentals_repository=object(), price_repository=_FakePriceRepository(),
            score_fn=_fake_universe_score_fn, version="fake_universe_v1",
            params=FactorStrategyParameters(top_n=3, rebalance_months=3),
        )
        result = BacktestEngine(price_repo, _config(start, end, universe), strategy).run()

        bought = {f.security_id for f in result.fills if f.side.value == "BUY"}
        assert "CYCLICAL" not in bought


class TestParameterValidation:
    def test_rejects_out_of_range_rebalance(self) -> None:
        with pytest.raises(ValueError):
            FactorStrategyParameters(rebalance_months=2)

    def test_rejects_non_positive_top_n(self) -> None:
        with pytest.raises(ValueError):
            FactorStrategyParameters(top_n=0)
