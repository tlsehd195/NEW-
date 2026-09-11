"""LocalFileDataProvider: a `data_infra.provider.DataProvider`
implementation that reads pre-downloaded, already-normalized CSV files
from local disk instead of making a live network call (Phase 31,
instruction section 21).

Why this exists
----------------
Every real provider integrated so far (`TiingoDataProvider`,
`StooqDataProvider`) requires live network access from *this*
process. Phase 26-30 repeatedly confirmed that this sandboxed
session's network egress is blocked to every market-data provider host
tried -- but a user with their own external network access (a
Codespaces environment, their own machine, an institutional dataset
subscription such as CRSP or Nasdaq Data Link/Sharadar) can acquire
real data there and needs a way to bring it into this repository's
validated pipeline (`IngestionRunner` -> `DataQualityFramework` ->
`DuckDBDataRepository`) without this process ever touching the
network itself, and without any API key ever entering this repository
or this conversation (instruction section 13/21).

This module intentionally does NOT parse any specific external
provider's actual bulk-file format (a CRSP or Nasdaq Data Link export,
for instance) -- this project has never seen a real sample of one, and
guessing a schema it has never verified would violate this project's
own "never fabricate provider capabilities" discipline (instruction
section 2.1). Instead it defines and documents ONE simple, explicit
CSV schema (see `_REQUIRED_COLUMNS` below) that the user's own external
preprocessing step is responsible for producing from whatever raw
format their acquired dataset actually uses. That preprocessing step
is out of scope for this repository (it depends entirely on which
external source the user chooses -- see
`docs/decisions/ADR-0034-real-data-acquisition-strategy.md`).

External acquisition workflow (instruction section 21):

    external environment (user's own network access)
        -> provider/dataset acquisition (Tiingo, Nasdaq Data Link, CRSP, ...)
        -> user's own preprocessing into this module's CSV schema
        -> one CSV file per security_id, placed in a local directory
        -> `scripts/import_external_market_data.py --data-dir ... --source-name ...`
        -> LocalFileDataProvider (this module) + IngestionRunner (Phase 1, unmodified)
        -> DataQualityFramework validation (Phase 1/20, unmodified)
        -> DuckDBDataRepository / Parquet storage (Phase 4, unmodified)
        -> historical universe / Walk-Forward (Phase 24-30, unmodified)

No API key is ever read by this module -- it never makes a network
call, so there is nothing to authenticate.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from data_infra.models import PriceBar, Provenance
from data_infra.provider import PermanentProviderError, bar_available_time, clamp_ingestion_time
from data_infra.versioning import compute_data_version

# The one CSV schema this module understands. A file not matching this
# is a `PermanentProviderError`, never a silent partial read -- instruction
# section 2.1's "never fabricate/repair" discipline applies to shape
# mismatches exactly as it does to values.
_REQUIRED_COLUMNS = ("date", "open", "high", "low", "close", "volume")
_OPTIONAL_COLUMNS = ("adj_close", "adj_high", "adj_low")


@dataclass(frozen=True)
class FileImportConfig:
    """`source_name` must describe the ACTUAL external source the user
    acquired this data from (e.g. "nasdaq_data_link_sharadar", "crsp",
    "tiingo_manual_export") -- never a guess, never left as a generic
    default, since it becomes `Provenance.source` and downstream REAL-data
    provenance checks (`run_long_horizon_validation.py`'s
    `_KNOWN_REAL_PROVIDER_SOURCES`, Phase 28) key off of exactly this
    string. A caller who cannot honestly name their source should not
    claim `--data-status REAL` for the result."""

    source_name: str
    data_dir: Path
    configuration_version_label: str = "v1"

    def __post_init__(self) -> None:
        if not self.source_name:
            raise ValueError("FileImportConfig.source_name must not be empty")

    def configuration_version(self) -> str:
        return f"file_import:{self.source_name}:{self.configuration_version_label}"


class LocalFileDataProvider:
    """Implements `data_infra.provider.DataProvider` by reading one CSV
    file per security_id from `config.data_dir` -- never a network call.
    File layout: `{data_dir}/{security_id}.csv`, columns
    `date,open,high,low,close,volume` (required) and `adj_close`
    (optional). `date` must be `YYYY-MM-DD`."""

    def __init__(self, config: FileImportConfig) -> None:
        self._config = config

    def _path_for(self, security_id: str) -> Path:
        return self._config.data_dir / f"{security_id}.csv"

    # -- DataProvider Protocol --------------------------------------

    def fetch(self, security_id: str, start: datetime, end: datetime) -> list[dict]:
        path = self._path_for(security_id)
        if not path.is_file():
            raise PermanentProviderError(
                f"no local file for security_id={security_id!r} at {path} "
                f"(LocalFileDataProvider requires one pre-populated CSV per symbol -- "
                f"see data_infra.providers.file_import module docstring)"
            )
        rows: list[dict] = []
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            missing_columns = set(_REQUIRED_COLUMNS) - set(reader.fieldnames or ())
            if missing_columns:
                raise PermanentProviderError(
                    f"{path} is missing required column(s) {sorted(missing_columns)} "
                    f"-- expected {_REQUIRED_COLUMNS}, found {reader.fieldnames}"
                )
            for row in reader:
                row_date = datetime.strptime(row["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                if row_date < start or row_date > end:
                    continue
                record = dict(row, security_id=security_id, _fetched_as_of=end)
                rows.append(record)
        return rows

    def validate(self, raw_records: Sequence[dict]) -> list[str]:
        issues: list[str] = []
        for i, record in enumerate(raw_records):
            missing = [f for f in _REQUIRED_COLUMNS if f not in record or record[f] in (None, "")]
            if missing:
                issues.append(f"record[{i}] missing/empty fields: {missing}")
        return issues

    def normalize(self, security_id: str, raw_records: Sequence[dict]) -> list[PriceBar]:
        bars: list[PriceBar] = []
        for record in raw_records:
            timestamp = datetime.strptime(record["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            as_of = record["_fetched_as_of"]
            content_fields = {k: v for k, v in record.items() if k not in ("_fetched_as_of", "security_id")}
            adj_close_raw = record.get("adj_close")
            adj_high_raw = record.get("adj_high")
            adj_low_raw = record.get("adj_low")
            provenance = Provenance(
                source=self._config.source_name,
                source_dataset=f"{self._config.source_name}_{security_id}",
                source_record_id=f"{security_id}:{record['date']}",
                retrieved_at=as_of,
                data_version=compute_data_version(content_fields),
            )
            bars.append(
                PriceBar(
                    security_id=security_id,
                    timestamp=timestamp,
                    open=float(record["open"]),
                    high=float(record["high"]),
                    low=float(record["low"]),
                    close=float(record["close"]),
                    volume=float(record["volume"]),
                    # Session 36 continued (external review remediation):
                    # see `data_infra.provider.bar_available_time`'s own
                    # docstring -- matches the identical fix in tiingo.py.
                    available_time=bar_available_time(timestamp),
                    # Session 37 (ADR-0115, external review N-3): clamped
                    # -- see `data_infra.provider.clamp_ingestion_time`'s
                    # own docstring for why the batch-level `as_of` can
                    # otherwise fall before this bar's own available_time
                    # for a month-end/current-day bar (100% reproducible
                    # for a local CSV import, whose `_fetched_as_of` is
                    # the caller's own `end` date, unmodified).
                    ingestion_time=clamp_ingestion_time(as_of, bar_available_time(timestamp)),
                    provenance=provenance,
                    adjusted_close=float(adj_close_raw) if adj_close_raw not in (None, "") else None,
                    adjusted_high=float(adj_high_raw) if adj_high_raw not in (None, "") else None,
                    adjusted_low=float(adj_low_raw) if adj_low_raw not in (None, "") else None,
                    currency="USD",
                )
            )
        return bars

    def metadata(self) -> dict:
        return {
            "provider_id": f"file_import:{self._config.source_name}",
            "provider_name": self._config.source_name,
            "rate_limit_per_minute": None,  # N/A -- local file, no network call
            "is_real_external_provider": True,
            "is_local_file_import": True,
            "configuration_version": self._config.configuration_version(),
        }
