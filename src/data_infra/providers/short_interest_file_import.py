"""Normalizes a user-supplied, pre-downloaded short-interest CSV file
into `data_infra.short_interest_models.ShortInterestRecord`s -- the
short-interest analogue of `data_infra.providers.file_import.
LocalFileDataProvider`, built for the identical reason (see that
module's own docstring, and `short_interest_models`'s module docstring):
this sandboxed session cannot reach `finra.org` to observe FINRA's own
real bulk short-interest file format, so this module defines and
documents ONE simple, explicit, project-owned CSV schema instead of
guessing FINRA's actual layout.

External acquisition workflow (mirrors `file_import.py`'s own):

    external environment (user's own network access, reaches finra.org)
        -> FINRA Equity Short Interest file/API download
        -> user's own preprocessing into this module's CSV schema
        -> one CSV file per security_id, placed in a local directory
           (`--data-dir`), OR one combined multi-symbol CSV
           (`--combined-csv`, `load_combined_short_interest_csv` below)
        -> `scripts/ingest_short_interest_data.py`
        -> this module -> DuckDBShortInterestRepository
        -> short_interest_score (strategy_research.factor_scores)

No network call is ever made by this module or the CLI that uses it."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from data_infra.models import Provenance
from data_infra.provider import PermanentProviderError
from data_infra.short_interest_models import ShortInterestRecord, dissemination_available_time
from data_infra.versioning import compute_data_version

# The one CSV schema this module understands, one file per security_id
# (`{data_dir}/{security_id}.csv`), mirroring LocalFileDataProvider's own
# `date,open,high,low,close,volume` convention. `settlement_date` is
# `YYYY-MM-DD`; `average_daily_volume`/`days_to_cover` are optional
# (FINRA's own real file may omit either for a thinly-traded name).
_REQUIRED_COLUMNS = ("settlement_date", "short_interest_quantity")
_OPTIONAL_COLUMNS = ("average_daily_volume", "days_to_cover")

# The combined, one-file-for-every-symbol schema `load_combined_short_
# interest_csv` accepts -- the per-symbol columns above plus one extra
# `security_id` column, so a caller who already has the data as a
# single export does not need to manually split it into N files first.
_COMBINED_REQUIRED_COLUMNS = ("security_id",) + _REQUIRED_COLUMNS


@dataclass(frozen=True)
class ShortInterestFileImportConfig:
    """`source_name` must describe the ACTUAL external source/
    preprocessing the user applied (e.g. "finra_manual_export") --
    identical `Provenance.source` discipline `FileImportConfig.source_name`
    already documents, never a generic placeholder."""

    source_name: str
    data_dir: Path

    def __post_init__(self) -> None:
        if not self.source_name:
            raise ValueError("ShortInterestFileImportConfig.source_name must not be empty")


def _path_for(config: ShortInterestFileImportConfig, security_id: str) -> Path:
    return config.data_dir / f"{security_id}.csv"


def _row_to_record(
    security_id: str, row: dict, *, source_name: str, retrieved_at: datetime,
) -> ShortInterestRecord:
    """Shared row-parsing logic for both the per-symbol
    (`load_short_interest_csv`) and combined (`load_combined_short_
    interest_csv`) schemas -- identical field semantics either way,
    only where `security_id` comes from differs (the filename vs. a
    column in the row itself)."""
    settlement_date = datetime.strptime(row["settlement_date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    average_daily_volume_raw = row.get("average_daily_volume")
    days_to_cover_raw = row.get("days_to_cover")
    content_fields = {k: v for k, v in row.items()}
    provenance = Provenance(
        source=source_name,
        source_dataset=f"{source_name}_{security_id}",
        source_record_id=f"{security_id}:{row['settlement_date']}",
        retrieved_at=retrieved_at,
        data_version=compute_data_version(content_fields),
    )
    return ShortInterestRecord(
        security_id=security_id,
        settlement_date=settlement_date,
        short_interest_quantity=float(row["short_interest_quantity"]),
        average_daily_volume=float(average_daily_volume_raw) if average_daily_volume_raw not in (None, "") else None,
        days_to_cover=float(days_to_cover_raw) if days_to_cover_raw not in (None, "") else None,
        available_time=dissemination_available_time(settlement_date),
        ingestion_time=retrieved_at,
        provenance=provenance,
    )


def load_short_interest_csv(
    config: ShortInterestFileImportConfig, security_id: str, *, retrieved_at: datetime,
) -> list[ShortInterestRecord]:
    """Reads and normalizes `{data_dir}/{security_id}.csv` into
    `ShortInterestRecord`s. `available_time` is ALWAYS derived via
    `dissemination_available_time` from each row's own `settlement_date`
    -- never read from the CSV, and never equal to `settlement_date`
    itself (see `short_interest_models` module docstring for why)."""
    path = _path_for(config, security_id)
    if not path.is_file():
        raise PermanentProviderError(
            f"no local file for security_id={security_id!r} at {path} "
            f"(this module requires one pre-populated CSV per symbol -- "
            f"see data_infra.providers.short_interest_file_import module docstring)"
        )
    records: list[ShortInterestRecord] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing_columns = set(_REQUIRED_COLUMNS) - set(reader.fieldnames or ())
        if missing_columns:
            raise PermanentProviderError(
                f"{path} is missing required column(s) {sorted(missing_columns)} "
                f"-- expected at least {_REQUIRED_COLUMNS}, found {reader.fieldnames}"
            )
        for row in reader:
            records.append(_row_to_record(security_id, row, source_name=config.source_name, retrieved_at=retrieved_at))
    return records


def load_combined_short_interest_csv(
    csv_path: Path, *, source_name: str, retrieved_at: datetime,
) -> dict[str, list[ShortInterestRecord]]:
    """Reads ONE CSV covering multiple symbols (`security_id,
    settlement_date,short_interest_quantity[,average_daily_volume]
    [,days_to_cover]`) and groups the resulting `ShortInterestRecord`s
    by `security_id` -- the one-file convenience counterpart to
    `load_short_interest_csv`'s one-file-per-symbol contract, for a
    caller who already has FINRA data as a single combined export
    (e.g. a whole settlement date's report across many symbols) and
    would otherwise need to manually split it into N per-symbol files
    first. Uses the identical row semantics (`_row_to_record`) -- this
    is purely a different INPUT SHAPE, not a different schema."""
    if not csv_path.is_file():
        raise PermanentProviderError(
            f"no combined CSV found at {csv_path} "
            f"(see data_infra.providers.short_interest_file_import module docstring)"
        )
    records_by_symbol: dict[str, list[ShortInterestRecord]] = {}
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing_columns = set(_COMBINED_REQUIRED_COLUMNS) - set(reader.fieldnames or ())
        if missing_columns:
            raise PermanentProviderError(
                f"{csv_path} is missing required column(s) {sorted(missing_columns)} "
                f"-- expected at least {_COMBINED_REQUIRED_COLUMNS}, found {reader.fieldnames}"
            )
        for row in reader:
            security_id = row["security_id"].strip()
            if not security_id:
                raise PermanentProviderError(f"{csv_path} has a row with an empty security_id")
            record = _row_to_record(security_id, row, source_name=source_name, retrieved_at=retrieved_at)
            records_by_symbol.setdefault(security_id, []).append(record)
    return records_by_symbol


def load_short_interest_csvs(
    config: ShortInterestFileImportConfig, security_ids: Sequence[str], *, retrieved_at: datetime,
) -> dict[str, list[ShortInterestRecord]]:
    """Convenience batch wrapper -- a security_id with no local CSV
    raises the same `PermanentProviderError` `load_short_interest_csv`
    would, not silently skipped (a missing file for a requested symbol
    is a real, reportable gap, not an empty-but-valid result)."""
    return {security_id: load_short_interest_csv(config, security_id, retrieved_at=retrieved_at) for security_id in security_ids}
