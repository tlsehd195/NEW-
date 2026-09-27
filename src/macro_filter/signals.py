"""The macro filter's risk-off signals and exposure rules (ADR-0217
signal table, ADR-0220 exact definitions).

Every signal reads only what was known at `as_of`: macro values through
`PointInTimeMacroSeries`, prices through a bar reader that the backtest
binds to its own as-of view. A signal whose inputs are missing or stale
at `as_of` is `None` (unavailable) and never counts as risk-off.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable, Mapping, Optional, Sequence

from data_infra.models import PriceBar

from macro_filter.config import ALL_SIGNALS, COMBINED_SIGNALS, MacroFilterConfig
from macro_filter.series import PointInTimeMacroSeries

BarReader = Callable[[str, datetime, datetime], Sequence[PriceBar]]

# The FRED series each signal reads (the gold signal reads prices only).
SIGNAL_SERIES: dict[str, tuple[str, ...]] = {
    "vix_high": ("VIXCLS",),
    "curve_10y3m_inverted": ("T10Y3M",),
    "credit_widening": ("BAA10Y",),
    "sahm_rule": ("UNRATE",),
    "rate_shock": ("DGS2",),
    "dollar_squeeze": ("DTWEXBGS",),
    "nfci_positive": ("NFCI",),
    "claims_rise": ("ICSA",),
    "curve_10y2y_inverted": ("T10Y2Y",),
    "gold_flight": (),
}


@dataclass(frozen=True)
class MacroSignalSnapshot:
    as_of: datetime
    flags: Mapping[str, Optional[bool]]

    def active(self, signals: Sequence[str]) -> int:
        return sum(1 for s in signals if self.flags.get(s) is True)


def _nearest_rank_percentile(values: Sequence[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def _fresh(obs_date: date, as_of: datetime, max_days: int) -> bool:
    return (as_of.date() - obs_date).days <= max_days


def _value_on_or_before(values: Sequence[tuple[date, float]], target: date) -> Optional[tuple[date, float]]:
    found = None
    for d, v in values:
        if d > target:
            break
        found = (d, v)
    return found


def _months_consecutive(dates: Sequence[date]) -> bool:
    return all(
        (b.year * 12 + b.month) - (a.year * 12 + a.month) == 1 for a, b in zip(dates, dates[1:])
    )


class MacroSignalEngine:
    """Computes every signal at a checkpoint; results are cached per
    `as_of`, so several exposure rules (and the gross and net runs of the
    same fold) share one computation."""

    def __init__(self, series: Mapping[str, PointInTimeMacroSeries], config: MacroFilterConfig) -> None:
        self._series = dict(series)
        self._config = config
        self._cache: dict[datetime, MacroSignalSnapshot] = {}

    @property
    def config(self) -> MacroFilterConfig:
        return self._config

    def evaluate(self, as_of: datetime, bars: Optional[BarReader] = None) -> MacroSignalSnapshot:
        cached = self._cache.get(as_of)
        if cached is not None:
            return cached
        flags: dict[str, Optional[bool]] = {
            "vix_high": self._vix_high(as_of),
            "curve_10y3m_inverted": self._level_below_zero("T10Y3M", as_of),
            "credit_widening": self._change_above("BAA10Y", as_of, self._config.credit_widening_points, relative=False),
            "sahm_rule": self._sahm(as_of),
            "rate_shock": self._change_above("DGS2", as_of, self._config.rate_shock_points, relative=False),
            "dollar_squeeze": self._change_above("DTWEXBGS", as_of, self._config.dollar_squeeze_fraction, relative=True),
            "nfci_positive": self._nfci_positive(as_of),
            "claims_rise": self._claims_rise(as_of),
            "curve_10y2y_inverted": self._level_below_zero("T10Y2Y", as_of),
            "gold_flight": self._gold_flight(as_of, bars) if bars is not None else None,
        }
        assert tuple(flags) == ALL_SIGNALS
        snapshot = MacroSignalSnapshot(as_of, flags)
        self._cache[as_of] = snapshot
        return snapshot

    def _values(self, series_id: str, as_of: datetime, days: int) -> list[tuple[date, float]]:
        s = self._series.get(series_id)
        if s is None:
            return []
        return s.values_as_of(as_of, since=as_of.date() - timedelta(days=days))

    def _vix_high(self, as_of: datetime) -> Optional[bool]:
        c = self._config
        values = self._values("VIXCLS", as_of, c.vix_lookback_days)
        if len(values) < c.vix_min_observations or not _fresh(values[-1][0], as_of, c.max_staleness_days_daily):
            return None
        return values[-1][1] > _nearest_rank_percentile([v for _, v in values], c.vix_percentile)

    def _level_below_zero(self, series_id: str, as_of: datetime) -> Optional[bool]:
        values = self._values(series_id, as_of, self._config.max_staleness_days_daily)
        if not values:
            return None
        return values[-1][1] < 0

    def _nfci_positive(self, as_of: datetime) -> Optional[bool]:
        values = self._values("NFCI", as_of, self._config.max_staleness_days_weekly)
        if not values:
            return None
        return values[-1][1] > 0

    def _change_above(self, series_id: str, as_of: datetime, threshold: float, *, relative: bool) -> Optional[bool]:
        c = self._config
        staleness = c.max_staleness_days_daily
        values = self._values(series_id, as_of, c.change_lookback_days + 2 * staleness)
        if not values or not _fresh(values[-1][0], as_of, staleness):
            return None
        latest_date, latest = values[-1]
        target = latest_date - timedelta(days=c.change_lookback_days)
        prior = _value_on_or_before(values, target)
        if prior is None or (target - prior[0]).days > staleness:
            return None
        if relative:
            if prior[1] <= 0:
                return None
            return latest / prior[1] - 1.0 > threshold
        return latest - prior[1] > threshold

    def _sahm(self, as_of: datetime) -> Optional[bool]:
        """Real-time Sahm rule: the 3-month average unemployment rate is
        at least 0.5 pt above its minimum over the previous 12 months,
        using only the vintages known at `as_of`."""
        c = self._config
        values = self._values("UNRATE", as_of, 20 * 31)
        if len(values) < 15 or not _fresh(values[-1][0], as_of, c.max_staleness_days_monthly):
            return None
        recent = values[-15:]
        if not _months_consecutive([d for d, _ in recent]):
            return None
        rates = [v for _, v in recent]
        averages = [statistics.fmean(rates[i - 2 : i + 1]) for i in range(2, len(rates))]
        return averages[-1] - min(averages[-13:-1]) >= c.sahm_threshold_points

    def _claims_rise(self, as_of: datetime) -> Optional[bool]:
        """4-week average initial claims more than 20% above the lowest
        4-week average of the trailing 52 weeks."""
        c = self._config
        weeks = c.claims_low_lookback_weeks + c.claims_average_weeks
        values = self._values("ICSA", as_of, (weeks + 4) * 7)
        if len(values) < weeks or not _fresh(values[-1][0], as_of, c.max_staleness_days_weekly):
            return None
        claims = [v for _, v in values[-weeks:]]
        n = c.claims_average_weeks
        averages = [statistics.fmean(claims[i - n + 1 : i + 1]) for i in range(n - 1, len(claims))]
        low = min(averages[-c.claims_low_lookback_weeks :])
        if low <= 0:
            return None
        return averages[-1] / low - 1.0 > c.claims_rise_fraction

    def _gold_flight(self, as_of: datetime, bars: BarReader) -> Optional[bool]:
        """GLD out-returned SPY over the last 63 trading days (flight to
        safety). Ratios of adjusted closes include the window's own
        dividends only, so they are point-in-time safe."""
        c = self._config
        start = as_of - timedelta(days=c.gold_lookback_trading_days * 2 + 14)
        closes: dict[str, dict[date, float]] = {}
        for symbol in (c.gold_symbol, c.equity_symbol):
            series: dict[date, float] = {}
            for bar in bars(symbol, start, as_of):
                price = bar.adjusted_close if bar.adjusted_close is not None else bar.close
                if price > 0:
                    series[bar.timestamp.date()] = price
            closes[symbol] = series
        common = sorted(set(closes[c.gold_symbol]) & set(closes[c.equity_symbol]))
        n = c.gold_lookback_trading_days
        if len(common) < n + 1 or not _fresh(common[-1], as_of, c.max_staleness_days_daily):
            return None
        first, last = common[-n - 1], common[-1]
        gold = closes[c.gold_symbol][last] / closes[c.gold_symbol][first]
        equity = closes[c.equity_symbol][last] / closes[c.equity_symbol][first]
        return gold > equity


@dataclass(frozen=True)
class ExposureRule:
    """One pre-registered trial. `signals=()` is the unfiltered baseline
    (always 100%); one signal is a single-signal trial; the combined
    rule counts active flags through the config's mapping."""

    name: str
    signals: tuple[str, ...]

    def exposure(self, snapshot: MacroSignalSnapshot, config: MacroFilterConfig) -> float:
        if not self.signals:
            return 1.0
        active = snapshot.active(self.signals)
        if len(self.signals) == 1:
            return config.single_signal_exposure if active else 1.0
        return config.combined_exposure(active)


BASELINE_RULE = ExposureRule("no_filter", ())
COMBINED_RULE = ExposureRule("combined", COMBINED_SIGNALS)


def pre_registered_rules() -> tuple[ExposureRule, ...]:
    """Every trial the validation evaluates, fixed before the first run:
    the baseline, the combined filter, and each signal alone."""
    return (BASELINE_RULE, COMBINED_RULE) + tuple(ExposureRule(f"only_{s}", (s,)) for s in ALL_SIGNALS)
