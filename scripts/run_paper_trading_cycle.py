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
loop. This script IS that loop -- still not "always-on" by itself (it
runs once, over a fixed window, then exits; a real external scheduler,
e.g. cron, must call it repeatedly). ADR-0073 (Session 36 continued)
made that repeated invocation actually SAFE via `--resume`: without it,
re-running this script over a range it already processed re-derives
fresh decision/sizing/risk lineage IDs every time (`build_validated_
order`'s idempotent `client_order_id` only protects a single process's
own retry, not two independent invocations) and genuinely double-
submits every order, not merely re-logs it. `--resume` skips whatever
`--paper-store` already has a real, persisted checkpoint for and
reconstructs `PaperRunnerState.value_history` from real prior portfolio
values rather than reprocessing or guessing. Building the scheduler
itself remains out of scope (this project has no server of its own to
run one on) -- e.g. a real crontab entry invoking this script daily
after market close (ADR-0075):
    30 21 * * 1-5 cd /path/to/repo && flock -n /tmp/paper_trading_cycle.lock \
        python3 scripts/run_paper_trading_cycle.py \
        --universe RESEARCH_UNIVERSE --db-path ./data/real_market_data \
        --paper-store ./data/paper_trading_store --resume \
        --start 2024-01-02 --end "$(date +%F)" --out ./data/paper_trading_cycle_report.json \
        >> ./data/paper_trading_cycle.log 2>&1
(`--start` only matters for a brand-new `--paper-store`; `--resume`
makes every later invocation pick up exactly where the last one left
off regardless of what `--start` says. `flock -n` refuses to start a
second run if a previous invocation is still executing when cron fires
again -- e.g. a slow real-network bar fetch overrunning into the next
scheduled slot -- rather than letting two processes hold `StorageEngine`
connections to the same DuckDB file at once, which this project's own
single-writer design, ADR-0002, already documents as unsupported; a
timestamped log file is where a real deployment would actually notice
that happened, since cron itself runs unattended).

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
from typing import Optional

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
from storage.trade_journal_repository import DuckDBTradeJournalRepository  # noqa: E402

from trade_journal.enums import TradeProvenance  # noqa: E402
from trade_journal.paper_adapter import reconstruct_journal_state  # noqa: E402

_UNIVERSES = {"PILOT_UNIVERSE": PILOT_UNIVERSE_V1, "RESEARCH_UNIVERSE": RESEARCH_UNIVERSE_STAGE4}

# Same bar-lookback margin scripts/run_long_horizon_validation.py's own
# split/window construction already budgets for real-world data gaps
# around a requested start date.
_WARMUP_DAYS = 30


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _last_processed_checkpoint(prediction_repository, representative_security_id: str) -> Optional[datetime]:
    """The latest `as_of_time` this store has a real, persisted
    prediction for `representative_security_id` -- `run_cycle` records
    one prediction per security every checkpoint uniformly, so any one
    security's own history is a faithful proxy for "which checkpoints
    has this store's Paper session already lived through," without
    needing to check all of them. `None` on a fresh/empty store (no
    prior run to resume from)."""
    records = prediction_repository.list_all(security_id=representative_security_id)
    if not records:
        return None
    return max(r.as_of_time for r in records)


def _next_starting_id(record_ids) -> int:
    """1 for an empty/fresh store; otherwise one past the highest
    numeric suffix already used across EVERY security this store has
    ever recorded for this ID kind (`predictor`/`decision_agent`/
    `position_sizer`/`risk_engine` each allocate from ONE shared counter
    across all securities in a cycle, not per-security -- checking only
    one security's own records would undercount how many IDs were
    really handed out). Every one of this project's ID formats is
    `<PREFIX...>-NNNNNN` -- the numeric suffix is always the last
    hyphen-separated segment, regardless of how many hyphens the prefix
    itself has (e.g. "DEC-OUT-000042")."""
    ids = list(record_ids)
    if not ids:
        return 1
    return max(int(rid.rsplit("-", 1)[1]) for rid in ids) + 1


