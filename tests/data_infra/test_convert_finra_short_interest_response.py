"""Real, executable tests for `scripts/convert_finra_short_interest_
response.py` (Session 37, ADR-0125).

This script makes NO network call -- it only transforms JSON response
files already saved locally -- so it is safe to run `main()` here end
to end, against fixture files shaped like the REAL FINRA
EquityShortInterest API response the account owner fetched this
session (field names/shapes are not invented; see that ADR for the
verification)."""

from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "convert_finra_short_interest_response.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("convert_finra_short_interest_response", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _real_shaped_record(**overrides) -> dict:
    """One record shaped exactly like the real FINRA API response this
    project verified this session -- every field the real payload
    carries, not a guessed subset."""
    record = {
        "issueSymbolIdentifier": "AAALF",
        "issueName": "Aareal Bank AG AKT",
        "marketCategoryDescription": "Other OTC",
        "marketCategoryCode": "u",
        "changePercent": 20.07,
        "currentShortShareNumber": 131471,
        "daysToCoverNumber": 999.99,
        "settlementDate": "2018-09-14",
        "previousShortShareNumber": 109497,
        "averageShortShareNumber": 0,
        "percentageChangefromPreviousShort": 21974,
    }
    record.update(overrides)
    return record


def _read_csv_rows(path: Path) -> list[dict]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


