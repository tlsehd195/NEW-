"""DuckDBAttributionRepository: persistent implementation of Phase 10's
AttributionRepository Protocol.

See docs/specifications/PHASE-10-counterfactual-attribution.md section
4.5 and ADR-0016. One new DuckDB table (`attribution_results`) in
Phase 4's existing catalog file, shaped exactly like Phase 3's existing
`post_trade_analyses`/`counterfactuals` tables (seq-ordered append
history, latest-wins retrieval) -- AttributionResult gets the same
persistence discipline those two Phase 3 types already use, not a new
one invented for this phase.

CounterfactualRecord persistence is NOT duplicated here: Phase 3's
DuckDBTradeJournalRepository.record_counterfactual/get_counterfactual
already accept and round-trip an arbitrary-length AlternativeOutcome
tuple, so Phase 10 calls that, unchanged.
"""

from __future__ import annotations

from typing import Optional

from storage.engine import StorageEngine
from storage.serialization import (
    attribution_result_to_payload,
    json_dumps,
    json_loads,
    payload_to_attribution_result,
    to_utc_naive,
)

from trade_journal.models import AttributionResult


class DuckDBAttributionRepository:
    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine

    def record(self, result: AttributionResult) -> AttributionResult:
        payload = attribution_result_to_payload(result)
        self._engine.connection.execute(
            "INSERT INTO attribution_results (experiment_id, computed_at, payload_json) VALUES (?, ?, ?)",
            [result.experiment_id, to_utc_naive(result.computed_at), json_dumps(payload)],
        )
        return result

    def get(self, experiment_id: str) -> Optional[AttributionResult]:
        row = self._engine.connection.execute(
            "SELECT payload_json FROM attribution_results WHERE experiment_id = ? ORDER BY seq DESC LIMIT 1",
            [experiment_id],
        ).fetchone()
        if row is None:
            return None
        return payload_to_attribution_result(json_loads(row[0]))

    def get_history(self, experiment_id: str) -> tuple[AttributionResult, ...]:
        cur = self._engine.connection.execute(
            "SELECT payload_json FROM attribution_results WHERE experiment_id = ? ORDER BY seq",
            [experiment_id],
        )
        return tuple(payload_to_attribution_result(json_loads(r[0])) for r in cur.fetchall())

    def list_all(self) -> list[AttributionResult]:
        cur = self._engine.connection.execute("SELECT payload_json FROM attribution_results ORDER BY seq")
        return [payload_to_attribution_result(json_loads(r[0])) for r in cur.fetchall()]
