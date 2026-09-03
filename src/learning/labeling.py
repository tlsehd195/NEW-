"""Labeler: turns a VALID `CleaningResult` into a `LabeledSample`
(instruction section 8). Label generation is a separate responsibility
from Data Cleaning -- this module never re-validates what Cleaning
already decided, and never touches an INVALID/EXCLUDED/UNKNOWN result.

Label source: `TradeRecord.realized_return` -- the trade's own,
already-realized outcome (never a newly-computed multi-day forward
return derived from price data). Using future information (the
outcome, realized after `sample_as_of_time`) to build a label is
explicitly permitted (instruction section 5); what is never permitted
is that same future information leaking back into `feature_cutoff_time`
or the sample's `state` -- this module only ever reads
`TradeRecord.realized_return`/`holding_period`, never touches
`ExperienceRecord.state`.

See docs/specifications/PHASE-9-learning-engine.md section 8.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from learning.config import LabelConfig
from learning.models import CleaningResult, LabeledSample

from trade_journal.models import ExperienceRecord
from trade_journal.repository import TradeJournalRepository


class Labeler:
    version = "labeler_v1"

    def __init__(self, config: LabelConfig = LabelConfig()) -> None:
        self._config = config

    def label(
        self,
        valid_results: Sequence[CleaningResult],
        records_by_trade_id: dict[str, ExperienceRecord],
        journal: TradeJournalRepository,
        *,
        label_generated_at: datetime,
    ) -> list[LabeledSample]:
        config = self._config
        samples: list[LabeledSample] = []

        for result in valid_results:
            record = records_by_trade_id[result.trade_id]
            trade = journal.get_trade(result.trade_id)
            label_value = (record.actual_outcome or {}).get("realized_return")
            if label_value is None:
                # Cleaning already excludes a missing realized_return
                # from `valid_results` -- this is a defensive guard, not
                # an expected path.
                continue

            label_end_time: Optional[datetime] = None
            if trade is not None and trade.holding_period is not None:
                label_end_time = result.sample_as_of_time + trade.holding_period

            samples.append(LabeledSample(
                trade_id=result.trade_id,
                experience_id=result.experience_id,
                sample_as_of_time=result.sample_as_of_time,
                feature_cutoff_time=result.sample_as_of_time,
                label_start_time=result.sample_as_of_time,
                label_end_time=label_end_time,
                label_value=float(label_value),
                label_version=self.version,
                label_definition=config.label_definition,
                label_horizon=None,
                label_generated_at=label_generated_at,
                provenance=result.provenance,
                feature_version=None,  # Phase 3's ExperienceRecord.state has no feature_version field to copy from
                data_version=record.data_version or (),
                features=record.state.get("features"),  # ADR-0048/0049 -- None unless a Strategy set OrderIntent.features
            ))

        return samples
