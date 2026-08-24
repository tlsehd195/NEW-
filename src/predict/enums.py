"""Enumerations for the Prediction layer (Phase 6).

See docs/specifications/PHASE-6-prediction.md sections 2, 7.
"""

from __future__ import annotations

from enum import Enum


class PredictionMethodType(str, Enum):
    """Explicitly distinguishes a deterministic, non-learned baseline
    from a (not-yet-built) model-based predictor -- the instruction's
    "deterministic baseline과 model-based prediction을 명확하게 구분"
    requirement, made a queryable, typed field rather than left to a
    naming convention alone."""

    DETERMINISTIC_BASELINE = "DETERMINISTIC_BASELINE"
    MODEL_BASED = "MODEL_BASED"  # reserved -- no implementation ships in Phase 6
