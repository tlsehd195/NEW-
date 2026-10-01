"""BacktestEngine: orchestrates the full replay loop.

See docs/specifications/PHASE-2-backtesting.md section 3 for the layer
diagram this module wires together.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from typing import Optional

from data_infra.enums import SecurityStatus
from data_infra.models import SecurityMaster
from data_infra.repository import DataRepository
from data_infra.versioning import compute_data_version

from backtest.asof import AsOfDataView, MembershipFilteredDataView
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
from backtest.risk_free import RiskFreeRates
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
    # ADR-0224, both only meaningful with a dynamic `universe`: hide
    # non-members' bars from the strategy, and turn a held position whose
    # security has had no bar for this many checkpoints in a row (it
    # stopped trading: acquired, delisted) into cash at its last close.
    restrict_strategy_to_universe: bool = False
    settle_after_missing_checkpoints: Optional[int] = None
    checkpoint_time: time = time(20, 0)
    risk_free_rate: float = 0.0
    # ADR-0229: when set, positive cash earns the 3-month T-bill yield
    # (the latest observation before each checkpoint's date, compounded
    # daily on an actual/365 basis). None keeps cash at 0%.
    cash_interest: Optional[RiskFreeRates] = None
    periods_per_year: int = 252
    seed: Optional[int] = None
    code_version: str = "unknown"
    feature_version: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.security_ids and self.universe is None:
            raise ValueError("BacktestConfig requires either security_ids or universe")
        if self.initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        if self.restrict_strategy_to_universe and self.universe is None:
            raise ValueError("restrict_strategy_to_universe requires a dynamic universe")
        if self.settle_after_missing_checkpoints is not None and self.settle_after_missing_checkpoints < 1:
            raise ValueError("settle_after_missing_checkpoints must be >= 1")


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
        strategy_view = (
            MembershipFilteredDataView(self._repository, clock) if config.restrict_strategy_to_universe else data_view
        )
        last_close: dict[str, float] = {}
        missing_streak: dict[str, int] = {}
        # Last SecurityMaster seen per held name. A delisted name's record
        # stops being valid at its `valid_to`, so `get_security` at a later
        # checkpoint returns None exactly when the delisting matters
        # (ADR-0187's open R2 finding); the remembered record still says
        # DELISTED.
        known_security: dict[str, SecurityMaster] = {}
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
            if config.cash_interest is not None and index > 0:
                self._accrue_cash_interest(portfolio, integrity, checkpoints[index - 1], checkpoint)

            universe_today = self._resolve_universe(checkpoint)
            if isinstance(strategy_view, MembershipFilteredDataView):
                strategy_view.members = frozenset(universe_today)
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

            last_close.update(todays_prices)
            marking_prices = todays_prices
            if config.settle_after_missing_checkpoints is not None:
                marking_prices = dict(todays_prices)
                for security_id in sorted(portfolio.positions):
                    if security_id in todays_prices:
                        missing_streak.pop(security_id, None)
                        continue
                    missing_streak[security_id] = missing_streak.get(security_id, 0) + 1
                    if security_id not in last_close:
                        continue
                    if missing_streak[security_id] >= config.settle_after_missing_checkpoints:
                        quantity = portfolio.positions[security_id].quantity
                        portfolio.settle_position(security_id, last_close[security_id], checkpoint)
                        missing_streak.pop(security_id, None)
                        integrity.record(
                            "stale_position_settled", IntegritySeverity.WARNING,
                            f"{security_id}: no bar for {config.settle_after_missing_checkpoints} checkpoints; "
                            f"{quantity:g} shares settled to cash at last close {last_close[security_id]:.4f}",
                            checkpoint, security_id,
                        )
                    else:
                        # Mark a name that has stopped printing at its last
                        # close, not at cost; it is still reported missing.
                        marking_prices[security_id] = last_close[security_id]

            _, missing = portfolio.mark_to_market(marking_prices, checkpoint)
            if marking_prices is not todays_prices:
                missing = sorted(set(missing) | {sid for sid in portfolio.positions if sid not in todays_prices})
            # Independent audit finding (Step 2, P2): a held position
            # whose security is CONFIRMED delisted (real SecurityMaster
            # status, never guessed) gets a dedicated, ERROR-severity
            # check (see BacktestIntegrityChecker.check_delisted_
            # position_marked_at_cost's own docstring for why) -- every
            # OTHER missing-price case (an ordinary temporary data gap)
            # keeps its existing WARNING-severity treatment, unchanged.
            for sid in [*(p for p in portfolio.positions if p not in known_security), *missing]:
                if (sm := self._repository.get_security(sid, checkpoint)) is not None:
                    known_security[sid] = sm
            # Only names actually valued at average cost: a name marked at
            # its last close (settle_after_missing_checkpoints, ADR-0224)
            # is not "marked at cost".
            missing_delisted = [
                sid for sid in missing
                if sid not in marking_prices
                and (sm := known_security.get(sid)) is not None
                and sm.status == SecurityStatus.DELISTED
            ]
            missing_other = [sid for sid in missing if sid not in missing_delisted]
            integrity.check_missing_data(missing_other, checkpoint)
            integrity.check_delisted_position_marked_at_cost(missing_delisted, checkpoint)

            portfolio_view = portfolio.snapshot_view(checkpoint)
            intents = self._strategy.generate_orders(checkpoint, strategy_view, portfolio_view)
            integrity.check_universe(intents, universe_today, checkpoint, held=set(portfolio.positions))
            integrity.check_duplicate_intents(intents, checkpoint)

            next_checkpoint = checkpoints[index + 1] if index + 1 < len(checkpoints) else None
            if intents and next_checkpoint is not None:
                # Session 37 (ADR-0115, external review N-7): every fill
                # below executes at `next_checkpoint`'s close and is
                # applied to `portfolio` synchronously, within THIS
                # iteration -- well before iteration index+1's own
                # top-of-loop corporate-action block (lines 114-122
                # above) would otherwise apply anything effective by
                # `next_checkpoint`. That ordering corrupted every split/
                # dividend at a checkpoint boundary: a post-split buy got
                # `apply_split`'s blind multiply applied to it a second
                # time once iteration index+1 ran (it was already
                # bought at the real, already-adjusted market price); an
                # ex-date buy wrongly received a dividend declared for
                # holders as of the day before; and a position sold via
                # this same fill had already been removed from
                # `portfolio.positions` by the time the dividend it WAS
                # entitled to (held through the prior close) would have
                # been applied. Applying `next_checkpoint`'s own
                # corporate actions here, before any fill, fixes all
                # three: existing holdings get correctly split-adjusted
                # and paid the dividend BEFORE the new fill lands (so the
                # new fill is never double-adjusted or wrongly paid), and
                # a same-checkpoint sell still receives the dividend it
                # earned before being removed. `CorporateActionApplier.
                # apply` is idempotent per `provenance.source_record_id`,
                # so iteration index+1's own top-of-loop pass safely
                # no-ops on whatever was already applied here.
                for security_id in sorted(tracked_ids):
                    next_actions = self._repository.get_corporate_actions(
                        security_id, next_checkpoint - timedelta(days=400), next_checkpoint,
                        as_of_time=next_checkpoint,
                    )
                    for action in next_actions:
                        integrity.check_corporate_action_timing(action, next_checkpoint)
                    warnings = corporate_action_applier.apply(next_actions, portfolio, next_checkpoint)
                    for warning in warnings:
                        integrity.record(
                            "corporate_action_correctness", IntegritySeverity.WARNING, warning, next_checkpoint
                        )
                # Keeps portfolio_view consistent with the portfolio it
                # was snapshotted from (the same invariant every other
                # portfolio.apply_*() call in this loop already
                # maintains, e.g. right after apply_fill below) -- the
                # block above just mutated `portfolio` directly.
                portfolio_view = portfolio.snapshot_view(checkpoint)
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
                # Independent audit finding (2026-09-24): two runs
                # differing ONLY in slippage_model/risk_free_rate/
                # periods_per_year previously hashed to the identical
                # configuration_version despite genuinely different
                # results (slippage_model already feeds real fills via
                # order_simulator above; risk_free_rate/periods_per_year
                # already feed compute_performance_report above) -- the
                # same "content hash must include every field that is
                # actually content" gap ADR-0195/P1-4 fixed for
                # learning.dataset's sample_fingerprint.
                "slippage_model": asdict(config.slippage_model) if hasattr(config.slippage_model, "__dataclass_fields__") else str(config.slippage_model),
                "risk_free_rate": config.risk_free_rate,
                "periods_per_year": config.periods_per_year,
                # Added only when set, so every existing run keeps its hash.
                **(
                    {"cash_interest": config.cash_interest.describe()}
                    if config.cash_interest is not None else {}
                ),
                **({"restrict_strategy_to_universe": True} if config.restrict_strategy_to_universe else {}),
                **(
                    {"settle_after_missing_checkpoints": config.settle_after_missing_checkpoints}
                    if config.settle_after_missing_checkpoints is not None else {}
                ),
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

    def _accrue_cash_interest(
        self,
        portfolio: PortfolioAccounting,
        integrity: BacktestIntegrityChecker,
        previous: datetime,
        checkpoint: datetime,
    ) -> None:
        if portfolio.cash <= 0:
            return
        rate = self._config.cash_interest.latest_annual_rate_before(checkpoint.date())
        if rate is None:
            integrity.record(
                "cash_interest_rate_missing", IntegritySeverity.WARNING,
                f"no 3-month T-bill yield within 10 days before {checkpoint.date()}; cash earned nothing",
                checkpoint,
            )
            return
        days = (checkpoint.date() - previous.date()).days
        interest = portfolio.cash * ((1.0 + rate / 365.0) ** days - 1.0)
        portfolio.accrue_cash_interest(interest, checkpoint)

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
