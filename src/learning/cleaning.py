"""DataCleaner: validates raw `ExperienceRecord`s before they can enter
a `TrainingDataset` (instruction section 7). Never silently drops a
sample -- every input record gets exactly one `CleaningResult`.

See docs/specifications/PHASE-9-learning-engine.md section 7.
"""

from __future__ import annotations

import math
from typing import Sequence

from learning.config import DataCleaningConfig
from learning.enums import SampleStatus
from learning.models import CleaningResult

from trade_journal.enums import TradeProvenance
from trade_journal.models import ExperienceRecord
from trade_journal.repository import TradeJournalRepository


def _finite(x) -> bool:
    return x is not None and isinstance(x, (int, float)) and math.isfinite(x)


class DataCleaner:
    version = "data_cleaner_v1"

    def __init__(self, config: DataCleaningConfig = DataCleaningConfig()) -> None:
        self._config = config

    def clean(
        self,
        records: Sequence[ExperienceRecord],
        journal: TradeJournalRepository,
        *,
        provenance: TradeProvenance,
    ) -> list[CleaningResult]:
        config = self._config
        results: list[CleaningResult] = []
        seen_trade_ids: set[str] = set()

        for record in records:
            if record.provenance != provenance:
                results.append(CleaningResult(
                    trade_id=record.trade_id, experience_id=record.experience_id,
                    status=SampleStatus.INVALID, reason="provenance_mismatch",
                    sample_as_of_time=None, provenance=record.provenance,
                ))
                continue

            if record.trade_id in seen_trade_ids:
                results.append(CleaningResult(
                    trade_id=record.trade_id, experience_id=record.experience_id,
                    status=SampleStatus.INVALID, reason="duplicate_trade_id",
                    sample_as_of_time=None, provenance=record.provenance,
                ))
                continue
            seen_trade_ids.add(record.trade_id)

            decision = journal.get_decision(record.decision_id)
            if decision is None or (config.require_sample_as_of_time and decision.decision_time is None):
                results.append(CleaningResult(
                    trade_id=record.trade_id, experience_id=record.experience_id,
                    status=SampleStatus.UNKNOWN, reason="missing_decision",
                    sample_as_of_time=None, provenance=record.provenance,
                ))
                continue
            sample_as_of_time = decision.decision_time

            if record.reward is not None and not _finite(record.reward):
                results.append(CleaningResult(
                    trade_id=record.trade_id, experience_id=record.experience_id,
                    status=SampleStatus.INVALID, reason="invalid_reward_numeric",
                    sample_as_of_time=sample_as_of_time, provenance=record.provenance,
                ))
                continue

            realized_return = (record.actual_outcome or {}).get("realized_return")
            if realized_return is not None and not _finite(realized_return):
                results.append(CleaningResult(
                    trade_id=record.trade_id, experience_id=record.experience_id,
                    status=SampleStatus.INVALID, reason="invalid_realized_return_numeric",
                    sample_as_of_time=sample_as_of_time, provenance=record.provenance,
                ))
                continue

            if realized_return is None:
                status = SampleStatus.EXCLUDED if config.require_realized_outcome else SampleStatus.VALID
                results.append(CleaningResult(
                    trade_id=record.trade_id, experience_id=record.experience_id,
                    status=status, reason="no_realized_outcome",
                    sample_as_of_time=sample_as_of_time, provenance=record.provenance,
                ))
                continue

            results.append(CleaningResult(
                trade_id=record.trade_id, experience_id=record.experience_id,
                status=SampleStatus.VALID, reason="ok",
                sample_as_of_time=sample_as_of_time, provenance=record.provenance,
            ))

        return results
