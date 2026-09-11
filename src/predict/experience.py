"""Links Prediction output to the Trade Journal / Experience Dataset,
without modifying Phase 3's `trade_journal` package -- the identical
non-invasive pattern `regime.experience.attach_regime_context` already
established (ADR-0011 section 5).

`ExperienceRecord.expected_outcome` already exists on Phase 3's model,
populated today only when `DecisionSnapshot.expected_return`/
`expected_risk` are set (never true for a Phase 2-sourced backtest,
since Phase 2 has no Prediction Engine). This module is the first thing
that can actually populate it with a real prediction, as an explicit,
opt-in enrichment step -- never by changing
`trade_journal.experience.build_experience_records` itself.
"""

from __future__ import annotations

import dataclasses
from typing import Optional, Sequence

from predict.repository import PredictionRepository

from trade_journal.enums import TradeProvenance
from trade_journal.models import ExperienceRecord
from trade_journal.repository import TradeJournalRepository


def attach_prediction_context(
    records: Sequence[ExperienceRecord],
    journal: TradeJournalRepository,
    prediction_repo: PredictionRepository,
    *,
    security_id: Optional[str] = None,
    method: Optional[str] = None,
    provenance: Optional[TradeProvenance] = None,
) -> list[ExperienceRecord]:
    """For each record, looks up its decision's `decision_time` AND
    `security_id`, then finds the most recent `PredictionOutput` for
    THAT security at or before that time (point-in-time -- never a
    prediction made after the decision). A record whose
    `expected_outcome` is already populated is left untouched (never
    overwritten with a possibly different, later re-run's prediction);
    a record with no matching decision or no prediction available at
    that time is returned unchanged.

    `security_id`, if given, restricts enrichment to records whose own
    decision is for that security -- every other record is returned
    unchanged. It is NEVER substituted for a record's own
    `decision.security_id` when looking up a prediction (Session 37,
    ADR-0115, external review N-8): doing so silently attached another
    security's prediction to a record whenever `records` spanned more
    than one security (undetected by this module's own tests, which
    only ever exercised a single security). Omit it (the default) to
    enrich every eligible record regardless of which security it is
    for."""
    enriched: list[ExperienceRecord] = []
    for record in records:
        if record.expected_outcome is not None:
            enriched.append(record)
            continue
        decision = journal.get_decision(record.decision_id)
        expected_outcome = None
        if decision is not None and (security_id is None or decision.security_id == security_id):
            prediction = prediction_repo.get_as_of(
                decision.security_id, decision.decision_time, method=method, provenance=provenance
            )
            if prediction is not None:
                expected_outcome = {
                    "expected_return": prediction.expected_return,
                    "expected_volatility": prediction.expected_volatility,
                    "probability": prediction.probability,
                    "uncertainty": prediction.uncertainty,
                    "confidence": prediction.confidence,
                    "prediction_id": prediction.prediction_id,
                    "method": prediction.method,
                }
        enriched.append(dataclasses.replace(record, expected_outcome=expected_outcome))
    return enriched
