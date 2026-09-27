"""Category: point-in-time correctness and rule definitions of the macro
filter (ADR-0220): a signal may only use values known at the checkpoint,
the pre-archive fallback applies only to never-revised series, and each
pre-registered exposure rule maps flags to the documented exposure."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

import pytest

from backtest_helpers import build_repository, make_bars, make_security, trading_days

from backtest.engine import BacktestConfig, BacktestEngine
from data_infra.providers.fred import FredVintageObservation, vintage_to_macro_record
from macro_filter.config import ALL_SIGNALS, COMBINED_SIGNALS, MacroFilterConfig
from macro_filter.series import PointInTimeMacroSeries, build_series
from macro_filter.signals import (
    BASELINE_RULE,
    COMBINED_RULE,
    ExposureRule,
    MacroSignalEngine,
    MacroSignalSnapshot,
    pre_registered_rules,
)
from macro_filter.strategy import MacroExposureStrategy

_NOW = datetime(2026, 9, 27, tzinfo=timezone.utc)
_CONFIG = MacroFilterConfig()


def _utc(y, m, d, h=0) -> datetime:
    return datetime(y, m, d, h, tzinfo=timezone.utc)


def _rec(series: str, obs: date, value: Optional[float], start: date, end: Optional[date] = None):
    return vintage_to_macro_record(FredVintageObservation(series, obs, value, start, end, _NOW), ingestion_time=_NOW)


def _daily(series: str, first: date, values: list[float], *, vintage: Optional[date] = None) -> list:
    """One vintage per day, released on the observation date itself, or
    (with `vintage`) every observation stamped with that one vintage, the
    way ALFRED stamps observations older than its first archive."""
    out = []
    for i, v in enumerate(values):
        d = first + timedelta(days=i)
        out.append(_rec(series, d, v, vintage or d))
    return out


# ---- PointInTimeMacroSeries ------------------------------------------------


def test_revision_is_invisible_until_it_is_known() -> None:
    s = PointInTimeMacroSeries("UNRATE", [
        _rec("UNRATE", date(2008, 1, 1), 5.0, date(2008, 2, 1), date(2008, 2, 29)),
        _rec("UNRATE", date(2008, 1, 1), 5.4, date(2008, 3, 1)),
    ])
    assert s.values_as_of(_utc(2008, 2, 1, 23), since=date(2008, 1, 1)) == []
    assert s.values_as_of(_utc(2008, 2, 2, 6), since=date(2008, 1, 1)) == [(date(2008, 1, 1), 5.0)]
    assert s.values_as_of(_utc(2008, 3, 2, 6), since=date(2008, 1, 1)) == [(date(2008, 1, 1), 5.4)]


def test_withdrawn_observation_disappears_once_known() -> None:
    s = PointInTimeMacroSeries("UNRATE", [_rec("UNRATE", date(2008, 1, 1), 5.0, date(2008, 2, 1), date(2008, 2, 10))])
    assert s.values_as_of(_utc(2008, 2, 10, 12), since=date(2008, 1, 1)) == [(date(2008, 1, 1), 5.0)]
    assert s.values_as_of(_utc(2008, 2, 12, 6), since=date(2008, 1, 1)) == []


def test_fallback_makes_pre_archive_values_known_after_the_lag() -> None:
    records = _daily("VIXCLS", date(2008, 10, 1), [30.0, 40.0], vintage=date(2010, 11, 22))
    strict = PointInTimeMacroSeries("VIXCLS", records)
    fallback = PointInTimeMacroSeries("VIXCLS", records, fallback_lag_days=1)
    as_of = _utc(2008, 10, 3, 20)  # Oct 1 + 1 day lag -> Oct 3 06:00; Oct 2 -> Oct 4 06:00
    assert strict.values_as_of(as_of, since=date(2008, 1, 1)) == []
    assert fallback.values_as_of(as_of, since=date(2008, 1, 1)) == [(date(2008, 10, 1), 30.0)]


def test_fallback_never_applies_after_the_first_vintage() -> None:
    first = date(2010, 11, 22)
    records = [_rec("VIXCLS", date(2010, 11, 20), 20.0, first), _rec("VIXCLS", date(2010, 12, 1), 25.0, date(2010, 12, 10))]
    s = PointInTimeMacroSeries("VIXCLS", records, fallback_lag_days=1)
    assert s.values_as_of(_utc(2010, 12, 5, 20), since=date(2010, 11, 1)) == [(date(2010, 11, 20), 20.0)]


def test_fallback_is_refused_for_a_revised_series() -> None:
    with pytest.raises(ValueError):
        PointInTimeMacroSeries("UNRATE", [], fallback_lag_days=1)
    # build_series silently gives revised series no fallback.
    records = [_rec("ICSA", date(2005, 1, 1), 300.0, date(2009, 5, 28))]
    assert build_series("ICSA", records, {"ICSA": 5}).values_as_of(_utc(2005, 2, 1), since=date(2004, 1, 1)) == []


# ---- signals -----------------------------------------------------------------


def _engine(**series_records) -> MacroSignalEngine:
    series = {sid: build_series(sid, recs, _CONFIG.fallback_lag_days) for sid, recs in series_records.items()}
    return MacroSignalEngine(series, _CONFIG)


def test_every_signal_is_unavailable_without_data() -> None:
    snap = _engine().evaluate(_utc(2010, 1, 5, 20))
    assert set(snap.flags) == set(ALL_SIGNALS)
    assert all(v is None for v in snap.flags.values())


def test_vix_high_compares_the_latest_close_with_its_trailing_80th_percentile() -> None:
    values = [15.0] * 300 + [40.0]
    engine = _engine(VIXCLS=_daily("VIXCLS", date(2015, 1, 1), values))
    last = date(2015, 1, 1) + timedelta(days=300)
    assert engine.evaluate(datetime.combine(last + timedelta(days=1), datetime.min.time(), timezone.utc) + timedelta(hours=20)).flags["vix_high"] is True
    # The day before, the latest value (15) is not above the percentile.
    assert engine.evaluate(datetime.combine(last, datetime.min.time(), timezone.utc) + timedelta(hours=20)).flags["vix_high"] is False


def test_vix_high_needs_enough_history() -> None:
    engine = _engine(VIXCLS=_daily("VIXCLS", date(2015, 1, 1), [15.0] * 50))
    assert engine.evaluate(_utc(2015, 2, 21, 20)).flags["vix_high"] is None


def test_curve_inversion_and_staleness() -> None:
    engine = _engine(T10Y3M=_daily("T10Y3M", date(2019, 5, 1), [0.1, -0.2]))
    assert engine.evaluate(_utc(2019, 5, 3, 20)).flags["curve_10y3m_inverted"] is True
    assert engine.evaluate(_utc(2019, 5, 2, 20)).flags["curve_10y3m_inverted"] is False
    # 15+ days without a new value: stale, unavailable.
    assert engine.evaluate(_utc(2019, 5, 20, 20)).flags["curve_10y3m_inverted"] is None


def test_credit_widening_is_a_three_month_change() -> None:
    values = [2.0] * 100 + [3.2]
    engine = _engine(BAA10Y=_daily("BAA10Y", date(2008, 1, 1), values))
    last = date(2008, 1, 1) + timedelta(days=100)
    as_of = datetime(last.year, last.month, last.day, 20, tzinfo=timezone.utc) + timedelta(days=1)
    assert engine.evaluate(as_of).flags["credit_widening"] is True
    engine2 = _engine(BAA10Y=_daily("BAA10Y", date(2008, 1, 1), [2.0] * 100 + [2.9]))
    assert engine2.evaluate(as_of).flags["credit_widening"] is False


def _monthly(series: str, first_year: int, values: list[float], lag_days: int = 35) -> list:
    out = []
    for i, v in enumerate(values):
        y, m = divmod(first_year * 12 + i, 12)
        obs = date(y, m + 1, 1)
        out.append(_rec(series, obs, v, obs + timedelta(days=lag_days)))
    return out


def test_sahm_rule_triggers_at_half_a_point() -> None:
    flat = [4.0] * 14
    rising = flat + [4.0, 4.6, 4.9]  # 3m avg 4.5 vs low 4.0
    engine = _engine(UNRATE=_monthly("UNRATE", 2000, rising))
    assert engine.evaluate(_utc(2001, 6, 20, 20)).flags["sahm_rule"] is True
    engine2 = _engine(UNRATE=_monthly("UNRATE", 2000, flat + [4.0, 4.3, 4.6]))
    assert engine2.evaluate(_utc(2001, 6, 20, 20)).flags["sahm_rule"] is False


def test_sahm_rule_uses_the_first_print_until_the_revision_is_known() -> None:
    records = _monthly("UNRATE", 2000, [4.0] * 16)  # last month 2001-04, printed 2001-05-06
    # That month is revised from 4.0 up to 6.0 on 2001-07-01.
    records.append(_rec("UNRATE", date(2001, 4, 1), 6.0, date(2001, 7, 1)))
    engine = _engine(UNRATE=records)
    assert engine.evaluate(_utc(2001, 6, 20, 20)).flags["sahm_rule"] is False
    assert engine.evaluate(_utc(2001, 7, 2, 20)).flags["sahm_rule"] is True


def test_claims_rise_against_the_52_week_low() -> None:
    weeks = [300.0] * 56
    spike = weeks[:-4] + [380.0] * 4
    first = date(2012, 1, 7)
    recs = [_rec("ICSA", first + timedelta(weeks=i), v, first + timedelta(weeks=i, days=5)) for i, v in enumerate(spike)]
    as_of = datetime.combine(first + timedelta(weeks=55, days=7), datetime.min.time(), timezone.utc) + timedelta(hours=20)
    assert _engine(ICSA=recs).evaluate(as_of).flags["claims_rise"] is True
    flat = [_rec("ICSA", first + timedelta(weeks=i), v, first + timedelta(weeks=i, days=5)) for i, v in enumerate(weeks)]
    assert _engine(ICSA=flat).evaluate(as_of).flags["claims_rise"] is False


def test_nfci_positive() -> None:
    recs = [_rec("NFCI", date(2012, 1, 6), 0.3, date(2012, 1, 11))]
    assert _engine(NFCI=recs).evaluate(_utc(2012, 1, 12, 20)).flags["nfci_positive"] is True
    assert _engine(NFCI=recs).evaluate(_utc(2012, 1, 11, 20)).flags["nfci_positive"] is None


def test_gold_flight_compares_63_day_returns() -> None:
    days = trading_days(date(2008, 1, 2), date(2008, 5, 30))
    gld = make_bars("GLD", days, [100.0 + i for i in range(len(days))])
    spy = make_bars("SPY", days, [100.0] * len(days))
    by_symbol = {"GLD": gld, "SPY": spy}

    def reader(symbol, start, end):
        return [b for b in by_symbol[symbol] if start <= b.timestamp <= end and b.available_time <= end]

    as_of = datetime.combine(days[-1], datetime.min.time(), timezone.utc) + timedelta(hours=20)
    assert _engine().evaluate(as_of, reader).flags["gold_flight"] is True


# ---- exposure rules ---------------------------------------------------------


def _snap(**flags) -> MacroSignalSnapshot:
    return MacroSignalSnapshot(_utc(2010, 1, 1), {s: flags.get(s) for s in ALL_SIGNALS})


def test_combined_mapping() -> None:
    assert COMBINED_RULE.exposure(_snap(), _CONFIG) == 1.0
    assert COMBINED_RULE.exposure(_snap(vix_high=True), _CONFIG) == 1.0
    assert COMBINED_RULE.exposure(_snap(vix_high=True, sahm_rule=True), _CONFIG) == 0.75
    three = dict(vix_high=True, sahm_rule=True, credit_widening=True, rate_shock=True)
    assert COMBINED_RULE.exposure(_snap(**three), _CONFIG) == 0.5
    # Gold is not part of the combined count; unavailable never counts.
    assert COMBINED_RULE.exposure(_snap(vix_high=True, gold_flight=True, sahm_rule=None), _CONFIG) == 1.0


def test_single_and_baseline_rules() -> None:
    only = ExposureRule("only_vix_high", ("vix_high",))
    assert only.exposure(_snap(vix_high=True), _CONFIG) == 0.5
    assert only.exposure(_snap(vix_high=None), _CONFIG) == 1.0
    assert BASELINE_RULE.exposure(_snap(vix_high=True), _CONFIG) == 1.0


def test_pre_registered_rule_set_is_fixed() -> None:
    rules = pre_registered_rules()
    assert [r.name for r in rules][:2] == ["no_filter", "combined"]
    assert len(rules) == 2 + len(ALL_SIGNALS) == 12
    assert COMBINED_RULE.signals == COMBINED_SIGNALS


def test_config_version_changes_with_any_threshold() -> None:
    assert MacroFilterConfig().configuration_version() == MacroFilterConfig().configuration_version()
    assert MacroFilterConfig(vix_percentile=0.9).configuration_version() != MacroFilterConfig().configuration_version()


# ---- strategy through the real engine ---------------------------------------


class _FixedEngine:
    """Signal engine stand-in whose VIX flag turns on at `switch_day`."""

    def __init__(self, switch_day: date) -> None:
        self.config = _CONFIG
        self._switch = switch_day

    def evaluate(self, as_of, bars=None):
        return _snap(vix_high=as_of.date() >= self._switch)


def _run(rule: ExposureRule, switch_day: date):
    days = trading_days(date(2019, 1, 2), date(2019, 3, 29))
    repo = build_repository(bars=make_bars("SPY", days, [100.0] * len(days)), securities=[make_security("SPY", "SPY")])
    strategy = MacroExposureStrategy("SPY", _FixedEngine(switch_day), rule)
    config = BacktestConfig(market="US_EQUITY", start_date=days[0], end_date=days[-1], initial_capital=10_000.0, security_ids=("SPY",))
    return BacktestEngine(repo, config, strategy).run(), strategy


def test_strategy_halves_the_position_when_the_flag_turns_on() -> None:
    result, strategy = _run(ExposureRule("only_vix_high", ("vix_high",)), date(2019, 2, 15))
    sides = [f.side.value for f in result.fills]
    assert sides == ["BUY", "SELL"]
    bought, sold = result.fills[0].quantity, result.fills[1].quantity
    assert bought == 98 and sold == pytest.approx(49, abs=1)
    assert strategy.exposure_log[0][1] == 1.0 and strategy.exposure_log[-1][1] == 0.5


def test_baseline_buys_once_and_holds() -> None:
    result, _ = _run(BASELINE_RULE, date(2019, 2, 15))
    assert [f.side.value for f in result.fills] == ["BUY"]


def test_sahm_rule_tolerates_one_missing_month() -> None:
    """FRED has no UNRATE for 2025-10 (BLS skipped it during the shutdown)."""
    from macro_filter.signals import sahm_rule_reading

    months = [(date(2025 + (i // 12), i % 12 + 1, 1), 4.0) for i in range(3, 21)]
    gapped = [(d, v) for d, v in months if d != date(2025, 10, 1)]
    reading = sahm_rule_reading(gapped, _utc(2026, 9, 27), _CONFIG)
    assert reading is not None and reading.active is False and reading.gap == 0.0
    # Two missing months in one 3-month window: no reading.
    thin = [(d, v) for d, v in gapped if d != date(2025, 11, 1)]
    assert sahm_rule_reading(thin, _utc(2026, 9, 27), _CONFIG) is None
