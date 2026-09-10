#!/usr/bin/env python3
"""Real, repeated Paper Trading execution CLI -- MULTI-STRATEGY variant
(Session 36 continued, ADR-0110).

`scripts/run_paper_trading_cycle.py` (ADR-0068/ADR-0073/ADR-0082) runs
exactly ONE strategy ("baseline_rule") against ONE `--paper-store`. The
account owner asked ("멀티 전략 ㄱㄱ", following up on an earlier future-
work note this session recorded in `docs/PROJECT_STATUS.md`: "45개
전략을 한 번에 페이퍼 트레이딩으로 돌릴 수 있는 멀티 전략 러너를 나중에
만들기로 함") for a runner that can paper-trade more than one strategy
at once. This script is that runner.

**Track records stay fully independent, by construction, never
retroactively merged** (the account owner's own earlier question this
session: "지금까지 쌓은 B&H 트랙레코드가 나중에 다른 전략에 어떻게
적용되는지" -- answer given then, enforced here in code now): each
strategy named in `--strategies` gets its OWN subdirectory under
`--paper-store-root` (`<root>/<strategy-name>/`), its own
`PaperTradingSession`, its own cash/positions/orders/fills, and its own
Prediction/Regime/Decision/Sizing/Risk/Trade-Journal repositories
(RUN_CYCLE-kind strategies only -- see `orchestration.paper_strategies`).
A strategy started today begins its own track record from today; it
never inherits another strategy's past fills.

**Shared, real market-data catalog, read-only, not re-fetched per
strategy**: exactly one `--db-path` is read once into memory (`Fetching
real bars ...` below) and handed to every strategy's own
`InMemoryPaperMarketDataSource` -- running N strategies here costs the
SAME number of Tiingo/Stooq API calls as running 1 (zero calls, since
this script never calls a provider at all; that only happens in
`scripts/ingest_real_market_data.py`, a separate, prior step). This is
the concrete answer to the account owner's own "Tiingo 한도 때문에 안
되는거 아니야?" question this session -- confirmed in code here, not
just asserted.

**RULE 0.8 boundary**: only strategies registered in `orchestration.
paper_strategies.STRATEGIES` can be named here -- none of the 45
factor-research candidates are registered there yet (none has a real
validated result), so none can be run through this script either. This
script is infrastructure, built ahead of any strategy being promoted to
it, exactly as the future-work note said it would be.

Usage (run in an environment with a real DuckDB catalog already
populated by scripts/ingest_real_market_data.py):
    python3 scripts/run_multi_strategy_paper_trading_cycle.py \\
        --universe PILOT_UNIVERSE \\
        --db-path ./data/real_market_data \\
        --paper-store-root ./data/multi_strategy_paper_trading_store \\
        --strategies baseline_rule,random_walk_baseline,buy_and_hold \\
        --start 2024-01-02 --end 2024-03-01 --resume \\
        --out ./data/multi_strategy_paper_trading_cycle_report.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from backtest.asof import AsOfDataView  # noqa: E402
from backtest.clock import BacktestClock, build_daily_checkpoints  # noqa: E402

from broker.paper.config import PaperTradingConfig  # noqa: E402
from broker.paper.market_data import InMemoryPaperMarketDataSource  # noqa: E402
from broker.paper.session import PaperTradingSession  # noqa: E402
from broker.paper.us_longterm_runner import run_buy_and_hold_paper_session  # noqa: E402

from data_infra.calendar import US_EQUITY  # noqa: E402
from data_infra.universe import PILOT_UNIVERSE_V1, RESEARCH_UNIVERSE_STAGE4  # noqa: E402

from orchestration.paper_runner import PaperRunnerState, compute_portfolio_snapshot, run_cycle  # noqa: E402
from orchestration.paper_strategies import (  # noqa: E402
    STRATEGIES,
    PaperStrategyKind,
    RunCycleStartingIds,
    build_run_cycle_components,
)

from risk.config import RiskConfig  # noqa: E402

from storage.broker_repository import DuckDBBrokerRequestRepository, DuckDBBrokerResponseRepository, DuckDBOrderStatusEventRepository  # noqa: E402
from storage.config import StorageConfig  # noqa: E402
from storage.data_repository import DuckDBDataRepository  # noqa: E402
from storage.decision_repository import DuckDBDecisionRepository  # noqa: E402
from storage.engine import StorageEngine  # noqa: E402
from storage.paper_repository import DuckDBPaperFillRepository, DuckDBPaperOrderRepository  # noqa: E402
from storage.prediction_repository import DuckDBPredictionRepository  # noqa: E402
from storage.regime_repository import DuckDBRegimeRepository  # noqa: E402
from storage.risk_repository import DuckDBPositionSizingRepository, DuckDBRiskRepository  # noqa: E402
from storage.trade_journal_repository import DuckDBTradeJournalRepository  # noqa: E402

_UNIVERSES = {"PILOT_UNIVERSE": PILOT_UNIVERSE_V1, "RESEARCH_UNIVERSE": RESEARCH_UNIVERSE_STAGE4}


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _next_starting_id(record_ids) -> int:
    """Identical logic to `scripts/run_paper_trading_cycle.py`'s own
    helper of the same name -- duplicated rather than imported, since
    that script's copy is a private, unexported module-level function
    and this script's own `--paper-store-root/<name>/` isolation means
    each strategy's IDs are seeded independently anyway (never a shared
    counter across strategies, matching the "fully independent track
    records" guarantee this module's docstring already states)."""
    ids = list(record_ids)
    if not ids:
        return 1
    return max(int(rid.rsplit("-", 1)[1]) for rid in ids) + 1


