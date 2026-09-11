"""Category: `data_infra.providers.short_interest_file_import` -- the
project-owned, local-CSV normalization for FINRA short interest data
(Session 36 continued, ADR-0099). Mirrors `test_file_import.py`'s own
pattern (if present) / `LocalFileDataProvider`'s own testing style,
applied to `ShortInterestRecord` output instead of `PriceBar`."""

from __future__ import annotations

from helpers import utc

import pytest

from data_infra.provider import PermanentProviderError
from data_infra.providers.short_interest_file_import import (
    ShortInterestFileImportConfig,
    load_combined_short_interest_csv,
    load_short_interest_csv,
    load_short_interest_csvs,
)
from data_infra.short_interest_models import dissemination_available_time


def _write_csv(tmp_path, security_id: str, rows: list[str]) -> None:
    header = "settlement_date,short_interest_quantity,average_daily_volume,days_to_cover\n"
    (tmp_path / f"{security_id}.csv").write_text(header + "\n".join(rows) + "\n")


class TestLoadShortInterestCsv:
    def test_parses_a_well_formed_row(self, tmp_path) -> None:
        _write_csv(tmp_path, "AAA", ["2026-08-15,100000,50000,2.0"])
        config = ShortInterestFileImportConfig(source_name="finra_manual_export", data_dir=tmp_path)

        records = load_short_interest_csv(config, "AAA", retrieved_at=utc(2026, 9, 3))

        assert len(records) == 1
        record = records[0]
        assert record.security_id == "AAA"
        assert record.settlement_date == utc(2026, 8, 15)
        assert record.short_interest_quantity == 100000.0
        assert record.average_daily_volume == 50000.0
        assert record.days_to_cover == 2.0
        assert record.provenance.source == "finra_manual_export"

    def test_available_time_is_the_dissemination_lag_never_the_settlement_date(self, tmp_path) -> None:
        _write_csv(tmp_path, "AAA", ["2026-08-15,100000,50000,2.0"])
        config = ShortInterestFileImportConfig(source_name="finra_manual_export", data_dir=tmp_path)

        record = load_short_interest_csv(config, "AAA", retrieved_at=utc(2026, 9, 3))[0]

        assert record.available_time == dissemination_available_time(utc(2026, 8, 15))
        assert record.available_time != record.settlement_date

    def test_optional_columns_can_be_blank(self, tmp_path) -> None:
        _write_csv(tmp_path, "AAA", ["2026-08-15,100000,,"])
        config = ShortInterestFileImportConfig(source_name="finra_manual_export", data_dir=tmp_path)

        record = load_short_interest_csv(config, "AAA", retrieved_at=utc(2026, 9, 3))[0]

        assert record.average_daily_volume is None
        assert record.days_to_cover is None

    def test_multiple_rows_produce_multiple_records(self, tmp_path) -> None:
        _write_csv(tmp_path, "AAA", ["2026-07-31,80000,40000,2.0", "2026-08-15,100000,50000,2.0"])
        config = ShortInterestFileImportConfig(source_name="finra_manual_export", data_dir=tmp_path)

        records = load_short_interest_csv(config, "AAA", retrieved_at=utc(2026, 9, 3))
        assert len(records) == 2

    def test_missing_file_raises_permanent_provider_error(self, tmp_path) -> None:
        config = ShortInterestFileImportConfig(source_name="finra_manual_export", data_dir=tmp_path)
        with pytest.raises(PermanentProviderError):
            load_short_interest_csv(config, "NOPE", retrieved_at=utc(2026, 9, 3))

    def test_missing_required_column_raises_permanent_provider_error(self, tmp_path) -> None:
        (tmp_path / "AAA.csv").write_text("settlement_date,average_daily_volume\n2026-08-15,50000\n")
        config = ShortInterestFileImportConfig(source_name="finra_manual_export", data_dir=tmp_path)
        with pytest.raises(PermanentProviderError):
            load_short_interest_csv(config, "AAA", retrieved_at=utc(2026, 9, 3))

    def test_empty_source_name_rejected(self, tmp_path) -> None:
        with pytest.raises(ValueError):
            ShortInterestFileImportConfig(source_name="", data_dir=tmp_path)


