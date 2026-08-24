"""Links Regime observations to the Trade Journal / Experience Dataset,
without modifying Phase 3's `trade_journal` package at all.

`ExperienceRecord.market_regime` already exists, reserved exactly for
this by Phase 3 (trade_journal/models.py: "reserved -- needs Phase 5").
This module is the first thing that actually populates it -- as an
explicit, opt-in enrichment step over an existing list of
`ExperienceRecord`s, not by changing `build_experience_records` itself
(Phase 5 spec section 12: "Backtest → Regime → Strategy 구조로 연결
가능한 interface를 만든다. 하지만 Phase 2의 기존 Strategy 동작을
불필요하게 변경하지 않는다" -- the same non-invasive-connection
discipline, applied to Phase 3 instead of Phase 2).
"""

from __future__ import annotations

import dataclasses
from typing import Optional, Sequence

from regime.enums import SubjectKind
from regime.repository import RegimeRepository

from trade_journal.enums import TradeProvenance
from trade_journal.models import ExperienceRecord
from trade_journal.repository import TradeJournalRepository


def attach_regime_context(
    records: Sequence[ExperienceRecord],
    journal: TradeJournalRepository,
    regime_repo: RegimeRepository,
    *,
    subject_id: str,
    subject_kind: SubjectKind = SubjectKind.SECURITY,
    provenance: Optional[TradeProvenance] = None,
) -> list[ExperienceRecord]:
    """For each record, looks up `journal.get_decision(record.decision_id)`
    to recover its `decision_time`, then finds the most recent
    `CompositeRegimeObservation` for `subject_id` at or before that time
    (a point-in-time query -- never a regime observation from after the
    decision, which would be exactly the kind of leakage this project's
    Point-in-Time principle forbids, applied here to Regime lineage
    instead of price data). Records with no matching decision or no
    regime observation available at that time are returned unchanged
    (`market_regime` stays `None` -- never fabricated)."""
    enriched: list[ExperienceRecord] = []
    for record in records:
        decision = journal.get_decision(record.decision_id)
        market_regime = record.market_regime
        if decision is not None:
            composite = regime_repo.get_composite_as_of(
                subject_id, subject_kind, decision.decision_time, provenance=provenance
            )
            if composite is not None:
                market_regime = composite.composite_label or _axis_summary(composite)
        enriched.append(dataclasses.replace(record, market_regime=market_regime))
    return enriched


def _axis_summary(composite) -> str:
    """A deterministic, human-readable fallback when no curated
    composite_label matched (regime.detector's curated label table is
    deliberately small, Phase 5 spec section 6) -- states every axis
    explicitly rather than silently omitting information the composite
    actually has."""
    parts = [f"{axis.value}={obs.state}" for axis, obs in sorted(composite.axes.items(), key=lambda kv: kv[0].value)]
    return "|".join(parts)
