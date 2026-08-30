"""Category: Strategy determinism + hypothesis sanity, mirroring
`test_long_term_momentum.py`'s exact structure -- `LeverageStrategy`
must (1) rank the lower-leverage synthetic security above the
higher-leverage one, (2) rebalance strictly by elapsed calendar months,
and (3) produce byte-identical order sequences on repeated runs.
SYNTHETIC/PIPELINE-VALIDATION fixtures only -- never real strategy
evidence (see `research_helpers.py`'s own docstring)."""

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

from strategy_research.leverage_strategy import LeverageParameters, LeverageStrategy


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


def _fundamentals_repo(tmp_path, *, low_leverage_id, high_leverage_id):
    engine = new_engine(tmp_path)
    repo = DuckDBFundamentalsRepository(engine)
    repo.add_fundamental(_fy_record(low_leverage_id, f"{low_leverage_id}:liab", concept="Liabilities", value=20.0))
    repo.add_fundamental(_fy_record(low_leverage_id, f"{low_leverage_id}:eq", concept="StockholdersEquity", value=100.0))
    repo.add_fundamental(_fy_record(high_leverage_id, f"{high_leverage_id}:liab", concept="Liabilities", value=90.0))
    repo.add_fundamental(_fy_record(high_leverage_id, f"{high_leverage_id}:eq", concept="StockholdersEquity", value=100.0))
    return repo


class TestPicksTheLowerLeverageName:
    def test_top_1_selects_the_lower_leverage_security(self, tmp_path) -> None:
        # TRENDUP/TRENDDOWN's own price paths are irrelevant to this
        # strategy's ranking (leverage_score never reads price data) --
        # reused only as a convenient pair of already-registered
        # synthetic symbols with real bar data for order sizing.
        universe = ("TRENDUP", "TRENDDOWN")
        start, end = date(2020, 1, 2), date(2020, 6, 1)
        price_repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)
        fundamentals_repo = _fundamentals_repo(tmp_path, low_leverage_id="TRENDDOWN", high_leverage_id="TRENDUP")

        strategy = LeverageStrategy(list(universe), fundamentals_repo, LeverageParameters(top_n=1, rebalance_months=3))
        result = BacktestEngine(price_repo, _config(start, end, universe), strategy).run()

        bought = {f.security_id for f in result.fills if f.side.value == "BUY"}
        assert bought == {"TRENDDOWN"}  # the lower-leverage security, regardless of its price trend


class TestRebalanceCadence:
    def test_does_not_rebalance_every_daily_checkpoint(self, tmp_path) -> None:
        universe = ("TRENDUP", "TRENDDOWN", "CYCLICAL")
        start, end = date(2020, 1, 2), date(2020, 6, 1)
        price_repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)
        fundamentals_repo = _fundamentals_repo(tmp_path, low_leverage_id="TRENDDOWN", high_leverage_id="TRENDUP")

        strategy = LeverageStrategy(list(universe), fundamentals_repo, LeverageParameters(top_n=1, rebalance_months=3))
        result = BacktestEngine(price_repo, _config(start, end, universe), strategy).run()

        assert 0 < len(result.fills) < 10


class TestDeterministicReplay:
    def test_identical_fills_on_replay(self, tmp_path) -> None:
        universe = ("TRENDUP", "TRENDDOWN", "CYCLICAL")
        start, end = date(2020, 1, 2), date(2021, 1, 4)
        price_repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)
        fundamentals_repo = _fundamentals_repo(tmp_path, low_leverage_id="TRENDDOWN", high_leverage_id="TRENDUP")
        config = _config(start, end, universe)

        result1 = BacktestEngine(
            price_repo, config, LeverageStrategy(list(universe), fundamentals_repo, LeverageParameters(top_n=1, rebalance_months=3))
        ).run()
        result2 = BacktestEngine(
            price_repo, config, LeverageStrategy(list(universe), fundamentals_repo, LeverageParameters(top_n=1, rebalance_months=3))
        ).run()

        def sig(f):
            return (f.security_id, f.side, f.quantity, f.price, f.execution_time)

        assert [sig(f) for f in result1.fills] == [sig(f) for f in result2.fills]
        assert result1.performance == result2.performance


class TestMissingFundamentalsDataHandledHonestly:
    def test_a_security_with_no_fundamentals_data_is_never_ranked_not_scored_as_zero(self, tmp_path) -> None:
        # CYCLICAL has no fundamentals records at all in this fixture --
        # leverage_score must return None for it (never a fabricated 0.0
        # that could rank it above or below a real score by accident).
        universe = ("TRENDUP", "TRENDDOWN", "CYCLICAL")
        start, end = date(2020, 1, 2), date(2020, 6, 1)
        price_repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)
        fundamentals_repo = _fundamentals_repo(tmp_path, low_leverage_id="TRENDDOWN", high_leverage_id="TRENDUP")

        strategy = LeverageStrategy(list(universe), fundamentals_repo, LeverageParameters(top_n=3, rebalance_months=3))
        result = BacktestEngine(price_repo, _config(start, end, universe), strategy).run()

        bought = {f.security_id for f in result.fills if f.side.value == "BUY"}
        assert "CYCLICAL" not in bought


class TestParameterValidation:
    def test_rejects_out_of_range_rebalance(self) -> None:
        with pytest.raises(ValueError):
            LeverageParameters(rebalance_months=2)

    def test_rejects_non_positive_top_n(self) -> None:
        with pytest.raises(ValueError):
            LeverageParameters(top_n=0)
