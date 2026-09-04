#!/usr/bin/env python3
"""Paper trading cycle CLI: drives the existing Predict -> Regime ->
Decision -> Position Sizing -> Risk Engine -> Order Validation ->
`PaperTradingSession` chain (Phase 6-8, 13, 15, all unmodified by this
script) across a real, already-ingested price history, one checkpoint
per US-equity trading day in `[--start, --end]`.

This is deliberately NOT a new order-construction path: every order this
script submits goes through the same `broker.validation.build_validated_order`
+ `broker.paper.session.PaperTradingSession.submit` boundary
`tests/integration/test_paper_trading_real_market_data.py` and
`broker/paper/us_longterm_runner.py` already exercise -- only the loop
tying a `DriftPredictor` (Phase 6 baseline, no ML) to that chain across
many checkpoints and many symbols is new.

`--paper-store` is a *separate*, persistent DuckDB catalog from
`--db-path` (mirrors `PaperTradingSession`'s own order/fill/status
repositories, `storage/paper_repository.py` + `storage/broker_repository.py`)
-- running this script again against the same `--paper-store` continues
writing into the same paper trading history rather than starting a new
account from scratch, exactly like `broker.paper.session.PaperTradingSession.restore`
is designed for (this script does not call `restore` itself -- each
invocation starts a fresh in-memory `PaperBrokerAdapter` seeded with
`--initial-capital`, so re-running is a NEW simulated account each time,
not a resume; a future phase could add a `--resume` flag using `restore`
without changing anything below it).

**"DriftPredictor's own warmup window"**: `predict.predictor.DriftPredictor`
(default `lookback_days=60`) needs `lookback_days + 1` real trading bars
before a checkpoint, or it honestly returns `expected_return=None`
(insufficient data, never a fabricated forecast) -- see that module's
own `predict()`. A checkpoint is counted here as "within warmup" when
EVERY symbol in the universe still lacks that much trailing history as
of that checkpoint (so literally no signal was available to anyone that
day), computed once up front from the same real bars this script already
fetches, before the actual checkpoint loop runs.

Usage (run in an environment with a real DuckDB catalog already
populated by scripts/ingest_real_market_data.py):
    python3 scripts/run_paper_trading_cycle.py \\
        --universe RESEARCH_UNIVERSE \\
        --db-path ./data/real_market_data \\
        --paper-store ./data/paper_trading_store \\
        --start 2023-06-01 --end 2023-08-01 \\
        --out ./data/paper_trading_cycle_report.json

Never executed by this repository's own automated test suite (it reads
real, already-ingested data from a path the test suite never has, and
its runtime scales with universe size x checkpoint count).
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from backtest.asof import AsOfDataView  # noqa: E402
from backtest.clock import BacktestClock, build_daily_checkpoints  # noqa: E402

from broker.enums import BrokerOrderStatus  # noqa: E402
from broker.paper.config import PaperTradingConfig  # noqa: E402
from broker.paper.market_data import InMemoryPaperMarketDataSource  # noqa: E402
from broker.paper.session import PaperTradingSession  # noqa: E402
from broker.validation import build_validated_order  # noqa: E402

from data_infra.calendar import US_EQUITY  # noqa: E402
from data_infra.universe import PILOT_UNIVERSE_V1, RESEARCH_UNIVERSE_STAGE3  # noqa: E402

from decision.agent import BaselineRuleDecisionAgent  # noqa: E402
from decision.config import DecisionConfig  # noqa: E402

from predict.config import PredictionConfig  # noqa: E402
from predict.predictor import DriftPredictor  # noqa: E402

from regime.config import RegimeConfig  # noqa: E402
from regime.detector import RegimeDetector  # noqa: E402
from regime.features import data_completeness  # noqa: E402

from risk.config import PositionSizingConfig, RiskConfig  # noqa: E402
from risk.engine import DeterministicPortfolioRiskEngine  # noqa: E402
from risk.enums import RiskCheckStatus  # noqa: E402
from risk.sizing import DeterministicPositionSizer  # noqa: E402

from storage.broker_repository import DuckDBOrderStatusEventRepository  # noqa: E402
from storage.config import StorageConfig  # noqa: E402
from storage.data_repository import DuckDBDataRepository  # noqa: E402
from storage.engine import StorageEngine  # noqa: E402
from storage.paper_repository import DuckDBPaperFillRepository, DuckDBPaperOrderRepository  # noqa: E402

from trade_journal.enums import TradeProvenance  # noqa: E402

_UNIVERSES = {"PILOT_UNIVERSE": PILOT_UNIVERSE_V1, "RESEARCH_UNIVERSE": RESEARCH_UNIVERSE_STAGE3}
_PRINT_EVERY = 10


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _price_of(bar) -> float:
    return bar.adjusted_close if bar.adjusted_close is not None else bar.close


def _count_warmup_checkpoints(
    checkpoints: tuple[datetime, ...],
    security_ids: list[str],
    extended_bars_by_symbol: dict[str, list],
    prediction_config: PredictionConfig,
) -> int:
    """Mirrors `DriftPredictor.predict`'s own data-sufficiency gate
    (`len(bars) < 2 or reliability < min_data_completeness`) directly
    against already-fetched bars, so this can run once up front instead
    of duplicating every real `predict()` call the main loop below
    already makes."""
    lookback = timedelta(days=prediction_config.lookback_days * 2)
    required = prediction_config.lookback_days + 1
    sorted_bars = {sid: sorted(bars, key=lambda b: b.timestamp) for sid, bars in extended_bars_by_symbol.items()}

    warmup_count = 0
    for checkpoint in checkpoints:
        window_start = checkpoint - lookback
        any_ready = False
        for sid in security_ids:
            bars = sorted_bars.get(sid, [])
            count = sum(1 for b in bars if window_start <= b.timestamp <= checkpoint)
            reliability = data_completeness(count, required)
            if not (count < 2 or reliability < prediction_config.min_data_completeness):
                any_ready = True
                break
        if not any_ready:
            warmup_count += 1
    return warmup_count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--universe", choices=sorted(_UNIVERSES), default="PILOT_UNIVERSE")
    parser.add_argument("--db-path", required=True, type=Path, help="Path to the DuckDB catalog scripts/ingest_real_market_data.py already populated")
    parser.add_argument("--paper-store", required=True, type=Path, help="Path to a (possibly new) DuckDB catalog for this paper trading account's orders/fills/status history")
    parser.add_argument("--start", required=True, type=_parse_date)
    parser.add_argument("--end", required=True, type=_parse_date)
    parser.add_argument("--initial-capital", type=float, default=10_000.0, help="Matches PAPER_CAPITAL_USD (broker.paper.us_longterm_config), not a currency-converted figure")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    universe = _UNIVERSES[args.universe]
    security_ids = list(universe.symbol_ids)
    report_path = args.out or (args.paper_store / "paper_trading_cycle_report.json")

    prediction_config = PredictionConfig()

    data_engine = StorageEngine(StorageConfig(root_dir=args.db_path))
    repository = DuckDBDataRepository(data_engine, calendars={"US_EQUITY": US_EQUITY})
    paper_engine = StorageEngine(StorageConfig(root_dir=args.paper_store))

    try:
        print(f"Fetching real bars for {len(security_ids)} symbols from {args.db_path} ...")
        bars_by_symbol = {
            sid: repository.get_bars(sid, args.start, args.end, as_of_time=args.end)
            for sid in security_ids
        }
        total_bars = sum(len(bars) for bars in bars_by_symbol.values())
        print(f"Fetched {total_bars} real bars.")

        # Extended history purely for the warmup diagnostic below --
        # DriftPredictor's own lookback reaches back before `--start`
        # into whatever real history the catalog already has, so
        # counting warmup checkpoints honestly requires seeing that
        # earlier data too, not just the [--start, --end] window.
        extended_start = args.start - timedelta(days=prediction_config.lookback_days * 2 + 5)
        extended_bars_by_symbol = {
            sid: repository.get_bars(sid, extended_start, args.end, as_of_time=args.end)
            for sid in security_ids
        }

        calendar = repository.get_trading_calendar("US_EQUITY")
        checkpoints = build_daily_checkpoints(calendar, args.start.date(), args.end.date())
        if not checkpoints:
            print("ERROR: no US_EQUITY trading day found in [--start, --end].", file=sys.stderr)
            return 1
        clock = BacktestClock(checkpoints)
        view = AsOfDataView(repository, clock)

        warmup_count = _count_warmup_checkpoints(checkpoints, security_ids, extended_bars_by_symbol, prediction_config)
        print(f"Running {len(checkpoints)} checkpoint(s) ({warmup_count} within DriftPredictor's own warmup window) ...")

        all_bars = [bar for bars in bars_by_symbol.values() for bar in bars]
        market_data = InMemoryPaperMarketDataSource(all_bars)
        paper_config = PaperTradingConfig(initial_cash=args.initial_capital)
        configuration_version = paper_config.configuration_version()
        session = PaperTradingSession(
            paper_config, market_data,
            order_repository=DuckDBPaperOrderRepository(paper_engine),
            fill_repository=DuckDBPaperFillRepository(paper_engine),
            status_repository=DuckDBOrderStatusEventRepository(paper_engine),
        )

        predictor = DriftPredictor(prediction_config)
        regime_detector = RegimeDetector(RegimeConfig())
        agent = BaselineRuleDecisionAgent(DecisionConfig())
        sizer = DeterministicPositionSizer(PositionSizingConfig())
        risk_engine = DeterministicPortfolioRiskEngine(RiskConfig())

        submitted_order_ids: list[str] = []
        checkpoint_reports: list[dict] = []

        for i in range(len(checkpoints)):
            clock.index = i
            checkpoint_time = clock.current_time
            portfolio = session.adapter.accounting.snapshot_view(checkpoint_time)
            value_history = [p.portfolio_value for p in session.adapter.accounting.value_series]
            turnover = session.adapter.accounting.turnover()

            for security_id in security_ids:
                prediction = predictor.predict(view, security_id, provenance=TradeProvenance.PAPER_TRADING)
                regime = regime_detector.compute_composite(view, security_id, provenance=TradeProvenance.PAPER_TRADING)
                decision = agent.decide(security_id, checkpoint_time, prediction, regime, portfolio, provenance=TradeProvenance.PAPER_TRADING)

                bar = market_data.get_reference_bar(security_id, as_of=checkpoint_time)
                current_price = _price_of(bar) if bar is not None else None

                sizing = sizer.size(
                    security_id, checkpoint_time, decision, prediction, regime, portfolio,
                    current_price=current_price, provenance=TradeProvenance.PAPER_TRADING,
                )
                risk_checked = risk_engine.assess(
                    security_id, checkpoint_time, sizing, portfolio,
                    current_price=current_price, value_history=value_history, turnover=turnover,
                    provenance=TradeProvenance.PAPER_TRADING,
                )

                if risk_checked.status not in (RiskCheckStatus.PASS, RiskCheckStatus.REDUCE):
                    continue

                current_quantity = portfolio.quantity_of(security_id)
                validation = build_validated_order(risk_checked, current_quantity=current_quantity, configuration_version=configuration_version)
                if validation.validated_order is None:
                    continue

                session.submit(validation.validated_order, requested_at=checkpoint_time)
                submitted_order_ids.append(validation.validated_order.client_order_id)

                # Refreshed so the NEXT symbol this same checkpoint sizes
                # against the cash this order actually consumed -- new
                # positions' market value is not yet reflected (that
                # happens once, below, via mark_to_market), only cash.
                portfolio = session.adapter.accounting.snapshot_view(checkpoint_time)

            # Let any still-open order from an earlier checkpoint (e.g.
            # PENDING because no bar was available yet) attempt to fill
            # against today's newly-available bar.
            session.advance(checkpoint_time)

            prices = {}
            for security_id in security_ids:
                bar = market_data.get_reference_bar(security_id, as_of=checkpoint_time)
                if bar is not None:
                    prices[security_id] = _price_of(bar)
            session.adapter.accounting.mark_to_market(prices, checkpoint_time)

            filled_so_far = sum(
                1 for cid in submitted_order_ids
                if session.adapter.get_order_status(cid, as_of=checkpoint_time).status == BrokerOrderStatus.FILLED
            )
            checkpoint_reports.append({
                "index": i + 1,
                "as_of": checkpoint_time.isoformat(),
                "submitted_so_far": len(submitted_order_ids),
                "filled_so_far": filled_so_far,
                "cash": session.adapter.cash,
            })
            if (i + 1) % _PRINT_EVERY == 0 or (i + 1) == len(checkpoints):
                print(f"  [{i + 1}/{len(checkpoints)}] {checkpoint_time.date()} -- submitted so far: {len(submitted_order_ids)}, filled so far: {filled_so_far}")

        final_cash = session.adapter.cash
        final_filled = checkpoint_reports[-1]["filled_so_far"] if checkpoint_reports else 0
        final_portfolio_value = (
            session.adapter.accounting.value_series[-1].portfolio_value
            if session.adapter.accounting.value_series else final_cash
        )

        report = {
            "note": (
                "REAL market data (as already ingested by scripts/ingest_real_market_data.py) "
                "driven through the unmodified Predict -> Regime -> Decision -> Position Sizing "
                "-> Risk Engine -> Order Validation -> PaperTradingSession chain, one checkpoint "
                "per US_EQUITY trading day. Every order below was rejected/reduced/passed by the "
                "real risk_checked_position + submitted through broker.validation.build_validated_order "
                "-- nothing here bypasses that boundary. Not a performance claim: DriftPredictor is "
                "an explicitly-labeled deterministic baseline (no ML, no claimed forecasting skill)."
            ),
            "universe": universe.name,
            "universe_version": universe.version,
            "security_ids": security_ids,
            "start": args.start.isoformat(),
            "end": args.end.isoformat(),
            "db_path": str(args.db_path),
            "paper_store": str(args.paper_store),
            "initial_capital": args.initial_capital,
            "symbol_count": len(security_ids),
            "bar_count": total_bars,
            "checkpoints_run": len(checkpoints),
            "checkpoints_in_warmup": warmup_count,
            "prediction_lookback_days": prediction_config.lookback_days,
            "orders_submitted": len(submitted_order_ids),
            "orders_filled": final_filled,
            "final_cash": final_cash,
            "final_portfolio_value": final_portfolio_value,
            "checkpoints": checkpoint_reports,
        }

        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, default=str))

        print(f"Checkpoints run: {len(checkpoints)}")
        print(f"Orders submitted: {len(submitted_order_ids)} (filled: {final_filled})")
        print(f"Final cash: {final_cash}")
        print(f"Report written to: {report_path}")
        return 0
    finally:
        data_engine.close()
        paper_engine.close()


if __name__ == "__main__":
    raise SystemExit(main())
