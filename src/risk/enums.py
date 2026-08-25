"""Enumerations for Position Sizing + Portfolio Risk Engine (Phase 8).

See docs/specifications/PHASE-8-position-sizing-and-risk.md section 8.
"""

from __future__ import annotations

from enum import Enum


class RiskCheckStatus(str, Enum):
    """The outcome vocabulary for both `PositionSizer` and
    `PortfolioRiskEngine` (instruction section 8: "최소 다음과 같은 상태를
    표현할 수 있어야 한다: PASS / REDUCE / REJECT / UNKNOWN"). Shared
    across both modules deliberately -- a single canonical vocabulary
    rather than two overlapping ones, since both express the same kind of
    outcome (grant the requested risk in full, grant a reduced amount,
    refuse it entirely, or refuse because the check itself could not run).

    PASS: the requested sizing/exposure was granted as computed, no
      external limit reduced it.
    REDUCE: an external limit (cash, a hard weight cap, gross exposure,
      concentration) clamped the result below what the unconstrained
      calculation would have produced, but a nonzero position remains.
    REJECT: the result is zero -- either a hard gate fired outright
      (e.g. volatility/liquidity/drawdown breach) or clamping left
      nothing tradeable.
    UNKNOWN: a required input was missing or invalid, so the check could
      not run at all. Per PROJECT_MASTER_PLAN.md section 1.4's
      fail-closed table and this phase's instruction section 9
      ("UNKNOWN -> DO NOT TRADE"), UNKNOWN is never treated as safe.
    """

    PASS = "PASS"
    REDUCE = "REDUCE"
    REJECT = "REJECT"
    UNKNOWN = "UNKNOWN"
