"""Category: Strategy determinism + leakage-safe in-strategy fitting.
`MLStrategy` must (1) fit itself lazily on its first `generate_orders`
call using only history strictly before that moment, (2) rank the
higher-predicted-forward-return synthetic security above the lower one
once fit, (3) rebalance strictly by elapsed calendar months, (4)
produce byte-identical order sequences on repeated runs, and (5) return
no orders (never a fabricated fallback) when there isn't enough history
to fit at all. SYNTHETIC/PIPELINE-VALIDATION fixtures only -- never
real strategy evidence (see `ml/__init__.py`'s own docstring)."""

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

from ml.ml_strategy import MLStrategy, MLStrategyParameters


def _config(start, end, universe):
    return BacktestConfig(
        market="US_EQUITY", start_date=start, end_date=end, initial_capital=100_000.0,
        security_ids=tuple(universe), code_version="test",
    )


def _fy_record(security_id, record_id, *, concept, value, period_end):
    return FundamentalRecord(
        security_id=security_id, concept=concept, period_end=period_end, fiscal_year=period_end.year,
        fiscal_period="FY", form_type="10-K", value=value, unit="USD",
        available_time=period_end, ingestion_time=period_end,
        provenance=Provenance(
            source="sec_edgar", source_dataset=f"sec_edgar_companyfacts_{security_id}",
            source_record_id=record_id, retrieved_at=period_end, data_version="v1",
        ),
    )


def _fundamentals_repo(tmp_path, security_ids, *, years=range(2015, 2023)):
    engine = new_engine(tmp_path)
    repo = DuckDBFundamentalsRepository(engine)
    for security_id in security_ids:
        for year in years:
            period_end = datetime(year, 12, 31, tzinfo=timezone.utc)
            repo.add_fundamental(_fy_record(security_id, f"{security_id}:ni:{year}", concept="NetIncomeLoss", value=10.0, period_end=period_end))
            repo.add_fundamental(_fy_record(security_id, f"{security_id}:assets:{year}", concept="Assets", value=100.0, period_end=period_end))
            repo.add_fundamental(_fy_record(security_id, f"{security_id}:eq:{year}", concept="StockholdersEquity", value=50.0, period_end=period_end))
            repo.add_fundamental(_fy_record(security_id, f"{security_id}:liab:{year}", concept="Liabilities", value=20.0, period_end=period_end))
            repo.add_fundamental(_fy_record(security_id, f"{security_id}:rev:{year}", concept="Revenues", value=200.0, period_end=period_end))
    return repo


_LONG_HISTORY = (date(2015, 1, 2), date(2023, 6, 1))
_PARAMS = MLStrategyParameters(top_n=1, rebalance_months=3, train_window_months=24)


class TestFitsAndPicksHigherPredictedReturn:
    def test_top_1_selects_the_stronger_uptrend_security(self, tmp_path) -> None:
        universe = ("TRENDUP", "TRENDDOWN")
        start, end = date(2022, 1, 3), date(2022, 9, 1)
        price_repo = synthetic_multi_year_repository(*_LONG_HISTORY, symbols=universe)
        fundamentals_repo = _fundamentals_repo(tmp_path, universe)

        strategy = MLStrategy(list(universe), fundamentals_repo, _PARAMS)
        result = BacktestEngine(price_repo, _config(start, end, universe), strategy).run()

        bought = {f.security_id for f in result.fills if f.side.value == "BUY"}
        assert bought == {"TRENDUP"}  # consistently higher momentum AND higher forward return


class TestRebalanceCadence:
    def test_does_not_rebalance_every_daily_checkpoint(self, tmp_path) -> None:
        universe = ("TRENDUP", "TRENDDOWN", "CYCLICAL")
        start, end = date(2022, 1, 3), date(2022, 9, 1)
        price_repo = synthetic_multi_year_repository(*_LONG_HISTORY, symbols=universe)
        fundamentals_repo = _fundamentals_repo(tmp_path, universe)

        strategy = MLStrategy(list(universe), fundamentals_repo, _PARAMS)
        result = BacktestEngine(price_repo, _config(start, end, universe), strategy).run()

        assert 0 < len(result.fills) < 10


class TestDeterministicReplay:
    def test_identical_fills_on_replay(self, tmp_path) -> None:
        universe = ("TRENDUP", "TRENDDOWN", "CYCLICAL")
        start, end = date(2022, 1, 3), date(2023, 1, 4)
        price_repo = synthetic_multi_year_repository(*_LONG_HISTORY, symbols=universe)
        fundamentals_repo = _fundamentals_repo(tmp_path, universe)
        config = _config(start, end, universe)

        result1 = BacktestEngine(price_repo, config, MLStrategy(list(universe), fundamentals_repo, _PARAMS)).run()
        result2 = BacktestEngine(price_repo, config, MLStrategy(list(universe), fundamentals_repo, _PARAMS)).run()

        def sig(f):
            return (f.security_id, f.side, f.quantity, f.price, f.execution_time)

        assert [sig(f) for f in result1.fills] == [sig(f) for f in result2.fills]
        assert result1.performance == result2.performance


class TestInsufficientHistoryHandledHonestly:
    def test_no_orders_when_there_is_no_fundamentals_data_to_fit_on(self, tmp_path) -> None:
        universe = ("TRENDUP", "TRENDDOWN")
        start, end = date(2022, 1, 3), date(2022, 9, 1)
        price_repo = synthetic_multi_year_repository(*_LONG_HISTORY, symbols=universe)
        empty_fundamentals_repo = DuckDBFundamentalsRepository(new_engine(tmp_path))

        strategy = MLStrategy(list(universe), empty_fundamentals_repo, _PARAMS)
        result = BacktestEngine(price_repo, _config(start, end, universe), strategy).run()

        assert result.fills == ()

    def test_no_orders_when_the_backtest_starts_too_early_in_history_to_fit(self, tmp_path) -> None:
        # Starting right at the repository's own earliest bar leaves no
        # room to walk train_window_months backward -- _fit must return
        # None (no fabricated fit), not raise.
        universe = ("TRENDUP", "TRENDDOWN")
        price_repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)
        fundamentals_repo = _fundamentals_repo(tmp_path, universe)

        strategy = MLStrategy(list(universe), fundamentals_repo, MLStrategyParameters(top_n=1, train_window_months=24))
        result = BacktestEngine(
            price_repo, _config(date(2020, 1, 2), date(2020, 6, 1), universe), strategy
        ).run()

        assert result.fills == ()


class TestParameterValidation:
    def test_rejects_out_of_range_rebalance(self) -> None:
        with pytest.raises(ValueError):
            MLStrategyParameters(rebalance_months=2)

    def test_rejects_non_positive_top_n(self) -> None:
        with pytest.raises(ValueError):
            MLStrategyParameters(top_n=0)

    def test_rejects_non_positive_train_window(self) -> None:
        with pytest.raises(ValueError):
            MLStrategyParameters(train_window_months=0)
