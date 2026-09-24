"""Category: `data_infra.providers.institutional_filer_holding_file_
import` -- the per-filer counterpart to `test_institutional_holding_
file_import.py` (ADR-0194). Combined-CSV-only (see that module's own
docstring for why this schema has no per-symbol-file option)."""

from __future__ import annotations

from helpers import utc

import pytest

from data_infra.institutional_holding_models import thirteen_f_available_time
from data_infra.provider import PermanentProviderError
from data_infra.providers.institutional_filer_holding_file_import import (
    load_combined_institutional_filer_holdings_csv,
)


def _write_csv(tmp_path, rows: list[str], filename: str = "filer_combined.csv"):
    header = "security_id,filer_cik,quarter_end,shares_held\n"
    path = tmp_path / filename
    path.write_text(header + "\n".join(rows) + "\n")
    return path


class TestLoadCombinedInstitutionalFilerHoldingsCsv:
    def test_parses_a_well_formed_row(self, tmp_path) -> None:
        path = _write_csv(tmp_path, ["AAA,0001067983,2026-06-30,500000"])

        result = load_combined_institutional_filer_holdings_csv(
            path, source_name="sec_13f_tracked_filer_positions", retrieved_at=utc(2026, 9, 3)
        )

        assert set(result) == {"AAA"}
        record = result["AAA"][0]
        assert record.security_id == "AAA"
        assert record.filer_cik == "0001067983"
        assert record.quarter_end == utc(2026, 6, 30)
        assert record.shares_held == 500000.0
        assert record.provenance.source == "sec_13f_tracked_filer_positions"

    def test_available_time_is_the_filing_deadline_never_the_quarter_end(self, tmp_path) -> None:
        path = _write_csv(tmp_path, ["AAA,0001067983,2026-06-30,500000"])

        record = load_combined_institutional_filer_holdings_csv(
            path, source_name="sec_13f_tracked_filer_positions", retrieved_at=utc(2026, 9, 3)
        )["AAA"][0]

        assert record.available_time == thirteen_f_available_time(utc(2026, 6, 30))
        assert record.available_time != record.quarter_end

    def test_multiple_filers_for_the_same_security_and_quarter_are_grouped_together(self, tmp_path) -> None:
        path = _write_csv(
            tmp_path,
            [
                "AAA,0001067983,2026-06-30,500000",
                "AAA,0001336528,2026-06-30,120000",
            ],
        )

        result = load_combined_institutional_filer_holdings_csv(
            path, source_name="sec_13f_tracked_filer_positions", retrieved_at=utc(2026, 9, 3)
        )

        assert len(result["AAA"]) == 2
        assert {r.filer_cik for r in result["AAA"]} == {"0001067983", "0001336528"}

    def test_groups_multiple_symbols_from_one_file(self, tmp_path) -> None:
        path = _write_csv(
            tmp_path,
            ["AAA,0001067983,2026-06-30,500000", "BBB,0001067983,2026-06-30,300000"],
        )

        result = load_combined_institutional_filer_holdings_csv(
            path, source_name="sec_13f_tracked_filer_positions", retrieved_at=utc(2026, 9, 3)
        )

        assert set(result) == {"AAA", "BBB"}

    def test_missing_file_raises_permanent_provider_error(self, tmp_path) -> None:
        with pytest.raises(PermanentProviderError):
            load_combined_institutional_filer_holdings_csv(
                tmp_path / "nope.csv", source_name="sec_13f_tracked_filer_positions", retrieved_at=utc(2026, 9, 3)
            )

    def test_missing_required_column_raises_permanent_provider_error(self, tmp_path) -> None:
        path = tmp_path / "bad.csv"
        path.write_text("security_id,quarter_end,shares_held\nAAA,2026-06-30,500000\n")
        with pytest.raises(PermanentProviderError):
            load_combined_institutional_filer_holdings_csv(
                path, source_name="sec_13f_tracked_filer_positions", retrieved_at=utc(2026, 9, 3)
            )

    def test_empty_security_id_value_raises_permanent_provider_error(self, tmp_path) -> None:
        path = _write_csv(tmp_path, [",0001067983,2026-06-30,500000"])
        with pytest.raises(PermanentProviderError):
            load_combined_institutional_filer_holdings_csv(
                path, source_name="sec_13f_tracked_filer_positions", retrieved_at=utc(2026, 9, 3)
            )

    def test_empty_filer_cik_value_raises_permanent_provider_error(self, tmp_path) -> None:
        path = _write_csv(tmp_path, ["AAA,,2026-06-30,500000"])
        with pytest.raises(PermanentProviderError):
            load_combined_institutional_filer_holdings_csv(
                path, source_name="sec_13f_tracked_filer_positions", retrieved_at=utc(2026, 9, 3)
            )
