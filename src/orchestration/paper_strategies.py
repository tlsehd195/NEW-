"""Named, pre-registered Paper Trading strategy configurations.

`scripts/run_paper_trading_cycle.py` used to answer "which components
does `run_cycle` get called with" with one hardcoded dict inline
(Session 36, ADR-0067/ADR-0082) -- the account owner's multi-strategy
request (Session 36 continued, ADR-0110: "45개 전략을 한 번에 페이퍼
트레이딩으로 돌릴 수 있는 멀티 전략 러너를 나중에 만들기로 함", the
future-work note `docs/PROJECT_STATUS.md` already recorded) needs more
than one such configuration nameable from a CLI flag, so that logic
moved here -- UNCHANGED in behavior for the one name ("baseline_rule")
that was already running in production daily.

**RULE 0.8 boundary, explicit**: every strategy registered here is
built ONLY from components this project already has, already tested,
already used elsewhere for exactly the purpose each plays here. None of
the 45 factor-research candidates (`strategy_research.factor_scores`)
are registered -- none has a real validated walk-forward result yet
(`docs/research/STRATEGY-VALIDATION-REPORT.md`'s own "Outstanding real
results not yet received" list), and RULE 0.8 forbids constructing or
selecting a strategy's rules after seeing any result. Adding a factor-
derived strategy here later requires that same discipline: decide its
construction BEFORE any real result, not after -- this module is not
where that decision gets made silently.

Two fundamentally different execution shapes exist and are NOT unified
into one interface (unifying them would either force `buy_and_hold`
through a Decision cycle it deliberately has none of, or force the
`run_cycle` strategies into a one-shot-allocation shape they are not):

- `PaperStrategyKind.RUN_CYCLE` -- one `orchestration.paper_runner.
  run_cycle` call per checkpoint, driven by a `(predictor, regime_
  detector, decision_agent, position_sizer, risk_engine)` component set
  this module's `build_run_cycle_components` constructs. The caller
  loops over checkpoints itself (see `scripts/run_paper_trading_cycle.py`
  and `scripts/run_multi_strategy_paper_trading_cycle.py`).
- `PaperStrategyKind.BUY_AND_HOLD` -- one `broker.paper.us_longterm_
  runner.run_buy_and_hold_paper_session` call on the first checkpoint
  only, then a per-checkpoint mark-to-market snapshot with no further
  orders (true buy & hold, ADR-0028's own low-turnover baseline
  selection) -- the caller drives this the same way.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from decision.agent import BaselineRuleDecisionAgent
from decision.config import DecisionConfig

from predict.config import PredictionConfig
from predict.predictor import DriftPredictor, Predictor, RandomWalkPredictor

from regime.config import RegimeConfig
from regime.detector import RegimeDetector

from risk.config import PositionSizingConfig, RiskConfig
from risk.engine import DeterministicPortfolioRiskEngine
from risk.sizing import DeterministicPositionSizer


class PaperStrategyKind(str, Enum):
    RUN_CYCLE = "run_cycle"
    BUY_AND_HOLD = "buy_and_hold"


@dataclass(frozen=True)
class PaperStrategySpec:
    name: str
    kind: PaperStrategyKind
    description: str


# `RandomWalkPredictor` is `predict.predictor`'s own documented
# "null-hypothesis baseline: no forecastable drift" companion to
# `DriftPredictor` (see its docstring) -- registering it here as a
# second RUN_CYCLE strategy needs no new forecasting logic, only
# wiring an already-built, already-tested component in a second place.
STRATEGIES: dict[str, PaperStrategySpec] = {
    "baseline_rule": PaperStrategySpec(
        name="baseline_rule",
        kind=PaperStrategyKind.RUN_CYCLE,
        description=(
            "DriftPredictor + BaselineRuleDecisionAgent + DeterministicPositionSizer + "
            "DeterministicPortfolioRiskEngine -- the exact configuration "
            "scripts/run_paper_trading_cycle.py ran inline before this registry existed "
            "(Session 36, ADR-0067/ADR-0082); the one strategy actually live in the daily "
            "GitHub Actions schedule."
        ),
    ),
    "random_walk_baseline": PaperStrategySpec(
        name="random_walk_baseline",
        kind=PaperStrategyKind.RUN_CYCLE,
        description=(
            "RandomWalkPredictor (expected_return=0.0 always, by construction of the null "
            "hypothesis) + the same BaselineRuleDecisionAgent/DeterministicPositionSizer/"
            "DeterministicPortfolioRiskEngine as baseline_rule -- a real statistical control, "
            "not a claim of skill: any strategy that cannot outperform this one over its own "
            "real paper-trading track record is not adding forecasting value."
        ),
    ),
    "buy_and_hold": PaperStrategySpec(
        name="buy_and_hold",
        kind=PaperStrategyKind.BUY_AND_HOLD,
        description=(
            "broker.paper.us_longterm_runner.run_buy_and_hold_paper_session -- equal-weight "
            "buy once across the universe on the first checkpoint, then never trade again "
            "(ADR-0028's own low-turnover reference baseline), already built and already "
            "used for the account owner's very first paper-trading track record but never "
            "before reachable from a strategy-name CLI flag."
        ),
    ),
}

_PREDICTOR_CLASSES: dict[str, type[Predictor]] = {
    "baseline_rule": DriftPredictor,
    "random_walk_baseline": RandomWalkPredictor,
}


@dataclass(frozen=True)
class RunCycleStartingIds:
    """Every `run_cycle`-shaped component allocates its own IDs from a
    counter that must be seeded from a store's real persisted max on
    any second invocation against a non-empty `--paper-store`
    (`scripts/run_paper_trading_cycle.py`'s own established discipline,
    ADR-0073) -- one field per component, never a single shared
    counter, since each is a genuinely separate ID namespace/table."""

    prediction: int = 1
    observation: int = 1
    composite: int = 1
    decision: int = 1
    sizing: int = 1
    risk: int = 1


def build_run_cycle_components(
    name: str, *, risk_config: RiskConfig, starting_ids: Optional[RunCycleStartingIds] = None,
) -> dict:
    """Builds the exact `(predictor, regime_detector, decision_agent,
    position_sizer, risk_engine)` dict `orchestration.paper_runner.
    run_cycle` takes as `**components`, for a RUN_CYCLE-kind strategy
    name. Raises `KeyError` for a BUY_AND_HOLD or unregistered name --
    callers must check `STRATEGIES[name].kind` first (mirroring
    `PaperTradingSession`'s own fail-closed discipline: no silent
    fallback to a different strategy)."""
    if name not in _PREDICTOR_CLASSES:
        raise KeyError(f"'{name}' is not a registered PaperStrategyKind.RUN_CYCLE strategy")
    ids = starting_ids or RunCycleStartingIds()
    predictor_cls = _PREDICTOR_CLASSES[name]
    # `lookback_days=20` matches `DriftPredictor`'s own original inline
    # configuration (pre-registry); `RandomWalkPredictor` ignores
    # `PredictionConfig` entirely (its own docstring: "needs no market
    # data lookup at all"), so the same value is harmless, not meaningful,
    # for that predictor -- passed uniformly rather than special-cased
    # to keep this function's one construction path simple.
    return dict(
        predictor=predictor_cls(PredictionConfig(lookback_days=20), starting_id=ids.prediction),
        regime_detector=RegimeDetector(
            RegimeConfig(), starting_observation_id=ids.observation, starting_composite_id=ids.composite,
        ),
        decision_agent=BaselineRuleDecisionAgent(DecisionConfig(), starting_id=ids.decision),
        position_sizer=DeterministicPositionSizer(PositionSizingConfig(), starting_id=ids.sizing),
        risk_engine=DeterministicPortfolioRiskEngine(risk_config, starting_id=ids.risk),
    )
