#!/usr/bin/env python3
"""Research-only experiment: how well does an LLM (Google Gemini) predict
a security's short-term price direction? Two subcommands:

    predict  -- for each security in a universe, build a prompt from real,
                point-in-time price history (read-only, via `storage.
                data_repository.DuckDBDataRepository` -- the same
                `DataRepository` Protocol backtest/strategy_research use,
                so this never sees data that would not have been
                available `--as-of` that date), call Google's Gemini API
                through `ai_gateway.gateway.AIGateway` +
                `ai_gateway.providers.gemini.GeminiProviderAdapter`
                (ADR-0206), and record the request/response into the
                existing `ai_requests`/`ai_responses` DuckDB tables
                (Phase 12's own persistence, untouched) plus a small,
                human-readable JSON sidecar file under
                `docs/research/reports/ai_prediction_experiment/`.

    score    -- reads a `predict` sidecar file, looks up the now-realized
                price move for each prediction whose target trading day
                has passed, and reports directional accuracy. Never
                mutates anything `predict` wrote.

**Explicitly separate from the real trading pipeline** (account owner's
own request, 2026-09-25): this script never imports `predict`/`decision`/
`risk`/`broker` (`tests/ai_gateway/test_ai_gateway_gemini_boundary.py`
verifies the reverse -- those packages never import this experiment's
own `ai_gateway.providers.*`), never produces a `trade_journal.enums.
DecisionAction`, and never calls a broker. It exists solely to log how
often the model's stated direction turns out to be right -- nothing here
feeds back into predict/decision/risk/broker, the Learning Engine's
Experience Dataset, or any live/paper trading path.

`AIRequest.provenance`/`AIResponse.provenance` are tagged
`TradeProvenance.HISTORICAL_SIMULATION` -- the closest of that enum's
three existing values (never a fourth value added just for this side
experiment; see ADR-0206) to what this actually is: an offline analysis
against already-ingested historical data, not a live/paper trading
event. This has no real contamination risk: `ai_requests`/`ai_responses`
are their own tables, never read by `learning.cleaning`/`experience`'s
Experience Dataset pipeline (grep-verified, ADR-0206).

Usage:
    export GEMINI_API_KEY=...
    python3 scripts/run_ai_prediction_experiment.py predict \\
        --db-path ./data/real_2010_latest \\
        --universe AAPL,MSFT,GOOGL \\
        --as-of 2026-09-20 --horizon-days 5

    python3 scripts/run_ai_prediction_experiment.py score \\
        --db-path ./data/real_2010_latest \\
        --predictions docs/research/reports/ai_prediction_experiment/2026-09-20_ai_prediction_experiment_v1.json \\
        --as-of 2026-09-30
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ai_gateway.config import GatewayConfig, ProviderConfig  # noqa: E402
from ai_gateway.enums import BillingStatus, TaskTier  # noqa: E402
from ai_gateway.gateway import AIGateway  # noqa: E402
from ai_gateway.models import AIRequest  # noqa: E402
from ai_gateway.providers.gemini import DEFAULT_GEMINI_PROVIDER_CONFIG, GeminiProviderAdapter  # noqa: E402
from ai_gateway.quota_manager import QuotaManager  # noqa: E402
from ai_gateway.repository import InMemoryQuotaStateRepository  # noqa: E402
from data_infra.models import PriceBar  # noqa: E402
from storage.ai_gateway_repository import DuckDBAIRequestRepository, DuckDBAIResponseRepository  # noqa: E402
from storage.config import StorageConfig  # noqa: E402
from storage.data_repository import DuckDBDataRepository  # noqa: E402
from storage.engine import StorageEngine  # noqa: E402
from trade_journal.enums import TradeProvenance  # noqa: E402

_PROMPT_TEMPLATE_ID = "ai_prediction_direction_v1"
_PROMPT_TEMPLATE_VERSION = "v1"
_RESPONSE_SCHEMA = ("direction", "confidence", "reasoning")
_DEFAULT_REPORT_DIR = Path(__file__).resolve().parent.parent / "docs" / "research" / "reports" / "ai_prediction_experiment"


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _end_of_day(day: datetime) -> datetime:
    """`day` is midnight UTC (`_parse_date`'s own output) -- pushed to
    23:59 the same calendar date so `get_bars`'s `as_of_time` argument is
    honestly "as of the end of this date", past every real
    `bar_available_time` offset for that date's own bar (`data_infra.
    provider.bar_available_time`), without having to import that
    constant just to reproduce its exact value here."""
    return day + timedelta(hours=23, minutes=59)


def _next_starting_id(record_ids) -> int:
    """Identical convention to `scripts/run_monitoring_sweep.py`'s own
    helper of the same name: 1 for an empty/fresh store, otherwise one
    past the highest numeric suffix already used."""
    highest = 0
    for record_id in record_ids:
        suffix = record_id.rsplit("-", 1)[-1]
        if suffix.isdigit():
            highest = max(highest, int(suffix))
    return highest + 1


def _build_prompt(security_id: str, bars: list[PriceBar], horizon_days: int) -> str:
    history = "\n".join(f"{b.timestamp.date().isoformat()},{b.close:.4f},{b.volume:.0f}" for b in bars)
    return (
        f"You are analyzing daily closing prices for {security_id} (US equity).\n"
        f"Recent daily close,volume history (oldest first, one row per trading day):\n"
        f"date,close,volume\n{history}\n\n"
        f"Predict the direction of {security_id}'s closing price exactly {horizon_days} trading "
        f"day(s) after the last date above, compared to that last close.\n"
        'Respond ONLY as compact JSON with exactly these keys: '
        '"direction" (one of "UP", "DOWN", "FLAT"), '
        '"confidence" (a number from 0.0 to 1.0), '
        '"reasoning" (a short one-sentence explanation).'
    )


def _build_gateway(engine: StorageEngine, gemini_config: ProviderConfig, *, as_of: datetime) -> AIGateway:
    gateway_config = GatewayConfig(providers=(gemini_config,))
    # Quota state itself is not part of what this experiment records
    # (`ai_requests`/`ai_responses` -- the actual, DuckDB-persisted
    # "result" -- are); an in-memory QuotaManager is enough to give
    # `AIGateway` a working QuotaManager/ProviderSelector for this one
    # process run.
    quota_manager = QuotaManager(InMemoryQuotaStateRepository())
    quota_manager.initialize(gemini_config, at=as_of, billing_status=BillingStatus.CONFIRMED_FREE)
    adapter = GeminiProviderAdapter(gemini_config)
    return AIGateway(
        gateway_config,
        {gemini_config.provider_id: adapter},
        quota_manager,
        request_repository=DuckDBAIRequestRepository(engine),
        response_repository=DuckDBAIResponseRepository(engine),
    )


def cmd_predict(args: argparse.Namespace) -> int:
    as_of_day = _parse_date(args.as_of)
    as_of_dt = _end_of_day(as_of_day)
    securities = [s.strip() for s in args.universe.split(",") if s.strip()]
    if not securities:
        print("no securities given via --universe", file=sys.stderr)
        return 1

    gemini_config = DEFAULT_GEMINI_PROVIDER_CONFIG
    if args.model:
        gemini_config = ProviderConfig(
            provider_id=gemini_config.provider_id, provider_name=gemini_config.provider_name,
            model=args.model, api_key_reference=gemini_config.api_key_reference,
            rpm_limit=gemini_config.rpm_limit, rpd_limit=gemini_config.rpd_limit,
            tpm_limit=gemini_config.tpm_limit, tpd_limit=gemini_config.tpd_limit,
        )

    with StorageEngine(StorageConfig(Path(args.db_path))) as engine:
        data_repo = DuckDBDataRepository(engine)
        gateway = _build_gateway(engine, gemini_config, as_of=as_of_dt)
        next_id = _next_starting_id(r.request_id for r in DuckDBAIRequestRepository(engine).list_all())

        records = []
        for i, security_id in enumerate(securities):
            lookback_start = as_of_day - timedelta(days=args.lookback_days * 3 + 14)  # generous calendar buffer
            bars = data_repo.get_bars(security_id, lookback_start, as_of_dt, as_of_dt)
            bars = bars[-args.lookback_days:]
            if len(bars) < max(5, args.lookback_days // 2):
                print(f"{security_id}: SKIPPED (only {len(bars)} bars of history as of {args.as_of})")
                records.append({
                    "security_id": security_id, "status": "SKIPPED_INSUFFICIENT_HISTORY",
                    "bars_available": len(bars),
                })
                continue

            request = AIRequest(
                request_id=f"AIREQ-{next_id:06d}", task_tier=TaskTier.MEDIUM,
                prompt_template_id=_PROMPT_TEMPLATE_ID, prompt_template_version=_PROMPT_TEMPLATE_VERSION,
                payload=_build_prompt(security_id, bars, args.horizon_days), max_tokens=300,
                requested_at=as_of_dt, provenance=TradeProvenance.HISTORICAL_SIMULATION,
                experiment_id=args.experiment_id, response_schema=_RESPONSE_SCHEMA,
            )
            next_id += 1
            response = gateway.generate(request, as_of=as_of_dt)
            last_bar = bars[-1]
            parsed = response.parsed or {}
            record = {
                "security_id": security_id, "request_id": request.request_id,
                "response_id": response.response_id, "status": response.status.value,
                "error_reason": response.error_reason,
                "last_known_date": last_bar.timestamp.date().isoformat(), "last_known_close": last_bar.close,
                "horizon_trading_days": args.horizon_days,
                "predicted_direction": parsed.get("direction"),
                "predicted_confidence": parsed.get("confidence"),
                "predicted_reasoning": parsed.get("reasoning"),
                "model": gemini_config.model, "provider_id": gemini_config.provider_id,
            }
            records.append(record)
            print(f"{security_id}: status={response.status.value} direction={record['predicted_direction']!r}")

            if i < len(securities) - 1:
                time.sleep(args.pause_seconds)

    out_path = Path(args.output) if args.output else _DEFAULT_REPORT_DIR / f"{args.as_of}_{args.experiment_id}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(
        {
            "experiment_id": args.experiment_id, "as_of": args.as_of, "horizon_trading_days": args.horizon_days,
            "model": gemini_config.model, "predictions": records,
        },
        indent=2, sort_keys=True,
    ) + "\n")
    print(f"wrote {len(records)} prediction record(s) to {out_path}")
    return 0


def _actual_direction(last_close: float, target_close: float) -> str:
    if target_close > last_close:
        return "UP"
    if target_close < last_close:
        return "DOWN"
    return "FLAT"


def cmd_score(args: argparse.Namespace) -> int:
    as_of_dt = _end_of_day(_parse_date(args.as_of))
    payload = json.loads(Path(args.predictions).read_text())

    scored: list[dict] = []
    with StorageEngine(StorageConfig(Path(args.db_path)), read_only=True) as engine:
        data_repo = DuckDBDataRepository(engine)
        for record in payload["predictions"]:
            if record["status"] != "SUCCESS" or not record.get("predicted_direction"):
                scored.append({**record, "outcome": "NOT_SCORABLE"})
                continue

            last_date = datetime.strptime(record["last_known_date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            horizon = record["horizon_trading_days"]
            window_end = min(last_date + timedelta(days=horizon * 3 + 14), as_of_dt)
            future_bars = data_repo.get_bars(record["security_id"], last_date + timedelta(days=1), window_end, as_of_dt)
            if len(future_bars) < horizon:
                scored.append({**record, "outcome": "PENDING_INSUFFICIENT_FUTURE_DATA"})
                continue

            target_bar = future_bars[horizon - 1]
            actual = _actual_direction(record["last_known_close"], target_bar.close)
            scored.append({
                **record,
                "outcome": "SCORED",
                "target_date": target_bar.timestamp.date().isoformat(),
                "target_close": target_bar.close,
                "actual_direction": actual,
                "correct": actual == record["predicted_direction"],
            })

    scorable = [r for r in scored if r["outcome"] == "SCORED"]
    n_correct = sum(1 for r in scorable if r["correct"])
    summary = {
        "scored_count": len(scorable),
        "correct_count": n_correct,
        "accuracy": (n_correct / len(scorable)) if scorable else None,
        "pending_count": sum(1 for r in scored if r["outcome"] == "PENDING_INSUFFICIENT_FUTURE_DATA"),
        "not_scorable_count": sum(1 for r in scored if r["outcome"] == "NOT_SCORABLE"),
    }

    out_path = Path(args.output) if args.output else Path(args.predictions).with_name(
        Path(args.predictions).stem + "_scored.json"
    )
    out_path.write_text(json.dumps(
        {
            "experiment_id": payload.get("experiment_id"), "scored_as_of": args.as_of,
            "summary": summary, "predictions": scored,
        },
        indent=2, sort_keys=True,
    ) + "\n")
    print(json.dumps(summary, indent=2))
    print(f"wrote {out_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    predict = sub.add_parser("predict", help="ask Gemini to predict price direction and record the result")
    predict.add_argument("--db-path", required=True, help="StorageConfig root_dir holding catalog.duckdb")
    predict.add_argument("--universe", required=True, help="comma-separated security ids, e.g. AAPL,MSFT")
    predict.add_argument("--as-of", required=True, help="YYYY-MM-DD -- only price history up to this date is used")
    predict.add_argument("--horizon-days", type=int, default=5, help="trading days ahead to predict (default: 5)")
    predict.add_argument("--lookback-days", type=int, default=30, help="trading days of history in the prompt (default: 30)")
    predict.add_argument("--experiment-id", default="ai_prediction_experiment_v1")
    predict.add_argument("--model", default=None, help="override the default Gemini model")
    predict.add_argument(
        "--pause-seconds", type=float, default=13.0,
        help="sleep between calls -- Gemini's free tier is 5 requests/minute (confirmed 2026-09-25, see "
             "ai_gateway.providers.gemini_transport's own docstring); default leaves headroom",
    )
    predict.add_argument("--output", default=None, help="output JSON path (default: docs/research/reports/ai_prediction_experiment/)")
    predict.set_defaults(func=cmd_predict)

    score = sub.add_parser("score", help="score a predict run's JSON file against now-realized prices")
    score.add_argument("--db-path", required=True)
    score.add_argument("--predictions", required=True, help="JSON file written by the predict subcommand")
    score.add_argument("--as-of", required=True, help="YYYY-MM-DD -- only price history up to this date is used")
    score.add_argument("--output", default=None)
    score.set_defaults(func=cmd_score)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
