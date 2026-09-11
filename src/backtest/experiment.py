"""ExperimentRecord / ExperimentTracker.

See docs/specifications/PHASE-2-backtesting.md section 13. In-process
registry only — a persistent store is future work (mirrors Phase 1's
DataQualityFramework run-counter scoping decision).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from backtest.enums import ExperimentResult
from backtest.metrics import PerformanceReport


@dataclass(frozen=True)
class ExperimentRecord:
    experiment_id: str
    strategy_version: str
    data_version: tuple[str, ...]
    feature_version: Optional[str]
    configuration_version: str
    start_date: datetime
    end_date: datetime
    initial_capital: float
    transaction_cost_config: dict
    slippage_config: dict
    benchmark: dict
    metrics: PerformanceReport
    code_version: str
    seed: Optional[int]
    result: ExperimentResult
    timestamp: datetime


class ExperimentTracker:
    """Allocates monotonic "BT-000001" style ids, mirroring Phase 1's
    "DQ-000001" pattern (data_infra.quality.DataQualityFramework). This
    class itself is in-process/ephemeral by design (see module
    docstring) -- but a caller that persists its output across
    multiple separate `ExperimentTracker` instances into a shared
    store (e.g. `storage.experiment_repository.DuckDBExperimentRepository`,
    which dedups on `experiment_id`) needs every instance's ids to stay
    distinct, or a later, genuinely different experiment silently
    collides with -- and is dropped by -- an earlier one that happened
    to get the same auto-incremented id (ADR-0115). `starting_id` lets
    such a caller seed each fresh tracker past whatever the shared
    store already holds, the same restart-safety pattern this project
    already uses for `ai_gateway.QuotaManager`/`broker.paper`
    observation ids/etc. -- optional and additive, no existing caller's
    behavior changes by not passing it."""

    def __init__(self, *, starting_id: int = 1) -> None:
        self._next_id = starting_id
        self.records: list[ExperimentRecord] = []

    def _allocate_id(self) -> str:
        experiment_id = f"BT-{self._next_id:06d}"
        self._next_id += 1
        return experiment_id

    def record(
        self,
        *,
        strategy_version: str,
        data_version: tuple[str, ...],
        feature_version: Optional[str],
        configuration_version: str,
        start_date: datetime,
        end_date: datetime,
        initial_capital: float,
        transaction_cost_config: dict,
        slippage_config: dict,
        benchmark: dict,
        metrics: PerformanceReport,
        code_version: str,
        seed: Optional[int],
        result: ExperimentResult,
        timestamp: datetime,
    ) -> ExperimentRecord:
        record = ExperimentRecord(
            experiment_id=self._allocate_id(),
            strategy_version=strategy_version,
            data_version=data_version,
            feature_version=feature_version,
            configuration_version=configuration_version,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            transaction_cost_config=transaction_cost_config,
            slippage_config=slippage_config,
            benchmark=benchmark,
            metrics=metrics,
            code_version=code_version,
            seed=seed,
            result=result,
            timestamp=timestamp,
        )
        self.records.append(record)
        return record
