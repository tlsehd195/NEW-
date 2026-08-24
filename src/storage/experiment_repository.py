"""ExperimentRepository: persistent Experiment Registry.

See docs/specifications/PHASE-4-baseline-models-and-storage.md sections
4, 11-12. Phase 2's `backtest.experiment.ExperimentTracker` stays exactly
as it is -- an in-process registry that allocates the `BT-000001`-style
id and hands back the `ExperimentRecord` a `BacktestResult` embeds
(engine.py is not modified, per this phase's "Repository abstraction
유지" requirement). This module adds a separate, explicit persistence
step: the caller (Phase 4's baseline runner) passes the already-built
`ExperimentRecord` here to durably record it. This mirrors exactly how
`trade_journal.backtest_adapter.ingest_backtest_result` treats Phase 2 as
a read-only source and Phase 3 as the write side -- Phase 4 does the same
for the experiment registry.
"""

from __future__ import annotations

from typing import Optional, Protocol

from storage.engine import StorageEngine
from storage.serialization import (
    dict_to_experiment_record,
    experiment_record_to_dict,
    json_dumps,
    json_loads,
    to_utc_naive,
)

from backtest.experiment import ExperimentRecord


class ExperimentRepository(Protocol):
    def record(self, experiment: ExperimentRecord) -> None:
        """Idempotent: recording the same experiment_id twice is a no-op
        the second time (natural-key = experiment_id itself, already
        globally unique per Phase 2's ExperimentTracker)."""
        ...

    def get(self, experiment_id: str) -> Optional[ExperimentRecord]: ...

    def list_all(self) -> list[ExperimentRecord]: ...


class DuckDBExperimentRepository:
    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine

    def record(self, experiment: ExperimentRecord) -> None:
        conn = self._engine.connection
        existing = conn.execute(
            "SELECT 1 FROM experiments WHERE experiment_id = ?", [experiment.experiment_id]
        ).fetchone()
        if existing is not None:
            return

        payload = experiment_record_to_dict(experiment)
        metrics = experiment.metrics
        conn.execute(
            "INSERT INTO experiments (experiment_id, strategy_version, configuration_version, "
            "start_date, end_date, initial_capital, code_version, seed, result, timestamp, "
            "cumulative_return, cagr, sharpe_ratio, sortino_ratio, max_drawdown, excess_return, "
            "turnover, total_transaction_cost, payload_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                experiment.experiment_id, experiment.strategy_version, experiment.configuration_version,
                to_utc_naive(experiment.start_date), to_utc_naive(experiment.end_date),
                experiment.initial_capital, experiment.code_version, experiment.seed,
                experiment.result.value, to_utc_naive(experiment.timestamp),
                metrics.cumulative_return, metrics.cagr, metrics.sharpe_ratio, metrics.sortino_ratio,
                metrics.max_drawdown, metrics.excess_return, metrics.turnover,
                metrics.total_transaction_cost, json_dumps(payload),
            ],
        )

    def get(self, experiment_id: str) -> Optional[ExperimentRecord]:
        row = self._engine.connection.execute(
            "SELECT payload_json FROM experiments WHERE experiment_id = ?", [experiment_id]
        ).fetchone()
        if row is None:
            return None
        return dict_to_experiment_record(json_loads(row[0]))

    def list_all(self) -> list[ExperimentRecord]:
        cur = self._engine.connection.execute("SELECT payload_json FROM experiments ORDER BY timestamp")
        return [dict_to_experiment_record(json_loads(r[0])) for r in cur.fetchall()]
