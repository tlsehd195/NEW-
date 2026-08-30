"""Category: Strategy determinism + rank-average combination logic.
`RankAverageEnsembleStrategy` must (1) pick the security whose average
rank of `leverage_score`/`net_margin_score` is best, (2) rebalance
strictly by elapsed calendar months, (3) produce byte-identical order
sequences on repeated runs, and (4) never rank a security missing
either score (no fabricated combination). SYNTHETIC/PIPELINE-
VALIDATION fixtures only -- never real strategy evidence."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from helpers import utc
from research_helpers import synthetic_multi_year_repository
from storage_helpers import new_engine

from backtest.engine import BacktestConfig, BacktestEngine

from data_infra.fundamentals_models import FundamentalRecord
from data_infra.models import Provenance

from storage.fundamentals_repository import DuckDBFundamentalsRepository

from strategy_research.ensemble_strategy import RankAverageEnsembleParameters, RankAverageEnsembleStrategy


def _config(start, end, universe):
    return BacktestConfig(
        market="US_EQUITY", start_date=start, end_date=end, initial_capital=100_000.0,
        security_ids=tuple(universe), code_version="test",
    )


def _fy_record(security_id, record_id, *, concept, value, period_end=utc(2019, 12, 31)):
    return FundamentalRecord(
        security_id=security_id, concept=concept, period_end=period_end, fiscal_year=period_end.year,
        fiscal_period="FY", form_type="10-K", value=value, unit="USD",
        available_time=period_end, ingestion_time=period_end,
        provenance=Provenance(
            source="sec_edgar", source_dataset=f"sec_edgar_companyfacts_{security_id}",
            source_record_id=record_id, retrieved_at=period_end, data_version="v1",
        ),
    )


def _fundamentals_repo(tmp_path, *, better_id, worse_id):
    engine = new_engine(tmp_path)
    repo = DuckDBFundamentalsRepository(engine)
    # `better_id` wins on BOTH leverage (lower Liabilities/Equity) and
    # net_margin (higher NetIncomeLoss/Revenues) -- an unambiguous case
    # for the rank-average to pick correctly on either component alone
    # or combined.
    repo.add_fundamental(_fy_record(better_id, f"{better_id}:liab", concept="Liabilities", value=10.0))
    repo.add_fundamental(_fy_record(better_id, f"{better_id}:eq", concept="StockholdersEquity", value=100.0))
    repo.add_fundamental(_fy_record(better_id, f"{better_id}:ni", concept="NetIncomeLoss", value=30.0))
    repo.add_fundamental(_fy_record(better_id, f"{better_id}:rev", concept="Revenues", value=100.0))

    repo.add_fundamental(_fy_record(worse_id, f"{worse_id}:liab", concept="Liabilities", value=90.0))
    repo.add_fundamental(_fy_record(worse_id, f"{worse_id}:eq", concept="StockholdersEquity", value=100.0))
    repo.add_fundamental(_fy_record(worse_id, f"{worse_id}:ni", concept="NetIncomeLoss", value=3.0))
    repo.add_fundamental(_fy_record(worse_id, f"{worse_id}:rev", concept="Revenues", value=100.0))
    return repo


class TestPicksTheBetterRankedName:
    def test_top_1_selects_the_security_that_wins_on_both_components(self, tmp_path) -> None:
        universe = ("TRENDUP", "TRENDDOWN")
        start, end = date(2020, 1, 2), date(2020, 6, 1)
        price_repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)
        fundamentals_repo = _fundamentals_repo(tmp_path, better_id="TRENDDOWN", worse_id="TRENDUP")

        strategy = RankAverageEnsembleStrategy(
            list(universe), fundamentals_repo, RankAverageEnsembleParameters(top_n=1, rebalance_months=3),
        )
        result = BacktestEngine(price_repo, _config(start, end, universe), strategy).run()

        bought = {f.security_id for f in result.fills if f.side.value == "BUY"}
        assert bought == {"TRENDDOWN"}  # the fundamentally-better security, regardless of price trend


class TestRebalanceCadence:
    def test_does_not_rebalance_every_daily_checkpoint(self, tmp_path) -> None:
        universe = ("TRENDUP", "TRENDDOWN", "CYCLICAL")
        start, end = date(2020, 1, 2), date(2020, 6, 1)
        price_repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)
        fundamentals_repo = _fundamentals_repo(tmp_path, better_id="TRENDDOWN", worse_id="TRENDUP")

        strategy = RankAverageEnsembleStrategy(
            list(universe), fundamentals_repo, RankAverageEnsembleParameters(top_n=1, rebalance_months=3),
        )
        result = BacktestEngine(price_repo, _config(start, end, universe), strategy).run()

        assert 0 < len(result.fills) < 10


class TestDeterministicReplay:
    def test_identical_fills_on_replay(self, tmp_path) -> None:
        universe = ("TRENDUP", "TRENDDOWN", "CYCLICAL")
        start, end = date(2020, 1, 2), date(2021, 1, 4)
        price_repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)
        fundamentals_repo = _fundamentals_repo(tmp_path, better_id="TRENDDOWN", worse_id="TRENDUP")
        config = _config(start, end, universe)
        params = RankAverageEnsembleParameters(top_n=1, rebalance_months=3)

        result1 = BacktestEngine(price_repo, config, RankAverageEnsembleStrategy(list(universe), fundamentals_repo, params)).run()
        result2 = BacktestEngine(price_repo, config, RankAverageEnsembleStrategy(list(universe), fundamentals_repo, params)).run()

        def sig(f):
            return (f.security_id, f.side, f.quantity, f.price, f.execution_time)

        assert [sig(f) for f in result1.fills] == [sig(f) for f in result2.fills]
        assert result1.performance == result2.performance


class TestMissingScoreHandledHonestly:
    def test_a_security_missing_either_score_is_never_ranked(self, tmp_path) -> None:
        # CYCLICAL has no fundamentals data at all -- neither
        # leverage_score nor net_margin_score is computable, so it must
        # never appear in the combined ranking (no fabricated average).
        universe = ("TRENDUP", "TRENDDOWN", "CYCLICAL")
        start, end = date(2020, 1, 2), date(2020, 6, 1)
        price_repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)
        fundamentals_repo = _fundamentals_repo(tmp_path, better_id="TRENDDOWN", worse_id="TRENDUP")

        strategy = RankAverageEnsembleStrategy(
            list(universe), fundamentals_repo, RankAverageEnsembleParameters(top_n=3, rebalance_months=3),
        )
        result = BacktestEngine(price_repo, _config(start, end, universe), strategy).run()

        bought = {f.security_id for f in result.fills if f.side.value == "BUY"}
        assert "CYCLICAL" not in bought

    def test_no_orders_when_no_security_has_both_scores(self, tmp_path) -> None:
        universe = ("TRENDUP", "TRENDDOWN")
        start, end = date(2020, 1, 2), date(2020, 6, 1)
        price_repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)
        empty_fundamentals_repo = DuckDBFundamentalsRepository(new_engine(tmp_path))

        strategy = RankAverageEnsembleStrategy(list(universe), empty_fundamentals_repo, RankAverageEnsembleParameters())
        result = BacktestEngine(price_repo, _config(start, end, universe), strategy).run()

        assert result.fills == ()


class TestParameterValidation:
    def test_rejects_out_of_range_rebalance(self) -> None:
        with pytest.raises(ValueError):
            RankAverageEnsembleParameters(rebalance_months=2)

    def test_rejects_non_positive_top_n(self) -> None:
        with pytest.raises(ValueError):
            RankAverageEnsembleParameters(top_n=0)