def _last_processed_checkpoint(prediction_repository, representative_security_id: str) -> Optional[datetime]:
    records = prediction_repository.list_all(security_id=representative_security_id)
    if not records:
        return None
    return max(r.as_of_time for r in records)


def _reconstruct_value_history(risk_repository, representative_security_id: str, up_to: datetime) -> list:
    records = risk_repository.list_all(security_id=representative_security_id, end=up_to)
    return [r.risk_state.portfolio_value for r in records if r.risk_state is not None]


def _run_run_cycle_strategy(
    *, name, security_ids, sector_by_security, checkpoints, view, clock, session, store_engine,
    risk_config, resume: bool,
) -> dict:
    """Runs a `PaperStrategyKind.RUN_CYCLE` strategy over `checkpoints`
    against its own already-isolated `store_engine` -- the same
    per-checkpoint loop `scripts/run_paper_trading_cycle.py` runs for
    its one hardcoded strategy, generalized to any name `orchestration.
    paper_strategies.build_run_cycle_components` accepts."""
    prediction_repository = DuckDBPredictionRepository(store_engine)
    regime_repository = DuckDBRegimeRepository(store_engine)
    decision_repository = DuckDBDecisionRepository(store_engine)
    sizing_repository = DuckDBPositionSizingRepository(store_engine)
    risk_repository = DuckDBRiskRepository(store_engine)
    trade_journal_repository = DuckDBTradeJournalRepository(store_engine)

    state = PaperRunnerState()
    strategy_checkpoints = checkpoints
    if resume:
        last_processed = _last_processed_checkpoint(prediction_repository, security_ids[0])
        if last_processed is not None:
            strategy_checkpoints = [c for c in checkpoints if c > last_processed]
            state.value_history.extend(_reconstruct_value_history(risk_repository, security_ids[0], last_processed))

    starting_ids = RunCycleStartingIds(
        prediction=_next_starting_id(r.prediction_id for r in prediction_repository.list_all()),
        observation=_next_starting_id(r.regime_id for r in regime_repository.list_observations()),
        composite=_next_starting_id(r.composite_id for r in regime_repository.list_composites()),
        decision=_next_starting_id(r.decision_id for r in decision_repository.list_all()),
        sizing=_next_starting_id(r.sizing_id for r in sizing_repository.list_all()),
        risk=_next_starting_id(r.risk_id for r in risk_repository.list_all()),
    )
    components = build_run_cycle_components(name, risk_config=risk_config, starting_ids=starting_ids)

    total_submitted = 0
    total_filled = 0
    checkpoint_index_by_value = {c: i for i, c in enumerate(checkpoints)}
    for checkpoint in strategy_checkpoints:
        clock.index = checkpoint_index_by_value[checkpoint]
        outcomes = run_cycle(
            security_ids, checkpoint, view, session, state=state,
            sector_by_security=sector_by_security,
            prediction_repository=prediction_repository, regime_repository=regime_repository,
            decision_repository=decision_repository, sizing_repository=sizing_repository,
            risk_repository=risk_repository, trade_journal_repository=trade_journal_repository, **components,
        )
        for outcome in outcomes:
            if outcome.submission is not None:
                total_submitted += 1
                if outcome.submission.filled_quantity:
                    total_filled += 1

    return {
        "kind": PaperStrategyKind.RUN_CYCLE.value,
        "checkpoints_run": len(strategy_checkpoints),
        "total_orders_submitted": total_submitted,
        "total_orders_with_a_fill": total_filled,
        "value_history_length": len(state.value_history),
    }


