"""derive_lineage: builds a `ModelLineageRecord` for a newly-trained
candidate, computing `generation` from its parent rather than trusting a
caller-supplied value (PROJECT_MASTER_PLAN.md section 4.5 lineage
tracking, applied to Model Evolution's own candidate tree).

See docs/specifications/PHASE-11-model-evolution.md section 6.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from evolution.models import ModelLineageRecord

from learning.models import CandidateModelArtifact


def derive_lineage(
    candidate: CandidateModelArtifact,
    *,
    parent: Optional[ModelLineageRecord] = None,
    lineage_basis: str = "initial",
    recorded_at: Optional[datetime] = None,
) -> ModelLineageRecord:
    """`parent=None` marks `candidate` as a root (generation 0) --
    e.g. Phase 9's first trainer run over a dataset. `parent` set marks
    `candidate` as evolved from that lineage record; `generation` is
    always `parent.generation + 1`, never a value the caller chooses
    directly, so a lineage chain can never have a gap or an
    inconsistent depth."""
    if parent is None:
        generation = 0
        parent_candidate_id = None
    else:
        generation = parent.generation + 1
        parent_candidate_id = parent.candidate_id

    return ModelLineageRecord(
        candidate_id=candidate.candidate_id,
        parent_candidate_id=parent_candidate_id,
        generation=generation,
        lineage_basis=lineage_basis,
        dataset_id=candidate.dataset_id,
        dataset_version=candidate.dataset_version,
        provenance=candidate.provenance,
        recorded_at=recorded_at,
    )
