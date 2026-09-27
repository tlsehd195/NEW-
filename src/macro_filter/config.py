"""MacroFilterConfig: every signal threshold, window, fallback lag and the
exposure mapping of the macro filter, frozen before the first backtest
(ADR-0217 "Multiple-testing guard", ADR-0220). Any change after results
have been seen is a new trial: bump `version`, and the validation report
counts it in the DSR/PBO trial set.

Thresholds are the fixed rules ADR-0217's signal table names, not fitted
values. The fallback lags are the MAX release lags ALFRED shows for each
series in its vintage era (ADR-0217 coverage tables, runs 36266048908),
never smaller than 1 day.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from data_infra.versioning import compute_data_version

# The nine ADR-0217 table signals, in table order. They make up the
# combined filter.
COMBINED_SIGNALS: tuple[str, ...] = (
    "vix_high",
    "curve_10y3m_inverted",
    "credit_widening",
    "sahm_rule",
    "rate_shock",
    "dollar_squeeze",
    "nfci_positive",
    "claims_rise",
    "curve_10y2y_inverted",
)

# Evaluated alone only. ADR-0217 allowed gold into the table only if
# pre-registered; it is registered here as a single-signal trial, and
# deliberately kept out of the combined count so the frozen table stays
# as written.
EXTRA_SIGNALS: tuple[str, ...] = ("gold_flight",)

ALL_SIGNALS: tuple[str, ...] = COMBINED_SIGNALS + EXTRA_SIGNALS


def _default_fallback_lags() -> dict[str, int]:
    # Only for series flagged revised=False in MACRO_SERIES_CATALOG: before
    # a series' first archived vintage, an observation counts as known
    # `lag` days after its observation date (then the usual
    # next-day-06:00-UTC stamp). Revised series (UNRATE, ICSA, NFCI,
    # DTWEXBGS) never get a fallback.
    return {
        "DFF": 9,
        "DGS3MO": 11,
        "DGS2": 11,
        "DGS10": 11,
        "T10Y2Y": 6,
        "T10Y3M": 6,
        "BAA10Y": 1,
        "VIXCLS": 1,
    }


@dataclass(frozen=True)
class MacroFilterConfig:
    version: str = "macro_filter_config_v1"

    vix_percentile: float = 0.80
    vix_lookback_days: int = 365
    vix_min_observations: int = 200

    change_lookback_days: int = 91  # "over 3 months"
    credit_widening_points: float = 1.0
    rate_shock_points: float = 1.0
    dollar_squeeze_fraction: float = 0.05

    sahm_threshold_points: float = 0.5

    claims_average_weeks: int = 4
    claims_low_lookback_weeks: int = 52
    claims_rise_fraction: float = 0.20

    gold_symbol: str = "GLD"
    equity_symbol: str = "SPY"
    gold_lookback_trading_days: int = 63

    # A value older than this (in calendar days, measured from as-of) is
    # stale and the signal reads as unavailable. Covers monthly releases
    # (~34-59 days lag + a month) with room to spare.
    max_staleness_days_daily: int = 14
    max_staleness_days_weekly: int = 30
    max_staleness_days_monthly: int = 100

    # Combined filter: count of active flags -> exposure (ADR-0217).
    # Index = number of active flags, capped at the last entry.
    combined_exposure_by_count: tuple[float, ...] = (1.0, 1.0, 0.75, 0.5)
    # Single-signal trials: exposure while that one flag is active.
    single_signal_exposure: float = 0.5

    fallback_lag_days: dict[str, int] = field(default_factory=_default_fallback_lags)

    def configuration_version(self) -> str:
        return compute_data_version(asdict(self))

    def combined_exposure(self, active_count: int) -> float:
        table = self.combined_exposure_by_count
        return table[min(active_count, len(table) - 1)]


DEFAULT_MACRO_FILTER_CONFIG = MacroFilterConfig()
