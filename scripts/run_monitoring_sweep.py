#!/usr/bin/env python3
"""Real monitoring sweep over an already-populated `--paper-store`
(independent audit finding, Step 10, P2).

**The gap this closes**: `monitoring.collectors`/`monitoring.pipeline`
were fully built and tested (Phase 14), and both the `monitoring_events`/
`component_health_states`/`drift_results`/`alerts` DuckDB tables
(`storage.schema`) and their real repository implementations
(`storage.monitoring_repository`, also Phase 14) already existed -- but
a repo-wide grep before this script was written found zero production
callers of any collector or of any of those four repositories outside
their own test file. The independent audit's own framing: "모니터링/
경보 코드 자체는 결정론적, fail-closed, PIT-클린, 잘 테스트됨 -- 실험실
계기가 공장에 설치된 적이 없는 것." This script is that installation: it
reads real, already-persisted Phase 8/Phase 1-13 records from the SAME
`--paper-store` `scripts/run_paper_trading_cycle.py` already populates
daily, runs them through the real collectors/pipeline, and persists the
result via `storage.monitoring_repository`'s existing DuckDB
repositories (which also picked up a real ordering fix alongside this
script -- see that module's own docstring).

**Scope, deliberately bounded and disclosed, not silently narrowed**:
covers `prediction`/`decision`/`regime`/`sizing`/`risk`/`account` --
the six components with real, already-populated repositories in
`--paper-store` today (`regime` added by a later, independent audit
fix, 2026-09-25 -- `collect_regime` previously did not exist at all).
Does NOT cover:
- `data_quality`: needs real `PriceBar` history from the SEPARATE
  market-data catalog (`--db-path`, not `--paper-store`) -- a real,
  addressable gap, left for a follow-up that also accepts a
  `--db-path` argument.
- `broker`: needs `BrokerRequestRecord`/`BrokerResponseRecord` -- these
  are the generic `broker.pipeline.submit_validated_order` audit trail
  (Phase 13), which `PaperTradingSession.submit()` does not go
  through (it calls `PaperBrokerAdapter.submit_order` directly) -- no
  real data exists in `--paper-store` for this component today.
- `ai_gateway`/`learning`/`model_evolution`: `ai_gateway` has zero real
  production calls (independently confirmed elsewhere this session).
  **Correction (independent audit finding, 2026-09-25): `model_evolution`
  does NOT actually run on any cron.** `learning_cycle.yml`'s weekly
  cron (`0 6 * * 6`, real and confirmed) only ever invokes
  `scripts/run_learning_cycle.py` -- there is no `model_evolution` CLI
  script anywhere in this repository, and no workflow references
  `evolution.pipeline`/`generate_candidate_batch` at all (confirmed via
  a repo-wide search). Only `learning` is actually scheduled;
  `model_evolution` has zero production callers, period -- integrating
  either into this sweep is a distinct follow-up, not folded in here to
  keep this script's own scope honest and reviewable.
- Drift detection (`monitoring.drift`): needs a real baseline-vs-current
  comparison window this script does not yet construct -- `drift_
  results`/drift-derived alerts are always empty this pass, not
  fabricated as "no drift detected."

Makes NO network call -- reads only the already-persisted local
`--paper-store`. Safe to run repeatedly against the same store and
window: every persisted row is idempotent on its own natural id
(`storage.monitoring_repository`'s own `record()` methods), and this
script seeds its own id counters from whatever the store already has,
matching `scripts/run_paper_trading_cycle.py`'s own established
`_next_starting_id` convention exactly.

Usage:
    python3 scripts/run_monitoring_sweep.py \\
        --paper-store ./data/paper_trading_store \\
        --representative-security-id AAPL \\
        --start 2024-01-02 --end 2024-06-28 \\
        --out ./data/monitoring_sweep_report.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from monitoring.collectors import (  # noqa: E402
    collect_account,
    collect_decision,
    collect_regime,
    collect_risk,
    collect_sizing,
)
from monitoring.collectors import collect_prediction  # noqa: E402
from monitoring.config import MonitoringConfig  # noqa: E402
from monitoring.enums import ComponentHealthStatus  # noqa: E402
from monitoring.pipeline import assemble_pipeline_observation  # noqa: E402

from orchestration.paper_runner import equity_history_from_risk_repository  # noqa: E402

from storage.config import StorageConfig  # noqa: E402
from storage.decision_repository import DuckDBDecisionRepository  # noqa: E402
from storage.engine import StorageEngine  # noqa: E402
from storage.monitoring_repository import (  # noqa: E402
    DuckDBAlertRepository,
    DuckDBComponentHealthRepository,
    DuckDBMonitoringEventRepository,
)
from storage.prediction_repository import DuckDBPredictionRepository  # noqa: E402
from storage.regime_repository import DuckDBRegimeRepository  # noqa: E402
from storage.risk_repository import DuckDBPositionSizingRepository, DuckDBRiskRepository  # noqa: E402


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _next_starting_id(record_ids) -> int:
    """Identical convention to `scripts/run_paper_trading_cycle.py`'s
    own helper of the same name: 1 for an empty/fresh store, otherwise
    one past the highest numeric suffix already used -- every id format
    here is `<PREFIX...>-NNNNNN`."""
    highest = 0
    for record_id in record_ids:
        suffix = record_id.rsplit("-", 1)[-1]
        if suffix.isdigit():
            highest = max(highest, int(suffix))
    return highest + 1


class _Counter:
    def __init__(self, prefix: str, start: int) -> None:
        self._prefix = prefix
        self._next = start

    def __call__(self) -> str:
        allocated = f"{self._prefix}-{self._next:06d}"
        self._next += 1
        return allocated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--paper-store", required=True, type=Path, help="The same --paper-store scripts/run_paper_trading_cycle.py already populates")
    parser.add_argument("--representative-security-id", required=True, help="Any security this store has real risk_assessments for -- used to reconstruct real portfolio-value history (equity_history_from_risk_repository)")
    parser.add_argument("--start", required=True, type=_parse_date, help="Start date, YYYY-MM-DD -- the window this sweep observes")
    parser.add_argument("--end", required=True, type=_parse_date, help="End date, YYYY-MM-DD -- also this sweep's as_of_time/observed_at reference; never derived from wall-clock time")
    parser.add_argument("--out", type=Path, default=None, help="Where to write the JSON report (default: <paper-store>/monitoring_sweep_report.json)")
    # Independent audit finding (2026-09-24): this script never had any
    # way to pass a real max_drawdown to collect_account -- it always
    # defaulted to None, which monitoring.health.evaluate_account_health
    # now (correctly) reports as UNKNOWN rather than a vacuous HEALTHY
    # (see that function's own docstring for why). Mirrors
    # run_paper_trading_cycle.py's own --max-drawdown flag/default
    # exactly (None = not enforced, same convention).
    parser.add_argument("--max-drawdown", type=float, default=None, help="Real drawdown threshold for ACCOUNT health alerting (default: None -- not configured, reported as UNKNOWN rather than a vacuous HEALTHY)")
    args = parser.parse_args(argv)

    report_path = args.out or (args.paper_store / "monitoring_sweep_report.json")

    store_engine = StorageEngine(StorageConfig(root_dir=args.paper_store))
    try:
        prediction_repository = DuckDBPredictionRepository(store_engine)
        decision_repository = DuckDBDecisionRepository(store_engine)
        sizing_repository = DuckDBPositionSizingRepository(store_engine)
        risk_repository = DuckDBRiskRepository(store_engine)
        regime_repository = DuckDBRegimeRepository(store_engine)

        event_repository = DuckDBMonitoringEventRepository(store_engine)
        health_repository = DuckDBComponentHealthRepository(store_engine)
        alert_repository = DuckDBAlertRepository(store_engine)

        predictions = prediction_repository.list_all(start=args.start, end=args.end)
        decisions = decision_repository.list_all(start=args.start, end=args.end)
        sizing_results = sizing_repository.list_all(start=args.start, end=args.end)
        risk_results = risk_repository.list_all(start=args.start, end=args.end)
        # Independent audit finding (2026-09-24, "REGIME collector 부재"):
        # collect_regime previously did not exist -- REGIME was a
        # declared MonitoringComponent with no collector wired to it at
        # all. list_composites() has no start/end filter of its own
        # (unlike the repositories above); collect_regime applies the
        # same _filter_by_time windowing to args.end internally, the
        # identical safety-net every other collector already has.
        regime_composites = regime_repository.list_composites()
        # Deliberately NOT windowed to [--start, --end] -- this reconstructs
        # the portfolio's real cumulative value history up to --end, the
        # same real input scripts/run_paper_trading_cycle.py's own
        # --resume path already uses for the identical purpose
        # (ADR-0136), so `compute_account_metrics`'s drawdown/return
        # figures reflect real history, not an artificially truncated one.
        equity_history = equity_history_from_risk_repository(
            risk_repository, args.representative_security_id, up_to=args.end,
        )

        config = MonitoringConfig()

        next_event_id = _next_starting_id(e.event_id for e in event_repository.list_all())
        next_health_id = _next_starting_id(h.health_id for h in health_repository.list_all())
        next_alert_id = _next_starting_id(a.alert_id for a in alert_repository.list_all())
        event_ids = _Counter("MONEVT", next_event_id)
        health_ids = _Counter("HEALTH", next_health_id)
        alert_ids = _Counter("ALERT", next_alert_id)

        collected = []
        for records, collector in (
            (predictions, collect_prediction),
            (decisions, collect_decision),
            (regime_composites, collect_regime),
            (sizing_results, collect_sizing),
            (risk_results, collect_risk),
        ):
            event, health = collector(
                records, as_of_time=args.end, observed_at=args.end, config=config,
                event_id=event_ids(), health_id=health_ids(),
            )
            collected.append((event, health))
        account_event, account_health = collect_account(
            equity_history, as_of_time=args.end, observed_at=args.end, config=config,
            event_id=event_ids(), health_id=health_ids(), max_drawdown=args.max_drawdown,
        )
        collected.append((account_event, account_health))

        observation = assemble_pipeline_observation(
            collected, as_of_time=args.end, observed_at=args.end, config=config,
            pipeline_health_id=health_ids(), alert_id_factory=alert_ids,
        )

        for event in observation.events:
            event_repository.record(event)
        for health in observation.component_healths + (observation.pipeline_health,):
            health_repository.record(health)
        for alert in observation.alerts:
            alert_repository.record(alert)
        # drift_results is always empty this pass (see module docstring)
        # -- nothing to persist to DuckDBDriftResultRepository yet.

        report = {
            "note": (
                "Real monitoring sweep over an already-populated --paper-store. "
                "Covers prediction/decision/regime/sizing/risk/account only -- see "
                "this script's own module docstring for the disclosed, not-yet-covered "
                "components (data_quality, broker, ai_gateway, learning, "
                "model_evolution, drift detection)."
            ),
            "paper_store": str(args.paper_store),
            "representative_security_id": args.representative_security_id,
            "window_start": args.start.isoformat(),
            "window_end": args.end.isoformat(),
            "record_counts": {
                "predictions": len(predictions), "decisions": len(decisions),
                "sizing_results": len(sizing_results), "risk_results": len(risk_results),
                "equity_history_points": len(equity_history),
            },
            "component_healths": [
                {"component": h.component.value, "status": h.status.value, "reason": h.reason}
                for h in observation.component_healths
            ],
            "pipeline_health": {
                "status": observation.pipeline_health.status.value,
                "reason": observation.pipeline_health.reason,
            },
            "events_persisted": len(observation.events),
            "alerts_raised": [
                {"severity": a.severity.value, "component": a.component.value, "message": a.message}
                for a in observation.alerts
            ],
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2))

        print(f"Monitoring sweep window: [{args.start.date()}, {args.end.date()}]")
        print(f"Record counts: {report['record_counts']}")
        for h in observation.component_healths:
            print(f"Component health: {h.component.value} = {h.status.value} ({h.reason})")
        print(f"Pipeline health: {observation.pipeline_health.status.value} ({observation.pipeline_health.reason})")
        print(f"Events persisted: {len(observation.events)}")
        print(f"Alerts raised: {len(observation.alerts)}")
        for a in observation.alerts:
            print(f"  [{a.severity.value}] {a.component.value}: {a.message}")
        print(f"Report written to: {report_path}")

        if observation.pipeline_health.status == ComponentHealthStatus.UNAVAILABLE:
            print("FATAL: pipeline health is UNAVAILABLE -- see alerts above.", file=sys.stderr)
            return 1
        return 0
    finally:
        store_engine.close()


if __name__ == "__main__":
    sys.exit(main())
