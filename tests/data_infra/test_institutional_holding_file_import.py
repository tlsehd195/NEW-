"""Category: `data_infra.providers.institutional_holding_file_import`
-- the project-owned, local-CSV normalization for aggregate SEC Form
13F institutional holdings data (Session 36 continued, ADR-0104).
Mirrors `test_short_interest_file_import.py`'s own pattern, applied to
`InstitutionalHoldingRecord` output instead of `ShortInterestRecord`."""

from __future__ import annotations

from helpers import utc

import pytest

from data_infra.institutional_holding_models import thirteen_f_available_time
from data_infra.provider import PermanentProviderError
from data_infra.providers.institutional_holding_file_import import (
    InstitutionalHoldingFileImportConfig,
    load_institutional_holdings_csv,
    load_institutional_holdings_csvs,
)


def _write_csv(tmp_path, security_id: str, rows: list[str]) -> None:
    header = "quarter_end,institutional_shares,num_institutions\n"
    (tmp_path / f"{security_id}.csv").write_text(header + "\n".join(rows) + "\n")


class TestLoadInstitutionalHoldingsCsv:
    def test_parses_a_well_formed_row(self, tmp_path) -> None:
        _write_csv(tmp_path, "AAA", ["2026-06-30,1000000,42"])
        config = InstitutionalHoldingFileImportConfig(source_name="sec_13f_manual_aggregation", data_dir=tmp_path)

        records = load_institutional_holdings_csv(config, "AAA", retrieved_at=utc(2026, 9, 3))

        assert len(records) == 1
        record = records[0]
        assert record.security_id == "AAA"
        assert record.quarter_end == utc(2026, 6, 30)
        assert record.institutional_shares == 1000000.0
        assert record.num_institutions == 42
        assert record.provenance.source == "sec_13f_manual_aggregation"

    def test_available_time_is_the_filing_deadline_never_the_quarter_end(self, tmp_path) -> None:
        _write_csv(tmp_path, "AAA", ["2026-06-30,1000000,42"])
        config = InstitutionalHoldingFileImportConfig(source_name="sec_13f_manual_aggregation", data_dir=tmp_path)

        record = load_institutional_holdings_csv(config, "AAA", retrieved_at=utc(2026, 9, 3))[0]

        assert record.available_time == thirteen_f_available_time(utc(2026, 6, 30))
        assert record.available_time != record.quarter_end

    def test_optional_num_institutions_can_be_blank(self, tmp_path) -> None:
        _write_csv(tmp_path, "AAA", ["2026-06-30,1000000,"])
        config = InstitutionalHoldingFileImportConfig(source_name="sec_13f_manual_aggregation", data_dir=tmp_path)

        record = load_institutional_holdings_csv(config, "AAA", retrieved_at=utc(2026, 9, 3))[0]

        assert record.num_institutions is None

    def test_multiple_rows_produce_multiple_records(self, tmp_path) -> None:
        _write_csv(tmp_path, "AAA", ["2026-03-31,800000,40", "2026-06-30,1000000,42"])
        config = InstitutionalHoldingFileImportConfig(source_name="sec_13f_manual_aggregation", data_dir=tmp_path)

        records = load_institutional_holdings_csv(config, "AAA", retrieved_at=utc(2026, 9, 3))
        assert len(records) == 2

    def test_missing_file_raises_permanent_provider_error(self, tmp_path) -> None:
        config = InstitutionalHoldingFileImportConfig(source_name="sec_13f_manual_aggregation", data_dir=tmp_path)
        with pytest.raises(PermanentProviderError):
            load_institutional_holdings_csv(config, "NOPE", retrieved_at=utc(2026, 9, 3))

    def test_missing_required_column_raises_permanent_provider_error(self, tmp_path) -> None:
        (tmp_path / "AAA.csv").write_text("quarter_end,num_institutions\n2026-06-30,42\n")
        config = InstitutionalHoldingFileImportConfig(source_name="sec_13f_manual_aggregation", data_dir=tmp_path)
        with pytest.raises(PermanentProviderError):
            load_institutional_holdings_csv(config, "AAA", retrieved_at=utc(2026, 9, 3))

    def test_empty_source_name_rejected(self, tmp_path) -> None:
        with pytest.raises(ValueError):
            InstitutionalHoldingFileImportConfig(source_name="", data_dir=tmp_path)


class TestLoadInstitutionalHoldingsCsvsBatch:
    def test_loads_multiple_symbols(self, tmp_path) -> None:
        _write_csv(tmp_path, "AAA", ["2026-06-30,1000000,42"])
        _write_csv(tmp_path, "BBB", ["2026-06-30,2000000,60"])
        config = InstitutionalHoldingFileImportConfig(source_name="sec_13f_manual_aggregation", data_dir=tmp_path)

        result = load_institutional_holdings_csvs(config, ["AAA", "BBB"], retrieved_at=utc(2026, 9, 3))

        assert set(result) == {"AAA", "BBB"}
        assert result["AAA"][0].institutional_shares == 1000000.0
        assert result["BBB"][0].institutional_shares == 2000000.0

    def test_a_missing_symbol_raises_rather_than_silently_skipping(self, tmp_path) -> None:
        _write_csv(tmp_path, "AAA", ["2026-06-30,1000000,42"])
        config = InstitutionalHoldingFileImportConfig(source_name="sec_13f_manual_aggregation", data_dir=tmp_path)

        with pytest.raises(PermanentProviderError):
            load_institutional_holdings_csvs(config, ["AAA", "NOPE"], retrieved_at=utc(2026, 9, 3))
