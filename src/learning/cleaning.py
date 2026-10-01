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
            # Session 37 (ADR-0115, external review, previously-remaining
            # MEDIUM): the `decision.decision_time is None` check is now
            # unconditional -- `config.require_sample_as_of_time` used to
            # gate it, but `DecisionSnapshot.decision_time` is a required,
            # non-Optional field everywhere a real DecisionSnapshot is
            # constructed, so that condition could never actually fire in
            # practice regardless of the flag. Guarding it only when the
            # (effectively always-True-in-practice) flag was set left a
            # dead, unreachable-in-normal-use path that -- were it ever
            # reached (e.g. a malformed/legacy row bypassing dataclass
            # construction) -- would let `sample_as_of_time=None` through
            # into `learning.dataset.build_training_dataset`'s own
            # `sort(key=lambda r: r.sample_as_of_time)`, crashing on a
            # None-vs-datetime comparison. Always excluding it here is
            # strictly safer and changes nothing for any real,
            # dataclass-constructed DecisionSnapshot.
            if decision is None or decision.decision_time is None:
                results.append(CleaningResult(
                    trade_id=record.trade_id, experience_id=record.experience_id,
                    status=SampleStatus.UNKNOWN, reason="missing_decision",
                    sample_as_of_time=None, provenance=record.provenance,
                ))
                continue
            sample_as_of_time = decision.decision_time

            # A fill priced on a bar that was already available when the
            # decision was made used the decision's own information as its
            # execution price (the same-bar fill ADR-0154 forbids and
            # ADR-0226 found in daily paper runs). Its outcome is not a real
            # T+1 outcome, so it must not train a model. Fills recorded
            # before `reference_bar_available_time` existed cannot be
            # checked and pass through.
            trade = journal.get_trade(record.trade_id)
            bar_time = trade.fill.reference_bar_available_time if trade is not None else None
            if bar_time is not None and bar_time <= decision.decision_time:
                results.append(CleaningResult(
                    trade_id=record.trade_id, experience_id=record.experience_id,
                    status=SampleStatus.INVALID, reason="fill_priced_on_decision_bar",
                    sample_as_of_time=sample_as_of_time, provenance=record.provenance,
                ))
                continue

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
