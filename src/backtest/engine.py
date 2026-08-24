"""BacktestEngine: orchestrates the full replay loop.

See docs/specifications/PHASE-2-backtesting.md section 3 for the layer
diagram this module wires together.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from typing import Optional

from data_infra.repository import DataRepository
from data_infra.versioning import compute_data_version

from backtest.asof import AsOfDataView
from backtest.benchmark import BenchmarkEngine, BenchmarkResult
from backtest.broker import BacktestBroker
from backtest.clock import BacktestClock, build_daily_checkpoints
from backtest.corporate_actions import CorporateActionApplier
from backtest.costs import DEFAULT_SLIPPAGE_MODEL, DEFAULT_TRANSACTION_COST_MODEL, SlippageModel, TransactionCostModel
from backtest.enums import ExperimentResult, IntegritySeverity, OrderStatus
from backtest.experiment import ExperimentRecord, ExperimentTracker
from backtest.fills import Fill, FillSimulator
from backtest.integrity import BacktestIntegrityChecker, IntegrityReport
from backtest.metrics import PerformanceReport, compute_performance_report
from backtest.orders import Order, OrderSimulator
from backtest.portfolio import PortfolioAccounting
from backtest.strategy import Strategy


@dataclass(frozen=True)
class BacktestConfig:
    market: str
    start_date: date
    end_date: date
    initial_capital: float
    security_ids: tuple[str, ...] = ()
    universe: Optional[tuple[str, str]] = None  # (market, universe_name) — dynamic, takes precedence
    benchmark_id: Optional[str] = None
    cost_model: TransactionCostModel = DEFAULT_TRANSACTION_COST_MODEL
    slippage_model: SlippageModel = DEFAULT_SLIPPAGE_MODEL
    max_participation: float = 0.10
    checkpoint_time: time = time(20, 0)
    risk_free_rate: float = 0.0
    periods_per_year: int = 252
    seed: Optional[int] = None
    code_version: str = "unknown"
    feature_version: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.security_ids and self.universe is None:
            raise ValueError("BacktestConfig requires either security_ids or universe")
        if self.initial_capital <= 0:
            raise ValueError("initial_capital must be positive")


@dataclass(frozen=True)
class BacktestResult:
    experiment: ExperimentRecord
    performance: PerformanceReport
    integrity: IntegrityReport
    benchmark: Optional[BenchmarkResult]
    orders: tuple[Order, ...]
    fills: tuple[Fill, ...]

    @property
    def is_valid_performance(self) -> bool:
        return self.integrity.is_valid_performance


class BacktestEngine:
    def __init__(
        self,
        repository: DataRepository,
        config: BacktestConfig,
        strategy: Strategy,
        *,
        experiment_tracker: Optional[ExperimentTracker] = None,
    ) -> None:
        self._repository = repository
        self._config = config
        self._strategy = strategy
        self._experiment_tracker = experiment_tracker or ExperimentTracker()

    def run(self) -> BacktestResult:
        config = self._config
        calendar = self._repository.get_trading_calendar(config.market)
        checkpoints = build_daily_checkpoints(
            calendar, config.start_date, config.end_date, checkpoint_time=config.checkpoint_time
        )
        clock = BacktestClock(checkpoints)
        data_view = AsOfDataView(self._repository, clock)
        portfolio = PortfolioAccounting(config.initial_capital)
        order_simulator = OrderSimulator(config.cost_model)
        fill_simulator = FillSimulator(
            config.cost_model, config.slippage_model, max_participation=config.max_participation
        )
        broker = BacktestBroker(fill_simulator)
        corporate_action_applier = CorporateActionApplier()
        integrity = BacktestIntegrityChecker()

        all_orders: list[Order] = []
        all_fills: list[Fill] = []
        data_versions_used: set[str] = set()

        for index, checkpoint in enumerate(checkpoints):
            clock.index = index
            integrity.check_checkpoint_order(checkpoint)

            universe_today = self._resolve_universe(checkpoint)
            tracked_ids = universe_today | set(portfolio.positions.keys())

            for security_id in sorted(tracked_ids):
                actions = self._repository.get_corporate_actions(
                    security_id, checkpoint - timedelta(days=400), checkpoint, as_of_time=checkpoint
                )
                for action in actions:
                    integrity.check_corporate_action_timing(action, checkpoint)
                warnings = corporate_action_applier.apply(actions, portfolio, checkpoint)
                for warning in warnings:
                    integrity.record("corporate_action_correctness", IntegritySeverity.WARNING, warning, checkpoint)

            todays_prices: dict[str, float] = {}
            for security_id in sorted(tracked_ids):
                bars = self._repository.get_bars(
                    security_id, checkpoint - timedelta(days=1), checkpoint, as_of_time=checkpoint
                )
                if bars:
                    todays_prices[security_id] = bars[-1].close
                    data_versions_used.add(bars[-1].provenance.data_version)

            _, missing = portfolio.mark_to_market(todays_prices, checkpoint)
            integrity.check_missing_data(missing, checkpoint)

            portfolio_view = portfolio.snapshot_view(checkpoint)
            intents = self._strategy.generate_orders(checkpoint, data_view, portfolio_view)
            integrity.check_universe(intents, universe_today, checkpoint)
            integrity.check_duplicate_intents(intents, checkpoint)

            next_checkpoint = checkpoints[index + 1] if index + 1 < len(checkpoints) else None
            if next_checkpoint is None:
                for intent in intents:
                    all_orders.append(
                        Order(
                            order_simulator.allocate_id(), intent.security_id, intent.side,
                            intent.quantity, intent.order_type, checkpoint, OrderStatus.NOT_EXECUTED,
                            "generated on the final checkpoint of the backtest window — no future "
                            "execution price exists within it (Phase 2 spec section 6.2)",
                        )
                    )
                integrity.note_discarded_end_of_backtest(intents, checkpoint)
                integrity.check_portfolio_state(portfolio.snapshot_view(checkpoint))
                continue

            for intent in intents:
                reference_price = todays_prices.get(intent.security_id)
                if reference_price is None:
                    integrity.record(
                        "missing_data", IntegritySeverity.WARNING,
                        f"cannot evaluate order for {intent.security_id}: no reference price at {checkpoint}",
                        checkpoint, intent.security_id,
                    )
                    continue

                order = order_simulator.create(intent, portfolio_view, checkpoint, reference_price)
                if order.status != OrderStatus.PROPOSED:
                    all_orders.append(order)
                    continue

                execution_bars = self._repository.get_bars(
                    intent.security_id, next_checkpoint - timedelta(days=1), next_checkpoint,
                    as_of_time=next_checkpoint,
                )
                execution_bar = execution_bars[-1] if execution_bars else None

                fill, updated_order = broker.submit_order(
                    order, execution_bar, portfolio_view, next_checkpoint
                )
                all_orders.append(updated_order)

                if fill is not None:
                    integrity.check_fill(fill)
                    integrity.check_execution_checkpoint(fill, next_checkpoint)
                    portfolio.apply_fill(fill)
                    all_fills.append(fill)
                    data_versions_used.add(fill.data_version)
                    portfolio_view = portfolio.snapshot_view(checkpoint)

            integrity.check_portfolio_state(portfolio.snapshot_view(checkpoint))

        benchmark_result = self._compute_benchmark(checkpoints)
        performance = compute_performance_report(
            portfolio, benchmark_result,
            risk_free_rate=config.risk_free_rate, periods_per_year=config.periods_per_year,
        )
        integrity_report = integrity.finalize()

        experiment_result = (
            ExperimentResult.PASSED if integrity_report.is_valid_performance else ExperimentResult.INTEGRITY_FAILED
        )
        configuration_version = compute_data_version(
            {
                "market": config.market,
                "start_date": str(config.start_date),
                "end_date": str(config.end_date),
                "initial_capital": config.initial_capital,
                "security_ids": config.security_ids,
                "universe": config.universe,
                "benchmark_id": config.benchmark_id,
                "cost_model": asdict(config.cost_model),
                "max_participation": config.max_participation,
            }
        )
        experiment = self._experiment_tracker.record(
            strategy_version=getattr(self._strategy, "version", type(self._strategy).__name__),
            data_version=tuple(sorted(data_versions_used)),
            feature_version=config.feature_version,
            configuration_version=configuration_version,
            start_date=checkpoints[0],
            end_date=checkpoints[-1],
            initial_capital=config.initial_capital,
            transaction_cost_config=asdict(config.cost_model),
            slippage_config=asdict(config.slippage_model) if hasattr(config.slippage_model, "__dataclass_fields__") else {},
            benchmark={
                "benchmark_id": config.benchmark_id,
                "return_type": benchmark_result.return_type.value if benchmark_result else None,
            },
            metrics=performance,
            code_version=config.code_version,
            seed=config.seed,
            result=experiment_result,
            timestamp=checkpoints[-1],
        )

        return BacktestResult(
            experiment=experiment,
            performance=performance,
            integrity=integrity_report,
            benchmark=benchmark_result,
            orders=tuple(all_orders),
            fills=tuple(all_fills),
        )

    def _resolve_universe(self, checkpoint: datetime) -> set[str]:
        config = self._config
        if config.universe is not None:
            market_name, universe_name = config.universe
            return set(self._repository.get_universe(market_name, universe_name, as_of_time=checkpoint))
        return set(config.security_ids)

    def _compute_benchmark(self, checkpoints: tuple[datetime, ...]) -> Optional[BenchmarkResult]:
        config = self._config
        if config.benchmark_id is None:
            return None
        benchmark_engine = BenchmarkEngine(config.cost_model)
        # Back-date the range start by a day: BenchmarkPoint.timestamp
        # conventionally marks the start of its period (Phase 1 spec
        # section 10, e.g. midnight), while `checkpoints[0]` is that same
        # trading day's end-of-session checkpoint (e.g. 20:00) — using
        # checkpoints[0] itself as the range start would incorrectly
        # exclude the first day's own benchmark point.
        return benchmark_engine.compute(
            self._repository, config.benchmark_id, checkpoints[0] - timedelta(days=1), checkpoints[-1],
            as_of_time=checkpoints[-1], initial_capital=config.initial_capital,
        )