def _run_buy_and_hold_strategy(
    *, security_ids, checkpoints, view, clock, market_data_source, session, store_engine, configuration_version,
) -> dict:
    """Runs `PaperStrategyKind.BUY_AND_HOLD`: one equal-weight buy across
    `security_ids` on the FIRST checkpoint only if this store has no
    orders yet (idempotent across `--resume` invocations -- never a
    second buy), then a per-checkpoint mark-to-market snapshot via
    `orchestration.paper_runner.compute_portfolio_snapshot` for every
    checkpoint in the requested range (cheap, read-only, safe to
    recompute every invocation since it submits no orders of its own).

    `clock.index` MUST be advanced to each checkpoint before the
    snapshot call, exactly like `_run_run_cycle_strategy` already does
    for `run_cycle` -- `AsOfDataView.get_bars` sources its point-in-time
    cutoff from `clock.current_time`, not from any argument passed to
    it (`backtest.asof.AsOfDataView.get_bars`), so skipping this would
    silently value every checkpoint using whatever the clock happened
    to be left at, not that checkpoint's own real as-of-time."""
    order_repository = DuckDBPaperOrderRepository(store_engine)
    request_repository = DuckDBBrokerRequestRepository(store_engine)
    response_repository = DuckDBBrokerResponseRepository(store_engine)

    already_bought = len(order_repository.list_all()) > 0
    skipped_symbols: tuple = ()
    if not already_bought and checkpoints:
        result = run_buy_and_hold_paper_session(
            security_ids, market_data_source, session,
            buy_time=checkpoints[0], configuration_version=configuration_version,
            request_repository=request_repository, response_repository=response_repository,
        )
        skipped_symbols = result.skipped_symbols

    value_history = []
    for i, checkpoint in enumerate(checkpoints):
        clock.index = i
        value_history.append(compute_portfolio_snapshot(session, view, checkpoint).portfolio_value)

    return {
        "kind": PaperStrategyKind.BUY_AND_HOLD.value,
        "checkpoints_run": len(checkpoints),
        "already_bought_before_this_run": already_bought,
        "skipped_symbols": list(skipped_symbols),
        "value_history_length": len(value_history),
        "final_portfolio_value": value_history[-1] if value_history else None,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--universe", choices=sorted(_UNIVERSES), default="PILOT_UNIVERSE")
    parser.add_argument("--db-path", required=True, type=Path)
    parser.add_argument("--paper-store-root", required=True, type=Path, help="Each strategy's own state is persisted under <root>/<strategy-name>/")
    parser.add_argument(
        "--strategies", type=str, default=None,
        help="Comma-separated strategy names from orchestration.paper_strategies.STRATEGIES (default: all registered)",
    )
    parser.add_argument("--start", required=True, type=_parse_date)
    parser.add_argument("--end", required=True, type=_parse_date)
    parser.add_argument("--initial-capital", type=float, default=1_000_000.0)
    parser.add_argument("--max-sector-weight", type=float, default=None)
    parser.add_argument("--max-order-notional", type=float, default=None)
    parser.add_argument("--max-drawdown", type=float, default=None)
    parser.add_argument("--max-portfolio-volatility", type=float, default=None)
    parser.add_argument("--reentry-cooldown-days", type=int, default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    strategy_names = sorted(STRATEGIES) if args.strategies is None else [s.strip() for s in args.strategies.split(",") if s.strip()]
    unknown = [name for name in strategy_names if name not in STRATEGIES]
    if unknown:
        print(f"FATAL: unregistered strategy name(s): {unknown} -- see orchestration.paper_strategies.STRATEGIES", file=sys.stderr)
        return 1

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

    print(f"Fetching real bars for {len(security_ids)} symbols from {args.db_path} (shared across {len(strategy_names)} strategy(ies)) ...", flush=True)
    bars = []
    for security_id in security_ids:
        bars.extend(repository.get_bars(security_id, args.start, args.end, as_of_time=args.end))
    if not bars:
        print("FATAL: no real bars found for this universe in the requested range -- has ingestion run?", file=sys.stderr)
        return 1
    print(f"Fetched {len(bars)} real bars.", flush=True)

    risk_config = RiskConfig(
        max_sector_weight=args.max_sector_weight, max_order_notional=args.max_order_notional,
        max_drawdown=args.max_drawdown, max_portfolio_volatility=args.max_portfolio_volatility,
        reentry_cooldown_days=args.reentry_cooldown_days,
    )

    results: dict = {}
    for name in strategy_names:
        spec = STRATEGIES[name]
        print(f"=== Strategy '{name}' ({spec.kind.value}) ===", flush=True)

        # A fresh InMemoryPaperMarketDataSource/AsOfDataView/PaperTradingSession
        # per strategy -- `PaperMarketDataSource`/`PaperBrokerAdapter` hold
        # mutable per-session state (fills, cash), so sharing one instance
        # across strategies would let one strategy's orders affect
        # another's account, defeating the whole point of this script.
        market_data_source = InMemoryPaperMarketDataSource(bars)
        clock = BacktestClock(checkpoints)
        view = AsOfDataView(repository, clock)
        paper_config = PaperTradingConfig(initial_cash=args.initial_capital)

        paper_store = args.paper_store_root / name
        store_engine = StorageEngine(StorageConfig(root_dir=paper_store))
        order_repository = DuckDBPaperOrderRepository(store_engine)
        fill_repository = DuckDBPaperFillRepository(store_engine)
        status_repository = DuckDBOrderStatusEventRepository(store_engine)
        session = PaperTradingSession.restore(
            paper_config, market_data_source,
            order_repository=order_repository, fill_repository=fill_repository, status_repository=status_repository,
            as_of=args.end,
        )

        if spec.kind == PaperStrategyKind.RUN_CYCLE:
            outcome = _run_run_cycle_strategy(
                name=name, security_ids=security_ids, sector_by_security=sector_by_security if args.max_sector_weight is not None else None,
                checkpoints=checkpoints, view=view, clock=clock, session=session, store_engine=store_engine,
                risk_config=risk_config, resume=args.resume,
            )
        else:
            outcome = _run_buy_and_hold_strategy(
                security_ids=security_ids, checkpoints=checkpoints, view=view, clock=clock,
                market_data_source=market_data_source, session=session, store_engine=store_engine,
                configuration_version=session.config.configuration_version(),
            )

        final_account = session.account_summary(as_of=checkpoints[-1])
        outcome["final_cash"] = final_account.cash
        outcome["final_positions"] = {sid: pos.quantity for sid, pos in final_account.positions.items() if pos.available}
        results[name] = outcome
        store_engine.close()

    data_engine.close()

    report = {
        "note": (
            "Real multi-strategy Paper Trading cycle run against ONE shared, already-ingested "
            "real market-data catalog -- each strategy's own state (cash/positions/orders/fills, "
            "and for RUN_CYCLE-kind strategies also Prediction/Regime/Decision/Sizing/Risk/Trade "
            "Journal history) is fully isolated under its own --paper-store-root/<name>/ "
            "subdirectory. Not an always-on process -- this run covers exactly [--start, --end] "
            "for every requested strategy and then exits."
        ),
        "universe": args.universe,
        "start": args.start.isoformat(),
        "end": args.end.isoformat(),
        "strategies": results,
        "risk_config": {
            "max_sector_weight": args.max_sector_weight, "max_order_notional": args.max_order_notional,
            "max_drawdown": args.max_drawdown, "max_portfolio_volatility": args.max_portfolio_volatility,
            "reentry_cooldown_days": args.reentry_cooldown_days,
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2))

    for name, outcome in results.items():
        print(f"[{name}] checkpoints_run={outcome['checkpoints_run']} final_cash={outcome['final_cash']}")
    print(f"Report written to: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
