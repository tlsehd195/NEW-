"""ShadowEvaluationRecord + `evaluate_in_shadow`: a reusable harness for
comparing a candidate `PortfolioRiskEngine` configuration against the
one actually governing real trading, WITHOUT ever letting the candidate
affect a real decision.

Session 36 continued -- the fifth of 5 items found while comparing this
project against an external repository (dragon1086/prism-insight), and
the natural first user of it is item #4 from that same list, the
reentry-cooldown risk rule (ADR-0093): that ADR's own proposed number
(5 trading days) is PROPOSED, not ratified, per this project's "risk
limits are not self-modified by AI" principle -- this module is how a
proposed limit accumulates real evidence ("if this had been active,
here is what it would have changed") before a human ever ratifies it,
mirroring the governance SPIRIT of `strategy_research.evidence.
LiveActivationApproval` (a policy change needs a human-reviewed record
before it binds) WITHOUT reusing that class directly -- it is
strategy-promotion-specific, human-attested, and (per its own
AST-scan test) constructible only inside its own test file, none of
which fits "compare two risk-check outcomes for one order."

**The one guarantee this module exists to provide, structurally, not
just by convention**: `evaluate_in_shadow` returns the REAL
`RiskCheckedPosition` as the first element of its result -- the only
one a caller should ever act on -- and a separate `ShadowEvaluationRecord`
as the second, for accumulation and later human review. Nothing in this
module has a code path that lets the shadow engine's result influence
the real one; they are computed independently, from two independently
supplied `PortfolioRiskEngine` instances, and never merged.

Deliberately narrow, not "any policy change" in the abstract: built and
tested against `PortfolioRiskEngine.assess` comparisons specifically,
since that is the concrete need this session has (comparing two
`RiskConfig`s). A future use against a different comparison shape
(e.g. two `PositionSizer`s) would need its own record shape and
function, not a forced generalization of this one -- this project's own
"don't design for hypothetical future requirements" discipline, applied
here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Protocol

from risk.engine import PortfolioRiskEngine
from risk.enums import RiskCheckStatus
from risk.models import PositionSizingResult, RiskCheckedPosition

from backtest.portfolio import PortfolioView

from trade_journal.enums import TradeProvenance


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{name} must be timezone-aware: {value!r}")


@dataclass(frozen=True)
class ShadowEvaluationRecord:
    """One side-by-side comparison of a REAL risk-check outcome (the one
    that actually governed a decision) against a candidate/shadow
    policy's outcome for the exact same inputs. `diverged` is the
    field a human reviewing accumulated records cares about first --
    computed here, once, rather than re-derived by every consumer."""

    shadow_id: str  # "SHADOW-000001"
    as_of_time: datetime
    security_id: str
    policy_name: str  # caller-supplied, factual description of the shadow variant, e.g. "reentry_cooldown_days=5" -- never a fabricated narrative

    real_status: RiskCheckStatus
    real_reason: str
    shadow_status: RiskCheckStatus
    shadow_reason: str
    diverged: bool  # real_status != shadow_status

    provenance: TradeProvenance = TradeProvenance.HISTORICAL_SIMULATION
    experiment_id: Optional[str] = None
    recorded_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        if not self.shadow_id:
            raise ValueError("ShadowEvaluationRecord.shadow_id must not be empty")
        if not self.security_id:
            raise ValueError("ShadowEvaluationRecord.security_id must not be empty")
        if not self.policy_name:
            raise ValueError("ShadowEvaluationRecord.policy_name must not be empty")
        _require_aware("ShadowEvaluationRecord.as_of_time", self.as_of_time)


class ShadowEvaluationRepository(Protocol):
    def record(self, evaluation: ShadowEvaluationRecord) -> ShadowEvaluationRecord: ...

    def list_evaluations(
        self, *, policy_name: Optional[str] = None, security_id: Optional[str] = None,
        diverged_only: bool = False,
    ) -> list[ShadowEvaluationRecord]: ...


class ShadowIdAllocator:
    """Monotonic `shadow_id` allocation, mirroring `risk.engine._IdAllocator`
    -- a plain counter, not reused directly from that module since it is
    a private (`_`-prefixed) implementation detail of a different class,
    not a shared public utility."""

    def __init__(self, *, starting_id: int = 1) -> None:
        self._next_id = starting_id

    def allocate(self) -> str:
        sid = f"SHADOW-{self._next_id:06d}"
        self._next_id += 1
        return sid


class InMemoryShadowEvaluationRepository:
    """The reference implementation -- consumers depend only on the
    `ShadowEvaluationRepository` Protocol, mirroring every earlier
    phase's own InMemory-first, Protocol-typed repository pattern
    (`regime.repository.InMemoryRegimeRepository` et al.). A persistent
    DuckDB-backed implementation is a documented future step, not built
    now -- no real shadow-evaluation volume exists yet to justify one
    (this project's own "don't build ahead of real need" discipline)."""

    def __init__(self) -> None:
        self._evaluations: dict[str, ShadowEvaluationRecord] = {}

    def record(self, evaluation: ShadowEvaluationRecord) -> ShadowEvaluationRecord:
        self._evaluations[evaluation.shadow_id] = evaluation
        return evaluation

    def list_evaluations(
        self, *, policy_name: Optional[str] = None, security_id: Optional[str] = None,
        diverged_only: bool = False,
    ) -> list[ShadowEvaluationRecord]:
        results = list(self._evaluations.values())
        if policy_name is not None:
            results = [e for e in results if e.policy_name == policy_name]
        if security_id is not None:
            results = [e for e in results if e.security_id == security_id]
        if diverged_only:
            results = [e for e in results if e.diverged]
        return sorted(results, key=lambda e: e.as_of_time)


def evaluate_in_shadow(
    real_engine: PortfolioRiskEngine,
    shadow_engine: PortfolioRiskEngine,
    *,
    security_id: str,
    as_of_time: datetime,
    sizing_result: Optional[PositionSizingResult],
    portfolio_state: Optional[PortfolioView],
    policy_name: str,
    shadow_id: str,
    repository: Optional[ShadowEvaluationRepository] = None,
    current_price: Optional[float] = None,
    value_history=None,
    turnover: Optional[float] = None,
    liquidity_state: Optional[str] = None,
    sector_by_security: Optional[dict[str, str]] = None,
    last_exit_time_by_security: Optional[dict[str, datetime]] = None,
    provenance: TradeProvenance = TradeProvenance.HISTORICAL_SIMULATION,
    experiment_id: Optional[str] = None,
) -> tuple[RiskCheckedPosition, ShadowEvaluationRecord]:
    """Runs the IDENTICAL inputs through both `real_engine` and
    `shadow_engine`, independently. Returns `(real_result, evaluation)`
    -- `real_result` is the ONLY one a caller should ever act on
    (exactly what calling `real_engine.assess(...)` alone would have
    produced; `shadow_engine`'s own result never reaches it). If
    `repository` is supplied, the evaluation is also persisted before
    being returned, so a caller that only needs the real decision can
    ignore the second return value entirely without losing the record.

    `shadow_id` is caller-allocated (e.g. via `ShadowIdAllocator.
    allocate()`), the same "an already-allocated ID is a constructor
    argument, never generated as a side effect of construction" pattern
    every other ID-bearing model in this project already uses
    (`RegimeObservation.regime_id`, `RiskCheckedPosition.risk_id`)."""
    shared = dict(
        current_price=current_price, value_history=value_history, turnover=turnover,
        liquidity_state=liquidity_state, sector_by_security=sector_by_security,
        last_exit_time_by_security=last_exit_time_by_security,
        provenance=provenance, experiment_id=experiment_id,
    )
    real_result = real_engine.assess(security_id, as_of_time, sizing_result, portfolio_state, **shared)
    shadow_result = shadow_engine.assess(security_id, as_of_time, sizing_result, portfolio_state, **shared)

    evaluation = ShadowEvaluationRecord(
        shadow_id=shadow_id,
        as_of_time=as_of_time,
        security_id=security_id,
        policy_name=policy_name,
        real_status=real_result.status,
        real_reason=real_result.reason,
        shadow_status=shadow_result.status,
        shadow_reason=shadow_result.reason,
        diverged=real_result.status != shadow_result.status,
        provenance=provenance,
        experiment_id=experiment_id,
        recorded_at=as_of_time,
    )
    if repository is not None:
        evaluation = repository.record(evaluation)
    return real_result, evaluation
