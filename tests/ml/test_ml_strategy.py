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

    def test_default_train_window_is_84_months_adr_0087(self) -> None:
        # ADR-0087: the account owner's "give the model more data"
        # direction -- extended from 60 (5 fiscal-year snapshots) to 84
        # (7), paired with linear_model.py's widened CANDIDATE_RIDGES.
        assert MLStrategyParameters().train_window_months == 84


class TestPluggableModelBuilder:
    """ADR-0043 Decision 5: MLStrategy's model family is swappable via
    `model_builder`, so a second family (ridge_cv_builder) can run
    through the identical leakage-safe, lazily-per-fold-fit mechanism
    without duplicating it."""

    def test_custom_model_builder_is_actually_used(self, tmp_path) -> None:
        universe = ("TRENDUP", "TRENDDOWN")
        start, end = date(2022, 1, 3), date(2022, 9, 1)
        price_repo = synthetic_multi_year_repository(*_LONG_HISTORY, symbols=universe)
        fundamentals_repo = _fundamentals_repo(tmp_path, universe)
        calls = []

        class _StubModel:
            def predict(self, features):
                return -features["momentum"]  # deliberately inverted ranking

        def _stub_builder(samples):
            calls.append(len(samples))
            return _StubModel()

        strategy = MLStrategy(list(universe), fundamentals_repo, _PARAMS, model_builder=_stub_builder)
        result = BacktestEngine(price_repo, _config(start, end, universe), strategy).run()

        assert calls, "the injected model_builder must have been called at least once"
        bought = {f.security_id for f in result.fills if f.side.value == "BUY"}
        assert bought == {"TRENDDOWN"}  # inverted ranking picks the weaker-momentum security

    def test_ridge_cv_builder_produces_a_usable_model(self, tmp_path) -> None:
        from ml.ml_strategy import ridge_cv_builder

        universe = ("TRENDUP", "TRENDDOWN", "CYCLICAL")
        start, end = date(2022, 1, 3), date(2022, 9, 1)
        price_repo = synthetic_multi_year_repository(*_LONG_HISTORY, symbols=universe)
        fundamentals_repo = _fundamentals_repo(tmp_path, universe)

        strategy = MLStrategy(
            list(universe), fundamentals_repo, MLStrategyParameters(top_n=1, train_window_months=24),
            model_builder=ridge_cv_builder, version="ml_ridge_cv_v1",
        )
        result = BacktestEngine(price_repo, _config(start, end, universe), strategy).run()

        assert strategy.version == "ml_ridge_cv_v1"
        # No crash, and the fit actually succeeded (some orders placed) --
        # correctness of the ridge selection itself is covered directly
        # in tests/ml/test_linear_model.py.
        assert len(result.fills) > 0


class TestSharedFeatureCache:
    """ADR-0043 Decision 5: an injected shared cache must not change
    ANY observable result -- it is a pure performance optimization."""

    def test_shared_cache_produces_identical_fills_to_no_cache(self, tmp_path) -> None:
        universe = ("TRENDUP", "TRENDDOWN", "CYCLICAL")
        start, end = date(2022, 1, 3), date(2023, 1, 4)
        price_repo = synthetic_multi_year_repository(*_LONG_HISTORY, symbols=universe)
        fundamentals_repo = _fundamentals_repo(tmp_path, universe)
        config = _config(start, end, universe)

        uncached = BacktestEngine(price_repo, config, MLStrategy(list(universe), fundamentals_repo, _PARAMS)).run()

        shared_features: dict = {}
        shared_targets: dict = {}
        cached_strategy = MLStrategy(
            list(universe), fundamentals_repo, _PARAMS, feature_cache=shared_features, target_cache=shared_targets,
        )
        cached = BacktestEngine(price_repo, config, cached_strategy).run()

        def sig(f):
            return (f.security_id, f.side, f.quantity, f.price, f.execution_time)

        assert [sig(f) for f in uncached.fills] == [sig(f) for f in cached.fills]
        assert uncached.performance == cached.performance
        assert shared_features  # actually got populated

    def test_a_cache_shared_across_two_instances_is_reused_correctly(self, tmp_path) -> None:
        # Simulates two walk-forward folds' fresh MLStrategy instances
        # sharing one cache dict, exactly as run_long_horizon_validation.py
        # wires it -- the second instance must produce the SAME result
        # as an uncached instance would, using values the first instance
        # already computed.
        universe = ("TRENDUP", "TRENDDOWN")
        start, end = date(2022, 1, 3), date(2022, 9, 1)
        price_repo = synthetic_multi_year_repository(*_LONG_HISTORY, symbols=universe)
        fundamentals_repo = _fundamentals_repo(tmp_path, universe)

        shared_features: dict = {}
        shared_targets: dict = {}
        first = MLStrategy(list(universe), fundamentals_repo, _PARAMS, feature_cache=shared_features, target_cache=shared_targets)
        BacktestEngine(price_repo, _config(start, end, universe), first).run()
        cache_size_after_first = len(shared_features)
        assert cache_size_after_first > 0

        second = MLStrategy(list(universe), fundamentals_repo, _PARAMS, feature_cache=shared_features, target_cache=shared_targets)
        result_second = BacktestEngine(price_repo, _config(start, end, universe), second).run()

        uncached_third = MLStrategy(list(universe), fundamentals_repo, _PARAMS)
        result_uncached = BacktestEngine(price_repo, _config(start, end, universe), uncached_third).run()

        def sig(f):
            return (f.security_id, f.side, f.quantity, f.price, f.execution_time)

        assert [sig(f) for f in result_second.fills] == [sig(f) for f in result_uncached.fills]
