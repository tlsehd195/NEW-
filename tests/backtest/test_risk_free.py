"""ADR-0227: window-average 3-month T-bill yield as the risk-free rate."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from backtest.risk_free import RiskFreeRates
from data_infra.macro_models import MacroObservationRecord
from data_infra.models import Provenance


def _utc(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def _record(obs: date, value, vintage: date) -> MacroObservationRecord:
    return MacroObservationRecord(
        series_id="DGS3MO", observation_date=_utc(obs), value=value,
        realtime_start=_utc(vintage), realtime_end=None, available_time=_utc(vintage),
        ingestion_time=_utc(vintage),
        provenance=Provenance(
            source="test", source_dataset="DGS3MO", source_record_id=f"{obs}@{vintage}",
            retrieved_at=_utc(vintage), data_version="v1",
        ),
    )


class TestAverageAnnualRate:
    def test_mean_of_the_window_as_a_decimal(self) -> None:
        rates = RiskFreeRates([(date(2024, 1, 2), 5.0), (date(2024, 1, 3), 4.0), (date(2024, 2, 1), 1.0)], source="t")
        assert rates.average_annual_rate(date(2024, 1, 1), date(2024, 1, 31)) == pytest.approx(0.045)

    def test_window_bounds_are_inclusive(self) -> None:
        rates = RiskFreeRates([(date(2024, 1, 2), 5.0), (date(2024, 1, 3), 3.0)], source="t")
        assert rates.average_annual_rate(date(2024, 1, 2), date(2024, 1, 2)) == pytest.approx(0.05)

    def test_missing_values_are_skipped_not_zero(self) -> None:
        rates = RiskFreeRates([(date(2024, 1, 2), 5.0), (date(2024, 1, 3), None)], source="t")
        assert rates.average_annual_rate(date(2024, 1, 1), date(2024, 1, 5)) == pytest.approx(0.05)

    def test_an_empty_window_raises_instead_of_returning_zero(self) -> None:
        rates = RiskFreeRates([(date(2024, 1, 2), 5.0)], source="t")
        with pytest.raises(ValueError):
            rates.average_annual_rate(date(2023, 1, 1), date(2023, 12, 31))


class TestFromMacroRecords:
    def test_latest_vintage_wins_per_observation_date(self) -> None:
        records = [
            _record(date(2024, 1, 2), 5.0, date(2024, 1, 3)),
            _record(date(2024, 1, 2), 5.2, date(2024, 1, 10)),
            _record(date(2024, 1, 3), 4.0, date(2024, 1, 4)),
        ]
        rates = RiskFreeRates.from_macro_records(records, source="t")
        assert len(rates) == 2
        assert rates.average_annual_rate(date(2024, 1, 2), date(2024, 1, 2)) == pytest.approx(0.052)

    def test_a_withdrawn_latest_value_drops_the_date(self) -> None:
        records = [
            _record(date(2024, 1, 2), 5.0, date(2024, 1, 3)),
            _record(date(2024, 1, 2), None, date(2024, 1, 10)),
        ]
        assert len(RiskFreeRates.from_macro_records(records, source="t")) == 0
