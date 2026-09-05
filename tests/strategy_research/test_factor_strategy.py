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
    _select_target,
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

    def test_rejects_non_positive_max_per_sector(self) -> None:
        with pytest.raises(ValueError):
            FactorStrategyParameters(max_per_sector=0)

    def test_max_per_sector_alone_is_a_valid_no_op_configuration(self) -> None:
        # sector_by_security defaults to None, so max_per_sector alone
        # does not activate the cap (see _select_target's own docstring
        # -- BOTH fields are required to opt in) -- this must not raise.
        FactorStrategyParameters(max_per_sector=2)


class TestSelectTarget:
    """Session 36 sector-neutralization capability -- built after
    `size_score` reaching walk-forward CANDIDATE at top_n=5 turned out
    to be SLB alone supplying 76.3% of its positive TEST PnL (Phase 33
    Addendum section E), a concentration artifact rather than a real
    size effect. `_select_target` is the shared selection helper all 4
    wrapper classes now call instead of a bare `ranked[:top_n]` slice."""

    def test_with_no_sector_data_behaves_identically_to_a_plain_slice(self) -> None:
        ranked = ["A", "B", "C", "D"]
        params = FactorStrategyParameters(top_n=2)

        assert _select_target(ranked, params) == {"A", "B"}

    def test_with_max_per_sector_but_no_sector_map_behaves_identically_to_a_plain_slice(self) -> None:
        # Both fields are required to opt in -- max_per_sector alone
        # (sector_by_security still None) must not activate the cap.
        ranked = ["A", "B", "C", "D"]
        params = FactorStrategyParameters(top_n=2, max_per_sector=1)

        assert _select_target(ranked, params) == {"A", "B"}

    def test_caps_how_many_of_one_sector_are_selected(self) -> None:
        # A/B/C are all ENERGY, ranked best to worst; D is TECH.
        # top_n=3 would normally pick A/B/C -- max_per_sector=1 should
        # instead skip B and C (already at the Energy cap) and fall
        # through to D, the next-best non-capped security.
        ranked = ["A", "B", "C", "D"]
        sector_by_security = {"A": "ENERGY", "B": "ENERGY", "C": "ENERGY", "D": "TECH"}
        params = FactorStrategyParameters(top_n=3, sector_by_security=sector_by_security, max_per_sector=1)

        assert _select_target(ranked, params) == {"A", "D"}

    def test_never_promotes_a_lower_ranked_security_ahead_of_a_higher_ranked_one(self) -> None:
        # Even capped, the final target set still respects rank order --
        # this test only checks membership (a set has no order), so the
        # real assertion is in the sibling test above: D is picked
        # because it is next in RANK order after the cap, not because it
        # was moved to the front.
        ranked = ["A", "B", "C", "D"]
        sector_by_security = {"A": "ENERGY", "B": "ENERGY", "C": "ENERGY", "D": "TECH"}
        params = FactorStrategyParameters(top_n=1, sector_by_security=sector_by_security, max_per_sector=1)

        assert _select_target(ranked, params) == {"A"}  # A is both best-ranked AND under its sector's cap

    def test_a_security_with_no_known_sector_is_never_capped(self) -> None:
        # C has no entry in sector_by_security at all (unconfirmed) --
        # absence of sector data must never be treated as evidence of
        # concentration (the same discipline universe.py's own honesty
        # rule already establishes for SymbolMetadata.sector).
        ranked = ["A", "B", "C"]
        sector_by_security = {"A": "ENERGY", "B": "ENERGY"}  # C deliberately absent
        params = FactorStrategyParameters(top_n=2, sector_by_security=sector_by_security, max_per_sector=1)

        assert _select_target(ranked, params) == {"A", "C"}

    def test_top_n_is_still_the_final_target_size_when_enough_securities_are_uncapped(self) -> None:
        ranked = ["A", "B", "C", "D", "E"]
        sector_by_security = {"A": "ENERGY", "B": "TECH", "C": "HEALTH", "D": "ENERGY", "E": "TECH"}
        params = FactorStrategyParameters(top_n=3, sector_by_security=sector_by_security, max_per_sector=1)

        assert _select_target(ranked, params) == {"A", "B", "C"}  # already 3 distinct sectors, no capping needed


class TestSectorCapEndToEnd:
    """One integration test proving the cap actually changes which
    securities `PriceFactorStrategy` buys, not just the pure helper's
    own return value -- mirrors `TestPriceFactorStrategy`'s existing
    fixture shape."""

    def test_sector_cap_excludes_a_same_sector_security_even_though_it_scores_higher(self) -> None:
        # Symbol names must come from research_helpers.SYNTHETIC_UNIVERSE
        # (synthetic_multi_year_repository's own generator set) -- the
        # "sector" labels below are an independent fixture-only mapping,
        # unrelated to the symbols' actual price paths, since only the
        # fake _score_fn (not price behavior) drives ranking here.
        universe = ("TRENDUP", "TRENDDOWN", "FLATLOW")
        start, end = date(2020, 1, 2), date(2020, 6, 1)
        price_repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)
        scores = {"TRENDUP": 3.0, "TRENDDOWN": 2.0, "FLATLOW": 1.0}

        def _score_fn(security_id, as_of_time, data):
            return scores.get(security_id)

        params = FactorStrategyParameters(
            top_n=2, rebalance_months=3,
            sector_by_security={"TRENDUP": "ENERGY", "TRENDDOWN": "ENERGY", "FLATLOW": "TECH"},
            max_per_sector=1,
        )
        strategy = PriceFactorStrategy(list(universe), _score_fn, version="fake_price_sector_v1", params=params)
        result = BacktestEngine(price_repo, _config(start, end, universe), strategy).run()

        bought = {f.security_id for f in result.fills if f.side.value == "BUY"}
        # Without the cap, top_n=2 would buy TRENDUP + TRENDDOWN (the
        # two highest scores). With max_per_sector=1, TRENDDOWN is
        # skipped (Energy already at its cap from TRENDUP) and FLATLOW
        # is bought instead.
        assert bought == {"TRENDUP", "FLATLOW"}
