#!/usr/bin/env python3
"""Real, repeated Paper Trading execution CLI (Session 36, ADR-0068).

Loops `orchestration.paper_runner.run_cycle` once per trading-day
checkpoint over `[--start, --end]`, against a real DuckDB market-data
catalog (populated by `scripts/ingest_real_market_data.py`) -- the
piece `docs/specifications/PHASE-15-paper-trading.md` section 1.1
explicitly deferred ("wiring [Regime/Prediction/Decision/Sizing/Risk]
into an always-on scheduled process is a later phase's concern") and
`orchestration.paper_runner` (ADR-0067) itself deliberately stopped
short of building: `run_cycle` is a per-checkpoint function, not a
loop. This script IS that loop -- still not "always-on" (it runs once,
over a fixed historical-to-recent window, then exits; a real always-on
process would need a real external scheduler, e.g. cron, calling this
script or its equivalent repeatedly, which remains genuinely out of
scope here).

Every checkpoint's real outcome is persisted through the same
DuckDB-backed repositories `tests/integration/test_risk_lineage.py`
already established for prediction/regime/decision/sizing/risk, plus
`storage.paper_repository`'s own order/fill repositories and
`storage.broker_repository.DuckDBOrderStatusEventRepository` for
`PaperTradingSession`'s own state -- nothing here is held only in
memory and lost when the process exits.

`sector_by_security` is read directly from the chosen `UniverseDefinition`'s
own public `SymbolMetadata.sector` field (real SEC EDGAR data,
ADR-0058/ADR-0059/ADR-0066) -- never from the module-private
`_REAL_SEC_SECTOR_AND_EXCHANGE` dict directly.

A `PaperRunnerState` is carried across the whole run, so
`--max-drawdown`/`--max-portfolio-volatility` become real, evaluable
checks once enough checkpoints have accumulated (`RiskConfig.
min_history_for_volatility`, default 5) -- both default to `None`
(disabled) here, since a fresh run has no prior history to seed from
and this script does not fabricate one.

Usage (run in an environment with a real DuckDB catalog already
populated by scripts/ingest_real_market_data.py):
    python3 scripts/run_paper_trading_cycle.py \\
        --universe PILOT_UNIVERSE \\
        --db-path ./data/real_market_data \\
        --paper-store ./data/paper_trading_store \\
        --start 2024-01-02 --end 2024-03-01 \\
        --out ./data/paper_trading_cycle_report.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from backtest.asof import AsOfDataView  # noqa: E402
from backtest.clock import BacktestClock, build_daily_checkpoints  # noqa: E402

from broker.paper.config import PaperTradingConfig  # noqa: E402
from broker.paper.market_data import InMemoryPaperMarketDataSource  # noqa: E402
from broker.paper.session import PaperTradingSession  # noqa: E402

from data_infra.calendar import US_EQUITY  # noqa: E402
from data_infra.universe import PILOT_UNIVERSE_V1, RESEARCH_UNIVERSE_STAGE4  # noqa: E402
from data_infra.versioning import compute_data_version  # noqa: E402

from decision.agent import BaselineRuleDecisionAgent  # noqa: E402
from decision.config import DecisionConfig  # noqa: E402

from orchestration.paper_runner import PaperRunnerState, run_cycle  # noqa: E402

from predict.config import PredictionConfig  # noqa: E402
from predict.predictor import DriftPredictor  # noqa: E402

from regime.config import RegimeConfig  # noqa: E402
from regime.detector import RegimeDetector  # noqa: E402

from risk.config import PositionSizingConfig, RiskConfig  # noqa: E402
from risk.engine import DeterministicPortfolioRiskEngine  # noqa: E402
from risk.sizing import DeterministicPositionSizer  # noqa: E402

from storage.config import StorageConfig  # noqa: E402
from storage.data_repository import DuckDBDataRepository  # noqa: E402
from storage.decision_repository import DuckDBDecisionRepository  # noqa: E402
from storage.engine import StorageEngine  # noqa: E402
from storage.paper_repository import DuckDBPaperFillRepository, DuckDBPaperOrderRepository  # noqa: E402
from storage.broker_repository import DuckDBOrderStatusEventRepository  # noqa: E402
from storage.prediction_repository import DuckDBPredictionRepository  # noqa: E402
from storage.regime_repository import DuckDBRegimeRepository  # noqa: E402
from storage.risk_repository import DuckDBPositionSizingRepository, DuckDBRiskRepository  # noqa: E402

_UNIVERSES = {"PILOT_UNIVERSE": PILOT_UNIVERSE_V1, "RESEARCH_UNIVERSE": RESEARCH_UNIVERSE_STAGE4}

# Same bar-lookback margin scripts/run_long_horizon_validation.py's own
# split/window construction already budgets for real-world data gaps
# around a requested start date.
_WARMUP_DAYS = 30


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--universe", choices=sorted(_UNIVERSES), default="PILOT_UNIVERSE")
    parser.add_argument("--db-path", required=True, type=Path, help="Real market-data DuckDB catalog (scripts/ingest_real_market_data.py)")
    parser.add_argument("--paper-store", required=True, type=Path, help="Where this run's own Paper session/lineage state is persisted")
    parser.add_argument("--start", required=True, type=_parse_date)
    parser.add_argument("--end", required=True, type=_parse_date)
    parser.add_argument("--initial-capital", type=float, default=1_000_000.0)
    parser.add_argument("--max-sector-weight", type=float, default=None)
    parser.add_argument("--max-order-notional", type=float, default=None)
    parser.add_argument("--max-drawdown", type=float, default=None, help="Disabled by default -- see module docstring")
    parser.add_argument("--max-portfolio-volatility", type=float, default=None)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    universe = _UNIVERSES[args.universe]
    security_ids = list(universe.symbol_ids)
    sector_by_security = {s.symbol: s.sector for s in universe.symbols if s.sector is not None}

    data_engine = StorageEngine(StorageConfig(root_dir=args.db_path))
    repository = DuckDBDataRepository(data_engine, calendars={"US_EQUITY": US_EQUITY})

    calendar = repository.get_trading_calendar("US_EQUITY")
    checkpoints = build_daily_checkpoints(calendar, args.start, args.end)
    if not checkpoints:
        print("FATAL: no trading-day checkpoints in the requested [--start, --end] range", file=sys.stderr)
        return 1

    print(f"Fetching real bars for {len(security_ids)} symbols from {args.db_path} ...", flush=True)
    bars = []
    for security_id in security_ids:
        bars.extend(repository.get_bars(security_id, args.start, args.end, as_of_time=args.end))
    if not bars:
        print("FATAL: no real bars found for this universe in the requested range -- has ingestion run?", file=sys.stderr)
        return 1
    print(f"Fetched {len(bars)} real bars.", flush=True)

    clock = BacktestClock(checkpoints)
    view = AsOfDataView(repository, clock)

    market_data_source = InMemoryPaperMarketDataSource(bars)
    paper_config = PaperTradingConfig(initial_cash=args.initial_capital)

    store_engine = StorageEngine(StorageConfig(root_dir=args.paper_store))
    order_repository = DuckDBPaperOrderRepository(store_engine)
    fill_repository = DuckDBPaperFillRepository(store_engine)
    status_repository = DuckDBOrderStatusEventRepository(store_engine)
    session = PaperTradingSession(
        paper_config, market_data_source,
        order_repository=order_repository, fill_repository=fill_repository, status_repository=status_repository,
    )

    prediction_repository = DuckDBPredictionRepository(store_engine)
    regime_repository = DuckDBRegimeRepository(store_engine)
    decision_repository = DuckDBDecisionRepository(store_engine)
    sizing_repository = DuckDBPositionSizingRepository(store_engine)
    risk_repository = DuckDBRiskRepository(store_engine)

    risk_config = RiskConfig(
        max_sector_weight=args.max_sector_weight, max_order_notional=args.max_order_notional,
        max_drawdown=args.max_drawdown, max_portfolio_volatility=args.max_portfolio_volatility,
    )
    components = dict(
        predictor=DriftPredictor(PredictionConfig(lookback_days=20)),
        regime_detector=RegimeDetector(RegimeConfig()),
        decision_agent=BaselineRuleDecisionAgent(DecisionConfig()),
        position_sizer=DeterministicPositionSizer(PositionSizingConfig()),
        risk_engine=DeterministicPortfolioRiskEngine(risk_config),
    )
    state = PaperRunnerState()

    warmup_checkpoints = [c for c in checkpoints if (c - args.start).days < _WARMUP_DAYS]
    print(f"Running {len(checkpoints)} checkpoint(s) ({len(warmup_checkpoints)} within DriftPredictor's own warmup window) ...", flush=True)

    total_submitted = 0
    total_filled = 0
    for i, checkpoint in enumerate(checkpoints):
        clock.index = i
        outcomes = run_cycle(
            security_ids, checkpoint, view, session, state=state,
            sector_by_security=sector_by_security if args.max_sector_weight is not None else None,
            prediction_repository=prediction_repository, regime_repository=regime_repository,
            decision_repository=decision_repository, sizing_repository=sizing_repository,
            risk_repository=risk_repository, **components,
        )
        for outcome in outcomes:
            if outcome.submission is not None:
                total_submitted += 1
                if outcome.submission.filled_quantity:
                    total_filled += 1
        if (i + 1) % 10 == 0 or i == len(checkpoints) - 1:
            print(f"  [{i + 1}/{len(checkpoints)}] {checkpoint.date()} -- submitted so far: {total_submitted}, filled so far: {total_filled}", flush=True)

    final_account = session.account_summary(as_of=checkpoints[-1])
    checksum = compute_data_version({
        "universe": args.universe, "security_ids": sorted(security_ids),
        "start": args.start.isoformat(), "end": args.end.isoformat(),
        "initial_capital": args.initial_capital,
    })

    report = {
        "note": (
            "Real Paper Trading cycle run against a real market-data catalog -- "
            "every checkpoint's Prediction/Regime/Decision/Sizing/Risk output and "
            "every real order/fill is persisted in --paper-store, queryable by the "
            "same repository classes this run used. Not an always-on process -- "
            "this run covers exactly [--start, --end] and then exits."
        ),
        "universe": args.universe,
        "start": args.start.isoformat(),
        "end": args.end.isoformat(),
        "checkpoints_run": len(checkpoints),
        "total_orders_submitted": total_submitted,
        "total_orders_with_a_fill": total_filled,
        "final_cash": final_account.cash,
        "final_positions": {sid: pos.quantity for sid, pos in final_account.positions.items() if pos.available},
        "value_history_length": len(state.value_history),
        "risk_config": {
            "max_sector_weight": args.max_sector_weight, "max_order_notional": args.max_order_notional,
            "max_drawdown": args.max_drawdown, "max_portfolio_volatility": args.max_portfolio_volatility,
        },
        "content_checksum": checksum,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2))

    print(f"Checkpoints run: {len(checkpoints)}")
    print(f"Orders submitted: {total_submitted} (filled: {total_filled})")
    print(f"Final cash: {final_account.cash}")
    print(f"Report written to: {args.out}")
    data_engine.close()
    store_engine.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
