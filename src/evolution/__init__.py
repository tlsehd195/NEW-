"""Model Evolution (Phase 11).

See docs/specifications/PHASE-11-model-evolution.md and ADR-0017.

This package is fully additive on top of Phase 9's Learning Engine
(`learning.*`) and Phase 3/10's Trade Journal / Counterfactual types
(`trade_journal.*`, `counterfactual.*`) -- no Phase 0-10 source file is
modified to build it. It generates additional candidate models,
compares them, advances `learning.enums.CandidateModelStatus` through
`BACKTESTED -> VALIDATED -> OOS_TESTED` under explicit, auditable
criteria, tracks candidate lineage, and fills the counterfactual
"alternative model decision" slot Phase 3/10 reserved for this phase.

No code path in this package ever constructs
`CandidateModelStatus.APPROVED`/`DEPLOYED`, submits an order, or calls a
broker -- see `tests/evolution/test_evolution_boundary.py`.
"""

from __future__ import annotations
