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

**Trade Journal (Session 36 continued, ADR-0096): always populated.**
Every real fill this run produces is now also recorded as a real
`trade_journal.models.TradeRecord` in `--paper-store` (via `orchestration.
paper_runner.run_cycle`'s own `trade_journal_repository` parameter) --
closing a real, previously-undiscovered gap: before ADR-0096, this
script's own Paper Trading runs never populated the Trade Journal at
all (only `broker.paper.*`'s own order/fill repositories). This is
unconditional, unlike `--reentry-cooldown-days` below -- the Trade
Journal itself has no "off" switch, only the risk limit that reads it
does. `--reentry-cooldown-days` (`RiskConfig.reentry_cooldown_days`,
ratified at 5 trading days -- ADR-0095 -- but `None`/disabled by
default here, same treatment as every other ratified risk limit)
supplies that real exit history to `PortfolioRiskEngine.assess`'s
reentry-cooldown check when set.

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
from broker.paper.performance import compute_paper_performance_report  # noqa: E402
from broker.paper.session import PaperTradingSession  # noqa: E402

from data_infra.calendar import US_EQUITY_NYSE  # noqa: E402
from data_infra.universe import PILOT_UNIVERSE_V1, RESEARCH_UNIVERSE_STAGE4  # noqa: E402
from data_infra.versioning import compute_data_version  # noqa: E402

from orchestration.paper_runner import PaperRunnerState, equity_history_from_risk_repository, run_cycle  # noqa: E402
from orchestration.paper_strategies import RunCycleStartingIds, build_run_cycle_components  # noqa: E402

from risk.config import PositionSizingConfig, RiskConfig  # noqa: E402

from storage.config import StorageConfig  # noqa: E402
from storage.data_repository import DuckDBDataRepository  # noqa: E402
from storage.decision_repository import DuckDBDecisionRepository  # noqa: E402
from storage.engine import StorageEngine  # noqa: E402
from storage.paper_performance_repository import DuckDBPaperPerformanceReportRepository  # noqa: E402
from storage.paper_repository import DuckDBPaperFillRepository, DuckDBPaperOrderRepository  # noqa: E402
from storage.broker_repository import DuckDBOrderStatusEventRepository  # noqa: E402
from storage.prediction_repository import DuckDBPredictionRepository  # noqa: E402
from storage.regime_repository import DuckDBRegimeRepository  # noqa: E402
from storage.risk_repository import DuckDBPositionSizingRepository, DuckDBRiskRepository  # noqa: E402
from storage.serialization import paper_performance_report_to_payload  # noqa: E402
from storage.trade_journal_repository import DuckDBTradeJournalRepository  # noqa: E402

from trade_journal.enums import TradeProvenance  # noqa: E402

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
    """Real, already-persisted portfolio values only (no timestamps) --
    what `PaperRunnerState.value_history` seeding needs. See
    `orchestration.paper_runner.equity_history_from_risk_repository` for
    the timestamped version and for why this repository, not
    `PortfolioAccounting`, is the durable source."""
    return [value for _, value in equity_history_from_risk_repository(risk_repository, representative_security_id, up_to=up_to)]


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
        "--lot-size", type=float, default=1.0,
        help=(
            "risk.config.PositionSizingConfig.lot_size, threaded through unchanged (Session 38) -- "
            "quantities are already floored to a multiple of this, so a fractional value (e.g. 0.0001) "
            "produces genuinely fractional share counts. Was already supported at the data-model level "
            "(ValidatedOrder.quantity/Fill.quantity/Position.quantity are all plain float -- confirmed by "
            "a repo-wide search for an int(...)-cast quantity, finding none); this flag is the first way "
            "to actually reach it from this script, for a real broker that supports fractional buys "
            "(the account owner's own Toss Securities does). Default 1.0 (whole shares) preserves "
            "every existing behavior exactly."
        ),
    )
    parser.add_argument(
        "--reentry-cooldown-days", type=int, default=None,
        help=(
            "Disabled by default (RiskConfig.reentry_cooldown_days, ratified at 5 -- ADR-0095 -- "
            "but not baked in as this flag's own default, same treatment as every other ratified "
            "risk limit). When set, this run's own Trade Journal (always populated in --paper-store "
            "as of ADR-0096, regardless of this flag) supplies real exit history to the cooldown check."
        ),
    )
    parser.add_argument(
        "--pending-order-ttl-days", type=int, default=None,
        help=(
            "PaperTradingConfig.pending_order_ttl_days. Disabled by default (None) -- a still-open "
            "order that can never fill (e.g. its security permanently loses liquidity) stays "
            "PENDING/PARTIAL_FILLED forever, unchanged from every prior run. When set, "
            "session.advance() auto-cancels an order once it has been open this many days "
            "(measured from its own original submission time), instead of retrying it forever."
        ),
    )
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
    repository = DuckDBDataRepository(data_engine, calendars={"US_EQUITY": US_EQUITY_NYSE})

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
    paper_config = PaperTradingConfig(
        initial_cash=args.initial_capital, pending_order_ttl_days=args.pending_order_ttl_days,
    )

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
    # Always populated (ADR-0096), same "on by default, opt-in only for
    # the *risk limit itself*" treatment `--reentry-cooldown-days` gets
    # below -- DuckDB's own `nextval('trade_id_seq')` sequence (see
    # storage.trade_journal_repository) persists correctly across
    # separate process invocations against the same --paper-store, so
    # this needs no ID-seeding logic the way the Python-counter-based
    # repositories above do.
    trade_journal_repository = DuckDBTradeJournalRepository(store_engine)

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
        reentry_cooldown_days=args.reentry_cooldown_days,
    )
    sizing_config = PositionSizingConfig(lot_size=args.lot_size)
    # "baseline_rule" (Session 36 continued, ADR-0110): the exact
    # DriftPredictor + BaselineRuleDecisionAgent + DeterministicPositionSizer
    # + DeterministicPortfolioRiskEngine configuration this script ran
    # inline before `orchestration.paper_strategies` existed -- moving the
    # construction there and calling it by name here changes nothing about
    # what this script actually runs.
    components = build_run_cycle_components(
        "baseline_rule", risk_config=risk_config, sizing_config=sizing_config,
        starting_ids=RunCycleStartingIds(
            prediction=next_prediction_id, observation=next_observation_id, composite=next_composite_id,
            decision=next_decision_id, sizing=next_sizing_id, risk=next_risk_id,
        ),
    )

    warmup_checkpoints = [c for c in checkpoints if (c - args.start).days < _WARMUP_DAYS]
    print(f"Running {len(checkpoints)} checkpoint(s) ({len(warmup_checkpoints)} within DriftPredictor's own warmup window) ...", flush=True)

    total_submitted = 0
    total_filled = 0
    # ADR-0154: `outcome.submission.filled_quantity` is now ALWAYS None
    # right after `run_cycle` returns -- `PaperBrokerAdapter.submit_order`
    # never fills synchronously any more, so a fill (when it lands, on a
    # LATER cycle's own `session.advance()`) can never show up on the
    # SAME `BrokerOrderResponse` this cycle's submission produced.
    # "filled so far" is therefore re-derived below from each submitted
    # order's real, current status, not from that now-permanently-None
    # field.
    submitted_client_order_ids: list[str] = []
    for i, checkpoint in enumerate(checkpoints):
        clock.index = i
        outcomes = run_cycle(
            security_ids, checkpoint, view, session, state=state,
            sector_by_security=sector_by_security if args.max_sector_weight is not None else None,
            prediction_repository=prediction_repository, regime_repository=regime_repository,
            decision_repository=decision_repository, sizing_repository=sizing_repository,
            risk_repository=risk_repository, trade_journal_repository=trade_journal_repository, **components,
        )
        for outcome in outcomes:
            if outcome.submission is not None:
                total_submitted += 1
                submitted_client_order_ids.append(outcome.submission.request_client_order_id)
        if (i + 1) % 10 == 0 or i == len(checkpoints) - 1:
            total_filled = sum(
                1 for cid in submitted_client_order_ids
                if (session.adapter.get_order_status(cid, as_of=checkpoint).filled_quantity or 0) > 0
            )
            print(f"  [{i + 1}/{len(checkpoints)}] {checkpoint.date()} -- submitted so far: {total_submitted}, filled so far: {total_filled}", flush=True)

    # External review, Session 38 continued: `mark_to_market` falling
    # back to average cost for a held security with no real price is a
    # real, honest gap -- surfacing it here (stdout + report JSON) is
    # the same "never let a real issue arrive with zero signal" treatment
    # `ingest_real_market_data.py`'s own missing_symbols print already gets.
    if state.mark_to_market_missing:
        total_missing_occurrences = sum(len(missing) for _, missing in state.mark_to_market_missing)
        print(
            f"WARNING: mark_to_market fell back to average cost {total_missing_occurrences} time(s) "
            f"across {len(state.mark_to_market_missing)} checkpoint(s) (no real price available) -- see "
            "mark_to_market_missing in the report JSON for details.",
            flush=True,
        )

    final_account = session.account_summary(as_of=checkpoints[-1])

    # Session 38: Phase 18's compute_paper_performance_report, wired
    # into this real production entrypoint for the first time (it was
    # previously only exercised by tests -- see ADR-0136). Persisted
    # through the same DuckDBPaperPerformanceReportRepository the tests
    # already use, one real report per invocation, natural-key-deduped
    # on report_id like every other repository in this pipeline.
    performance_repository = DuckDBPaperPerformanceReportRepository(store_engine)
    paper_session_id = f"paper-session-{args.universe.lower()}"
    equity_history = equity_history_from_risk_repository(risk_repository, security_ids[0], up_to=checkpoints[-1])
    trades = trade_journal_repository.list_trades(
        provenance=TradeProvenance.PAPER_TRADING, start=args.start, end=args.end,
    )
    next_performance_report_id = _next_starting_id(
        r.report_id for r in performance_repository.list_for_session(paper_session_id)
    )
    performance_report = compute_paper_performance_report(
        report_id=f"PAPERPERF-{next_performance_report_id:06d}",
        paper_session_id=paper_session_id,
        equity_history=equity_history,
        trades=trades,
        evaluated_at=checkpoints[-1],
        # `session.adapter.accounting.turnover()` is deliberately NOT
        # used here -- its own `_valuation_history` (the denominator) is
        # real only within this ONE process (`PaperTradingSession.
        # restore()` never replays past `mark_to_market` calls -- see
        # `equity_history_from_risk_repository`'s own docstring), while its
        # `_trade_notionals` numerator IS durable across every past
        # --resume run. Combining a durable numerator with a fresh-
        # this-run-only denominator would silently overstate turnover on
        # every resumed run after the first -- left `None` (honestly
        # "not_supplied") rather than reported wrong.
        strategy_version="baseline_rule",
    )
    performance_repository.record(performance_report)

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
            "reentry_cooldown_days": args.reentry_cooldown_days,
        },
        # --lot-size directly changes every proposed quantity (Session
        # 38) -- omitting it here would repeat the exact reproducibility
        # gap risk_config's own comment above already documents.
        "lot_size": args.lot_size,
        # --pending-order-ttl-days changes which orders get auto-cancelled
        # vs. retried -- same reproducibility rationale as lot_size above.
        "pending_order_ttl_days": args.pending_order_ttl_days,
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
            "reentry_cooldown_days": args.reentry_cooldown_days,
        },
        "lot_size": args.lot_size,
        "pending_order_ttl_days": args.pending_order_ttl_days,
        "mark_to_market_missing": [
            {"as_of_time": as_of.isoformat(), "security_ids": list(missing)}
            for as_of, missing in state.mark_to_market_missing
        ],
        "performance": paper_performance_report_to_payload(performance_report),
        "content_checksum": checksum,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2))

    print(f"Checkpoints run: {len(checkpoints)}")
    print(f"Orders submitted: {total_submitted} (filled: {total_filled})")
    print(f"Final cash: {final_account.cash}")
    print(f"Sharpe ratio: {performance_report.sharpe_ratio} (reason if None: {performance_report.reasons.get('sharpe_ratio')})")
    print(f"Report written to: {args.out}")
    data_engine.close()
    store_engine.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