def _reconstruct_value_history(risk_repository, representative_security_id: str, up_to: datetime) -> list:
    """Real, already-persisted portfolio values for every checkpoint up
    to and including `up_to`, in chronological order -- reconstructed
    from `RiskCheckedPosition.risk_state.portfolio_value` (one real
    snapshot per checkpoint, shared across every security assessed that
    cycle) rather than guessed or interpolated. Never fabricates a
    value for a checkpoint whose `risk_state` is unexpectedly absent --
    that checkpoint is simply skipped, matching this project's fail-
    closed discipline (a caller resuming with a resulting short history
    sees `max_drawdown`/`max_portfolio_volatility` correctly stay
    "unknown" for longer, never a fabricated gap-filled series)."""
    records = risk_repository.list_all(security_id=representative_security_id, end=up_to)
    return [r.risk_state.portfolio_value for r in records if r.risk_state is not None]


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
    parser.add_argument(
        "--resume", action="store_true",
        help=(
            "Safe to invoke repeatedly (e.g. from an external cron) with the same --start/--end/"
            "--paper-store: checkpoints already recorded in --paper-store are skipped rather than "
            "reprocessed (each run's fresh decision/sizing/risk IDs would otherwise make every "
            "resubmission a genuinely new order, not a deduplicated retry -- see ADR-0073). "
            "value_history is reconstructed from real, already-persisted portfolio values, never "
            "guessed. Without this flag, re-running an already-processed range double-submits."
        ),
    )
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

    market_data_source = InMemoryPaperMarketDataSource(bars)
    paper_config = PaperTradingConfig(initial_cash=args.initial_capital)

    store_engine = StorageEngine(StorageConfig(root_dir=args.paper_store))
    order_repository = DuckDBPaperOrderRepository(store_engine)
    fill_repository = DuckDBPaperFillRepository(store_engine)
    status_repository = DuckDBOrderStatusEventRepository(store_engine)
    # `restore()` replays whatever this store already has (nothing, on a
    # brand-new store) -- strictly more correct than the plain
    # constructor for every case, not only --resume (ADR-0073).
    session = PaperTradingSession.restore(
        paper_config, market_data_source,
        order_repository=order_repository, fill_repository=fill_repository, status_repository=status_repository,
        as_of=args.end,
    )

    prediction_repository = DuckDBPredictionRepository(store_engine)
    regime_repository = DuckDBRegimeRepository(store_engine)
    decision_repository = DuckDBDecisionRepository(store_engine)
    sizing_repository = DuckDBPositionSizingRepository(store_engine)
    risk_repository = DuckDBRiskRepository(store_engine)
    trade_journal = DuckDBTradeJournalRepository(store_engine)
    # Always reconstructed from whatever the journal already has (empty
    # for a fresh --paper-store) -- not only under --resume, the same
    # "always correct, never just a --resume special case" choice
    # ADR-0073 already made for `PaperTradingSession.restore()` and
    # `_next_starting_id` above.
    journal_state = reconstruct_journal_state(trade_journal)

    # Any --resume filtering of `checkpoints` MUST happen before `clock`/
    # `view` are built below -- `clock.index` is an index into whatever
    # list `clock` was constructed from, so building it from the
    # unfiltered range and then shortening `checkpoints` afterward would
    # silently misalign every subsequent `clock.index = i` in the main
    # loop with the wrong calendar date.
    state = PaperRunnerState()
    if args.resume:
        last_processed = _last_processed_checkpoint(prediction_repository, security_ids[0])
        if last_processed is not None:
            before_count = len(checkpoints)
            checkpoints = [c for c in checkpoints if c > last_processed]
            state.value_history.extend(_reconstruct_value_history(risk_repository, security_ids[0], last_processed))
            print(
                f"--resume: last processed checkpoint was {last_processed.date()} -- "
                f"skipping {before_count - len(checkpoints)}/{before_count} already-done checkpoint(s), "
                f"value_history seeded with {len(state.value_history)} real prior point(s).",
                flush=True,
            )
            if not checkpoints:
                print("--resume: nothing new to process in [--start, --end] -- exiting.", flush=True)
                final_account = session.account_summary(as_of=last_processed)
                report = {
                    "note": "Nothing new to process -- every requested checkpoint was already recorded.",
                    "universe": args.universe, "checkpoints_run": 0,
                    "final_cash": final_account.cash,
                    "final_positions": {sid: pos.quantity for sid, pos in final_account.positions.items() if pos.available},
                }
                args.out.parent.mkdir(parents=True, exist_ok=True)
                args.out.write_text(json.dumps(report, indent=2))
                data_engine.close()
                store_engine.close()
                return 0

    clock = BacktestClock(checkpoints)
    view = AsOfDataView(repository, clock)

    # Every component below allocates its own IDs (prediction_id/
    # composite_id/decision_id/sizing_id/risk_id) from a counter that
    # starts at 1 in a fresh process -- on a store that already has
    # persisted records (--resume or otherwise), a fresh counter WILL
    # collide with an ID a prior invocation already used, since each
    # repository's table enforces a real primary-key uniqueness
    # constraint on that ID, not just on natural_key (ADR-0073). Seeding
    # every counter from this store's own real persisted max, always --
    # not only under --resume -- makes ANY second invocation against a
    # non-empty --paper-store safe, matching the same "always correct,
    # never just a --resume special case" choice already made for
    # `PaperTradingSession.restore()` above.
    next_prediction_id = _next_starting_id(r.prediction_id for r in prediction_repository.list_all())
    next_composite_id = _next_starting_id(r.composite_id for r in regime_repository.list_composites())
    # `record_composite` also persists each axis's own `RegimeObservation`
    # (a SEPARATE, separately primary-keyed table, `regime_observations`)
    # -- both counters must be seeded, not just the composite's.
    next_observation_id = _next_starting_id(r.regime_id for r in regime_repository.list_observations())
    next_decision_id = _next_starting_id(r.decision_id for r in decision_repository.list_all())
    next_sizing_id = _next_starting_id(r.sizing_id for r in sizing_repository.list_all())
    next_risk_id = _next_starting_id(r.risk_id for r in risk_repository.list_all())

    risk_config = RiskConfig(
        max_sector_weight=args.max_sector_weight, max_order_notional=args.max_order_notional,
        max_drawdown=args.max_drawdown, max_portfolio_volatility=args.max_portfolio_volatility,
    )
    components = dict(
        predictor=DriftPredictor(PredictionConfig(lookback_days=20), starting_id=next_prediction_id),
        regime_detector=RegimeDetector(
            RegimeConfig(), starting_observation_id=next_observation_id, starting_composite_id=next_composite_id,
        ),
        decision_agent=BaselineRuleDecisionAgent(DecisionConfig(), starting_id=next_decision_id),
        position_sizer=DeterministicPositionSizer(PositionSizingConfig(), starting_id=next_sizing_id),
        risk_engine=DeterministicPortfolioRiskEngine(risk_config, starting_id=next_risk_id),
    )

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
            risk_repository=risk_repository, trade_journal=trade_journal, journal_state=journal_state,
            **components,
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
        # A run's risk_config is a real determinant of its outcome (this
        # script's own `--max-sector-weight`/`--max-order-notional`
        # flags directly change position sizes and fill counts) -- a
        # checksum that omitted it would call two runs with materially
        # different risk limits and materially different results
        # identical, the same reproducibility gap Phase 30/31 already
        # fixed for the ingestion manifest.
        "risk_config": {
            "max_sector_weight": args.max_sector_weight, "max_order_notional": args.max_order_notional,
            "max_drawdown": args.max_drawdown, "max_portfolio_volatility": args.max_portfolio_volatility,
        },
    })

    report = {
        "note": (
            "Real Paper Trading cycle run against a real market-data catalog -- "
            "every checkpoint's Prediction/Regime/Decision/Sizing/Risk output and "
            "every real order/fill is persisted in --paper-store, queryable by the "
            "same repository classes this run used. Not an always-on process -- "
            "this run covers exactly [--start, --end] and then exits. Every "
            "checkpoint's Decision/Trade also reaches the Trade Journal now "
            "(ADR-0086) -- scripts/run_learning_cycle.py can train from it."
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
        "trade_journal_decisions": len(trade_journal.list_decisions()),
        "trade_journal_trades": len(trade_journal.list_trades(provenance=TradeProvenance.PAPER_TRADING)),
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