class TestConvertFinraShortInterestResponse:
    def test_maps_real_fields_to_the_combined_csv_schema(self, tmp_path) -> None:
        module = _load_script()
        input_path = tmp_path / "response.json"
        input_path.write_text(json.dumps([_real_shaped_record()]))
        out_path = tmp_path / "combined.csv"

        exit_code = module.main([str(input_path), "--out", str(out_path)])
        assert exit_code == 0

        rows = _read_csv_rows(out_path)
        assert len(rows) == 1
        assert rows[0]["security_id"] == "AAALF"
        assert rows[0]["settlement_date"] == "2018-09-14"
        assert rows[0]["short_interest_quantity"] == "131471"

    def test_finra_undefined_sentinel_999_99_becomes_blank_not_a_literal_number(self, tmp_path) -> None:
        module = _load_script()
        input_path = tmp_path / "response.json"
        input_path.write_text(json.dumps([_real_shaped_record(daysToCoverNumber=999.99)]))
        out_path = tmp_path / "combined.csv"

        module.main([str(input_path), "--out", str(out_path)])

        rows = _read_csv_rows(out_path)
        assert rows[0]["days_to_cover"] == ""

    def test_a_real_non_sentinel_days_to_cover_value_is_preserved(self, tmp_path) -> None:
        module = _load_script()
        input_path = tmp_path / "response.json"
        input_path.write_text(json.dumps([_real_shaped_record(daysToCoverNumber=1)]))
        out_path = tmp_path / "combined.csv"

        module.main([str(input_path), "--out", str(out_path)])

        rows = _read_csv_rows(out_path)
        assert rows[0]["days_to_cover"] == "1"

    def test_average_daily_volume_is_always_blank_never_averageShortShareNumber(self, tmp_path) -> None:
        """averageShortShareNumber is a different concept (average SHORT
        position, not average TRADING volume) -- this script must never
        silently relabel it as average_daily_volume."""
        module = _load_script()
        input_path = tmp_path / "response.json"
        input_path.write_text(json.dumps([_real_shaped_record(averageShortShareNumber=999999)]))
        out_path = tmp_path / "combined.csv"

        module.main([str(input_path), "--out", str(out_path)])

        rows = _read_csv_rows(out_path)
        assert rows[0]["average_daily_volume"] == ""

    def test_multiple_input_files_are_concatenated(self, tmp_path) -> None:
        module = _load_script()
        input1 = tmp_path / "response1.json"
        input1.write_text(json.dumps([_real_shaped_record(issueSymbolIdentifier="AAALF")]))
        input2 = tmp_path / "response2.json"
        input2.write_text(json.dumps([_real_shaped_record(issueSymbolIdentifier="AACAF")]))
        out_path = tmp_path / "combined.csv"

        exit_code = module.main([str(input1), str(input2), "--out", str(out_path)])
        assert exit_code == 0

        rows = _read_csv_rows(out_path)
        assert {r["security_id"] for r in rows} == {"AAALF", "AACAF"}

    def test_multiple_records_in_one_file_all_convert(self, tmp_path) -> None:
        module = _load_script()
        input_path = tmp_path / "response.json"
        input_path.write_text(
            json.dumps(
                [
                    _real_shaped_record(issueSymbolIdentifier="AAALF"),
                    _real_shaped_record(issueSymbolIdentifier="AACAF"),
                    _real_shaped_record(issueSymbolIdentifier="AACAY", daysToCoverNumber=1),
                ]
            )
        )
        out_path = tmp_path / "combined.csv"

        module.main([str(input_path), "--out", str(out_path)])

        rows = _read_csv_rows(out_path)
        assert len(rows) == 3

    def test_missing_input_file_fails_with_nonzero_exit(self, tmp_path) -> None:
        module = _load_script()
        exit_code = module.main([str(tmp_path / "nope.json"), "--out", str(tmp_path / "combined.csv")])
        assert exit_code == 1

    def test_non_array_json_fails_with_nonzero_exit(self, tmp_path) -> None:
        module = _load_script()
        input_path = tmp_path / "response.json"
        input_path.write_text(json.dumps({"not": "an array"}))
        exit_code = module.main([str(input_path), "--out", str(tmp_path / "combined.csv")])
        assert exit_code == 1

    def test_record_missing_a_required_field_fails_with_nonzero_exit(self, tmp_path) -> None:
        module = _load_script()
        input_path = tmp_path / "response.json"
        bad_record = _real_shaped_record()
        del bad_record["settlementDate"]
        input_path.write_text(json.dumps([bad_record]))
        exit_code = module.main([str(input_path), "--out", str(tmp_path / "combined.csv")])
        assert exit_code == 1

    def test_empty_array_fails_with_nonzero_exit(self, tmp_path) -> None:
        module = _load_script()
        input_path = tmp_path / "response.json"
        input_path.write_text(json.dumps([]))
        exit_code = module.main([str(input_path), "--out", str(tmp_path / "combined.csv")])
        assert exit_code == 1

    def test_output_is_directly_consumable_by_the_ingestion_cli(self, tmp_path) -> None:
        """End-to-end: convert a real-shaped response, then feed the
        result straight into ingest_short_interest_data.py's own
        --combined-csv mode (ADR-0124) -- proves the two scripts'
        schemas actually agree, not just that each one parses in
        isolation."""
        convert_module = _load_script()
        input_path = tmp_path / "response.json"
        input_path.write_text(json.dumps([_real_shaped_record(issueSymbolIdentifier="AAALF")]))
        combined_csv = tmp_path / "combined.csv"
        assert convert_module.main([str(input_path), "--out", str(combined_csv)]) == 0

        ingest_script_path = Path(__file__).resolve().parents[2] / "scripts" / "ingest_short_interest_data.py"
        spec = importlib.util.spec_from_file_location("ingest_short_interest_data", ingest_script_path)
        ingest_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ingest_module)

        db_path = tmp_path / "db"
        exit_code = ingest_module.main(
            [
                "--source-name", "finra_api",
                "--combined-csv", str(combined_csv),
                "--symbols", "AAALF",
                "--as-of", "2026-09-11",
                "--db-path", str(db_path),
            ]
        )
        assert exit_code == 0

    def test_no_network_module_is_imported_by_this_script(self) -> None:
        source = _SCRIPT_PATH.read_text()
        for forbidden in ("import requests", "urllib.request", "http.client"):
            assert forbidden not in source, f"{forbidden!r} must not appear in a script that claims to make no network call"