class TestLoadShortInterestCsvsBatch:
    def test_loads_multiple_symbols(self, tmp_path) -> None:
        _write_csv(tmp_path, "AAA", ["2026-08-15,100000,50000,2.0"])
        _write_csv(tmp_path, "BBB", ["2026-08-15,200000,100000,2.0"])
        config = ShortInterestFileImportConfig(source_name="finra_manual_export", data_dir=tmp_path)

        result = load_short_interest_csvs(config, ["AAA", "BBB"], retrieved_at=utc(2026, 9, 3))

        assert set(result) == {"AAA", "BBB"}
        assert result["AAA"][0].short_interest_quantity == 100000.0
        assert result["BBB"][0].short_interest_quantity == 200000.0

    def test_a_missing_symbol_raises_rather_than_silently_skipping(self, tmp_path) -> None:
        _write_csv(tmp_path, "AAA", ["2026-08-15,100000,50000,2.0"])
        config = ShortInterestFileImportConfig(source_name="finra_manual_export", data_dir=tmp_path)

        with pytest.raises(PermanentProviderError):
            load_short_interest_csvs(config, ["AAA", "NOPE"], retrieved_at=utc(2026, 9, 3))


class TestLoadCombinedShortInterestCsv:
    def _write_combined_csv(self, tmp_path, rows: list[str], filename: str = "combined.csv"):
        header = "security_id,settlement_date,short_interest_quantity,average_daily_volume,days_to_cover\n"
        path = tmp_path / filename
        path.write_text(header + "\n".join(rows) + "\n")
        return path

    def test_groups_multiple_symbols_from_one_file(self, tmp_path) -> None:
        path = self._write_combined_csv(
            tmp_path,
            ["AAA,2026-08-15,100000,50000,2.0", "BBB,2026-08-15,200000,100000,2.0"],
        )

        result = load_combined_short_interest_csv(path, source_name="finra_manual_export", retrieved_at=utc(2026, 9, 3))

        assert set(result) == {"AAA", "BBB"}
        assert result["AAA"][0].short_interest_quantity == 100000.0
        assert result["BBB"][0].short_interest_quantity == 200000.0
        assert result["AAA"][0].provenance.source == "finra_manual_export"

    def test_multiple_rows_for_the_same_symbol_are_grouped_together(self, tmp_path) -> None:
        path = self._write_combined_csv(
            tmp_path,
            ["AAA,2026-07-31,80000,40000,2.0", "AAA,2026-08-15,100000,50000,2.0"],
        )

        result = load_combined_short_interest_csv(path, source_name="finra_manual_export", retrieved_at=utc(2026, 9, 3))

        assert len(result["AAA"]) == 2

    def test_optional_columns_can_be_blank(self, tmp_path) -> None:
        path = self._write_combined_csv(tmp_path, ["AAA,2026-08-15,100000,,"])

        result = load_combined_short_interest_csv(path, source_name="finra_manual_export", retrieved_at=utc(2026, 9, 3))

        assert result["AAA"][0].average_daily_volume is None
        assert result["AAA"][0].days_to_cover is None

    def test_missing_file_raises_permanent_provider_error(self, tmp_path) -> None:
        with pytest.raises(PermanentProviderError):
            load_combined_short_interest_csv(tmp_path / "nope.csv", source_name="finra_manual_export", retrieved_at=utc(2026, 9, 3))

    def test_missing_security_id_column_raises_permanent_provider_error(self, tmp_path) -> None:
        path = tmp_path / "bad.csv"
        path.write_text("settlement_date,short_interest_quantity\n2026-08-15,100000\n")
        with pytest.raises(PermanentProviderError):
            load_combined_short_interest_csv(path, source_name="finra_manual_export", retrieved_at=utc(2026, 9, 3))

    def test_empty_security_id_value_raises_permanent_provider_error(self, tmp_path) -> None:
        path = self._write_combined_csv(tmp_path, [",2026-08-15,100000,,"])
        with pytest.raises(PermanentProviderError):
            load_combined_short_interest_csv(path, source_name="finra_manual_export", retrieved_at=utc(2026, 9, 3))
