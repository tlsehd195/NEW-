"""Enumerations for the Market Regime layer (Phase 5).

See docs/specifications/PHASE-5-market-regime.md sections 2, 5.

`RegimeProvenance` is intentionally *not* redefined here — it is
`trade_journal.enums.TradeProvenance`, reused directly rather than
duplicated (the same "reuse an existing type instead of a parallel
schema" discipline ADR-0009 already established for Phase 3, applied
here for the same reason: Regime observations must be classifiable as
HISTORICAL_SIMULATION | PAPER_TRADING | LIVE_TRADING exactly like every
other record this project keeps a permanent history of, and a second,
differently-spelled enum for the same concept would only invite drift).
"""

from __future__ import annotations

from enum import Enum


class RegimeAxis(str, Enum):
    """The five axes PROJECT_MASTER_PLAN.md section 7.6 names as an
    example classification scheme, plus DISTRIBUTION (Session 36,
    found while comparing this project against an external repository,
    dragon1086/prism-insight). Not "the" regime system -- an
    intentionally minimal, documented starting set (Phase 5 spec
    section 2) that this addition itself demonstrates is meant to grow."""

    TREND = "TREND"
    VOLATILITY = "VOLATILITY"
    LIQUIDITY = "LIQUIDITY"
    CORRELATION = "CORRELATION"
    STRESS = "STRESS"
    DISTRIBUTION = "DISTRIBUTION"


class SubjectKind(str, Enum):
    """What a regime observation describes: a single security, or a
    benchmark/index series (Phase 5 spec section 2 -- "시장 상태" is
    naturally a benchmark-level concept as often as a per-security one;
    both are supported by the same feature math since both PriceBar and
    BenchmarkPoint reduce to the same PricePoint shape, see points.py)."""

    SECURITY = "SECURITY"
    BENCHMARK = "BENCHMARK"


class TrendState(str, Enum):
    BULL = "BULL"
    BEAR = "BEAR"
    NEUTRAL = "NEUTRAL"
    UNKNOWN = "UNKNOWN"  # insufficient history -- fail-closed, never guessed


class VolatilityState(str, Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    EXTREME = "EXTREME"
    UNKNOWN = "UNKNOWN"


class LiquidityState(str, Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class CorrelationState(str, Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class StressState(str, Enum):
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class DistributionState(str, Enum):
    """IBD-style "distribution day" count over a trailing window --
    institutional-selling pressure (decline on rising volume), not the
    Volatility/Stress axes' price-only or drawdown-only view. NORMAL/
    ELEVATED/HIGH mirrors StressState's own naming since both are
    "how much selling pressure" classifications, just from different
    underlying evidence (see regime/features.py::compute_distribution_days)."""

    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


# Maps each axis to the Enum class its RegimeObservation.state string
# round-trips through. RegimeObservation.state is stored as a plain str
# (the winning enum member's .value) rather than a typed field, because a
# single dataclass generic across six different per-axis Enum domains
# has no single correct Enum type to declare -- this lookup is how a
# caller that needs the typed value back gets it: `AXIS_STATE_ENUM[axis](state_str)`.
AXIS_STATE_ENUM: dict[RegimeAxis, type[Enum]] = {
    RegimeAxis.TREND: TrendState,
    RegimeAxis.VOLATILITY: VolatilityState,
    RegimeAxis.LIQUIDITY: LiquidityState,
    RegimeAxis.CORRELATION: CorrelationState,
    RegimeAxis.STRESS: StressState,
    RegimeAxis.DISTRIBUTION: DistributionState,
}
