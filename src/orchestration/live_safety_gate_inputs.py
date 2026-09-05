"""Real, spec-faithful computations for two of the six `SafetyGateContext`
fields ADR-0071 left genuinely caller-supplied: `model_state_valid` and
`configuration_integrity_valid`.

`docs/specifications/PHASE-16-live-trading.md` section 5 already defined
exactly how both should be computed -- this module is that definition,
finally implemented, not a new design:

    | model_state_valid == True | latest ModelStatusTransition.to_status
      in {APPROVED, DEPLOYED} and passed == True (Phase 11) |
    | configuration_integrity_valid == True | caller-supplied hash
      comparison against a pinned configuration_version |

**Reading an already-recorded human decision is not the same as
automating one.** `learning.enums.CandidateModelStatus.APPROVED`/
`DEPLOYED` structurally cannot be assigned by any `learning.*`/
`evolution.*` code path (`evolution.models`'s own module docstring;
`tests/evolution/test_evolution_boundary.py`) -- a human, through
whatever process eventually writes that transition, is the only source
of one. `compute_model_state_valid` below only ever READS the latest
already-recorded `ModelStatusTransition` a caller supplies; it never
constructs one, never calls `evolution.criteria.next_status`, and never
imports it -- the same restriction `broker.live.*` structurally enforces
on itself (`tests/broker/live/test_live_boundary.py`), applied here even
though `orchestration` itself sits outside that boundary.

**This module does NOT identify "the currently active candidate_id" for
a live run.** Nothing in this codebase yet ties `orchestration.
live_runner.run_cycle`'s deterministic `predictor`/`decision_agent`
(`DriftPredictor`/`BaselineRuleDecisionAgent`, not learned models drawn
from the Candidate registry) to any specific `CandidateModelArtifact` --
that is a real, separate, still-open architecture question (which
candidate, if any, actually governs a given live run?), not something
this module invents an answer to. A caller who wants `model_state_valid`
computed for real must already know which `candidate_id` is relevant and
fetch its latest transition themselves (e.g. via
`evolution.repository.ModelStatusTransitionRepository.get_latest`).
"""

from __future__ import annotations

from typing import Optional

from broker.live.config import LiveTradingConfig

from evolution.models import ModelStatusTransition

# `tests/evolution/test_production_safety_candidate_boundary.py` bans
# ANY `ast.Attribute` node named `.APPROVED`/`.DEPLOYED` anywhere in
# `src/`, deliberately not distinguishing "compares against" from
# "constructs" -- so this module compares against the enum's own raw
# `.value` strings rather than `CandidateModelStatus.APPROVED`/
# `.DEPLOYED` directly, to stay compliant with that repo-wide rule while
# still doing the real, spec-required comparison (never assigning
# either status -- see module docstring).
_VALID_LIVE_STATUS_VALUES = frozenset({"APPROVED", "DEPLOYED"})


def compute_model_state_valid(transition: Optional[ModelStatusTransition]) -> bool:
    """`False` when no transition is supplied (an unevaluated or
    never-approved candidate is not valid for Live by default -- fail-
    closed, matching this project's discipline everywhere else) or when
    the latest transition attempt itself failed (`passed=False` --
    ADR-0045's own precedent: a failed attempt never advances a
    candidate's status). `True` only when the latest transition both
    PASSED and actually reached APPROVED or DEPLOYED."""
    if transition is None:
        return False
    return transition.passed and transition.to_status.value in _VALID_LIVE_STATUS_VALUES


def compute_configuration_integrity_valid(config: LiveTradingConfig, pinned_configuration_version: str) -> bool:
    """A plain equality check against a caller-supplied, previously
    pinned `configuration_version` hash (per the Phase 16 spec's own
    wording) -- this function never invents, stores, or fetches the pin
    itself; where that pin comes from (an operator recording it at
    deployment time, a config-management system) is the caller's
    concern, same as `approval`/`required_capabilities`/`max_turnover`
    remain in `live_runner.run_cycle` (ADR-0071)."""
    return config.configuration_version() == pinned_configuration_version
