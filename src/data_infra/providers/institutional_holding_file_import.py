"""Normalizes a user-supplied, pre-aggregated institutional-holdings CSV
file into `data_infra.institutional_holding_models.
InstitutionalHoldingRecord`s -- the institutional-holdings analogue of
`data_infra.providers.short_interest_file_import`, built for the
identical reason (see that module's own docstring, and
`institutional_holding_models`'s module docstring): this sandboxed
session cannot reach `sec.gov` (confirmed blocked for both
`www.sec.gov` and `data.sec.gov` this session) to observe SEC's own
real Form 13F structured data set, and even with access, that data set
is keyed by CUSIP -- a security identifier this project has never
carried on `SecurityMaster` -- while this project's own CUSIP-to-
`security_id` mapping does not exist and cannot be guessed. This module
defines and documents ONE simple, explicit, project-owned CSV schema
instead of guessing SEC's actual per-filer layout or a CUSIP mapping.

External acquisition workflow (mirrors `short_interest_file_import.py`'s
own):

    external environment (user's own network access, reaches sec.gov)
        -> SEC Form 13F structured data set (quarterly ZIP, INFOTABLE)
        -> user's own preprocessing: resolve each of their own universe
           securities' CUSIP, sum SSHPRNAMT across every 13F filer
           reporting a position in that CUSIP that quarter
        -> one row per quarter per security_id, in this module's schema
        -> one CSV file per security_id, placed in a local directory
        -> `scripts/ingest_institutional_holdings.py --data-dir ...`
        -> this module -> DuckDBInstitutionalHoldingRepository
        -> institutional_ownership_change_score
           (strategy_research.factor_scores)

No network call is ever made by this module or the CLI that uses it."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from data_infra.institutional_holding_models import InstitutionalHoldingRecord, thirteen_f_available_time
from data_infra.models import Provenance
from data_infra.provider import PermanentProviderError
from data_infra.versioning import compute_data_version

# The one CSV schema this module understands, one file per security_id
# (`{data_dir}/{security_id}.csv`), mirroring short_interest_file_
# import.py's own convention. `quarter_end` is `YYYY-MM-DD` (the last
# calendar day of the 13F reporting quarter, e.g. 2024-12-31);
# `num_institutions` is optional (the account owner's own preprocessing
# may or may not have counted distinct filers).
_REQUIRED_COLUMNS = ("quarter_end", "institutional_shares")
_OPTIONAL_COLUMNS = ("num_institutions",)


@dataclass(frozen=True)
class InstitutionalHoldingFileImportConfig:
    """`source_name` must describe the ACTUAL external source/
    preprocessing the user applied (e.g. "sec_13f_manual_aggregation")
    -- identical `Provenance.source` discipline
    `ShortInterestFileImportConfig.source_name` already documents, never
    a generic placeholder."""

    source_name: str
    data_dir: Path

    def __post_init__(self) -> None:
        if not self.source_name:
            raise ValueError("InstitutionalHoldingFileImportConfig.source_name must not be empty")


def _path_for(config: InstitutionalHoldingFileImportConfig, security_id: str) -> Path:
    return config.data_dir / f"{security_id}.csv"


def load_institutional_holdings_csv(
    config: InstitutionalHoldingFileImportConfig, security_id: str, *, retrieved_at: datetime,
) -> list[InstitutionalHoldingRecord]:
    """Reads and normalizes `{data_dir}/{security_id}.csv` into
    `InstitutionalHoldingRecord`s. `available_time` is ALWAYS derived
    via `thirteen_f_available_time` from each row's own `quarter_end` --
    never read from the CSV, and never equal to `quarter_end` itself
    (see `institutional_holding_models` module docstring for why)."""
    path = _path_for(config, security_id)
    if not path.is_file():
        raise PermanentProviderError(
            f"no local file for security_id={security_id!r} at {path} "
            f"(this module requires one pre-populated CSV per symbol -- "
            f"see data_infra.providers.institutional_holding_file_import module docstring)"
        )
    records: list[InstitutionalHoldingRecord] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing_columns = set(_REQUIRED_COLUMNS) - set(reader.fieldnames or ())
        if missing_columns:
            raise PermanentProviderError(
                f"{path} is missing required column(s) {sorted(missing_columns)} "
                f"-- expected at least {_REQUIRED_COLUMNS}, found {reader.fieldnames}"
            )
        for row in reader:
            quarter_end = datetime.strptime(row["quarter_end"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            num_institutions_raw = row.get("num_institutions")
            content_fields = {k: v for k, v in row.items()}
            provenance = Provenance(
                source=config.source_name,
                source_dataset=f"{config.source_name}_{security_id}",
                source_record_id=f"{security_id}:{row['quarter_end']}",
                retrieved_at=retrieved_at,
                data_version=compute_data_version(content_fields),
            )
            records.append(
                InstitutionalHoldingRecord(
                    security_id=security_id,
                    quarter_end=quarter_end,
                    institutional_shares=float(row["institutional_shares"]),
                    num_institutions=int(num_institutions_raw) if num_institutions_raw not in (None, "") else None,
                    available_time=thirteen_f_available_time(quarter_end),
                    ingestion_time=retrieved_at,
                    provenance=provenance,
                )
            )
    return records


def load_institutional_holdings_csvs(
    config: InstitutionalHoldingFileImportConfig, security_ids: Sequence[str], *, retrieved_at: datetime,
) -> dict[str, list[InstitutionalHoldingRecord]]:
    """Convenience batch wrapper -- a security_id with no local CSV
    raises the same `PermanentProviderError` `load_institutional_holdings_csv`
    would, not silently skipped (a missing file for a requested symbol
    is a real, reportable gap, not an empty-but-valid result)."""
    return {
        security_id: load_institutional_holdings_csv(config, security_id, retrieved_at=retrieved_at)
        for security_id in security_ids
    }
