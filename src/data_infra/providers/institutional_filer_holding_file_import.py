"""Normalizes a user-supplied, per-filer institutional-holdings CSV file
into `data_infra.institutional_holding_models.
InstitutionalFilerHoldingRecord`s -- the per-filer counterpart to
`institutional_holding_file_import.py` (which produces the ALL-filers-
aggregated `InstitutionalHoldingRecord`; see that module's own docstring
for why this project defines its own explicit schema here rather than
guessing SEC's real bulk INFOTABLE layout or a CUSIP mapping: the same
reasoning applies unchanged to this per-filer variant).

Deliberately COMBINED-CSV-ONLY, unlike `institutional_holding_file_
import.py`'s per-symbol-file option: this schema exists specifically
for `data_infra.tracked_institutional_filers` -- a small, curated,
named set of filers (four as of this module's introduction), each of
whom holds positions across many different securities. A single file
covering `security_id, filer_cik, quarter_end, shares_held` for every
tracked filer and every security in one place is the natural shape for
that (one export per quarter from whatever tool the user's own external
preprocessing uses), not one file per security_id.

External acquisition workflow (mirrors `institutional_holding_file_
import.py`'s own):

    external environment (user's own network access, reaches sec.gov)
        -> SEC Form 13F structured data set (quarterly ZIP, INFOTABLE),
           filtered down to ONLY the CIKs in
           data_infra.tracked_institutional_filers.TRACKED_FILERS
        -> user's own preprocessing: resolve each of their own universe
           securities' CUSIP, look up each tracked filer's reported
           SSHPRNAMT for that CUSIP that quarter (no cross-filer
           summing -- this is per-filer, not aggregate)
        -> one combined CSV (`security_id,filer_cik,quarter_end,shares_held`)
        -> scripts/ingest_institutional_holdings.py (--filer-combined-csv)
        -> this module -> DuckDBInstitutionalFilerHoldingRepository
        -> guru_consensus_score (strategy_research.factor_scores)

No network call is ever made by this module or the CLI that uses it."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from data_infra.institutional_holding_models import InstitutionalFilerHoldingRecord, thirteen_f_available_time
from data_infra.models import Provenance
from data_infra.provider import PermanentProviderError
from data_infra.versioning import compute_data_version

# security_id + filer_cik together identify one row (one filer's
# reported position in one security for one quarter) -- neither alone
# is unique across the file.
_REQUIRED_COLUMNS = ("security_id", "filer_cik", "quarter_end", "shares_held")


def load_combined_institutional_filer_holdings_csv(
    csv_path: Path, *, source_name: str, retrieved_at: datetime,
) -> dict[str, list[InstitutionalFilerHoldingRecord]]:
    """Reads ONE CSV covering multiple securities and multiple tracked
    filers (`security_id,filer_cik,quarter_end,shares_held`) and groups
    the resulting `InstitutionalFilerHoldingRecord`s by `security_id` --
    the per-filer analogue of `institutional_holding_file_import.
    load_combined_institutional_holdings_csv`. `available_time` is
    ALWAYS derived via `thirteen_f_available_time` from each row's own
    `quarter_end`, never read from the CSV (same look-ahead discipline
    as the aggregate module)."""
    if not csv_path.is_file():
        raise PermanentProviderError(
            f"no combined CSV found at {csv_path} "
            f"(see data_infra.providers.institutional_filer_holding_file_import module docstring)"
        )
    records_by_symbol: dict[str, list[InstitutionalFilerHoldingRecord]] = {}
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing_columns = set(_REQUIRED_COLUMNS) - set(reader.fieldnames or ())
        if missing_columns:
            raise PermanentProviderError(
                f"{csv_path} is missing required column(s) {sorted(missing_columns)} "
                f"-- expected at least {_REQUIRED_COLUMNS}, found {reader.fieldnames}"
            )
        for row in reader:
            security_id = row["security_id"].strip()
            filer_cik = row["filer_cik"].strip()
            if not security_id:
                raise PermanentProviderError(f"{csv_path} has a row with an empty security_id")
            if not filer_cik:
                raise PermanentProviderError(f"{csv_path} has a row with an empty filer_cik")
            quarter_end = datetime.strptime(row["quarter_end"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            content_fields = {k: v for k, v in row.items()}
            provenance = Provenance(
                source=source_name,
                source_dataset=f"{source_name}_{security_id}_{filer_cik}",
                source_record_id=f"{security_id}:{filer_cik}:{row['quarter_end']}",
                retrieved_at=retrieved_at,
                data_version=compute_data_version(content_fields),
            )
            record = InstitutionalFilerHoldingRecord(
                security_id=security_id,
                filer_cik=filer_cik,
                quarter_end=quarter_end,
                shares_held=float(row["shares_held"]),
                available_time=thirteen_f_available_time(quarter_end),
                ingestion_time=retrieved_at,
                provenance=provenance,
            )
            records_by_symbol.setdefault(security_id, []).append(record)
    return records_by_symbol
