# ADR-0124: Combined-CSV Mode for Short-Interest and Form 13F Import

**Status:** Accepted
**Date:** 2026-09-11
**Deciders:** Claude Code (documentation cleanup session, continued), pending project owner review
**Related documents:** `docs/decisions/ADR-0099-short-interest-factor.md`,
`docs/decisions/ADR-0104-institutional-ownership-change-factor.md`

---

## Context

The user ran `scripts/ingest_short_interest_data.py --data-dir
/path/to/preprocessed/csv/files ...` using the literal example path
from this session's own earlier instructions, and (correctly) got 87
"no local file" errors -- that path was always a placeholder, and this
project's `--data-dir` contract requires one pre-populated CSV file
**per symbol** (`{data_dir}/{security_id}.csv`). The user then asked
for this to "run in one shot" -- i.e., fewer manual steps between
acquiring real FINRA/SEC data and successfully ingesting it.

Fully automating the FINRA/SEC side (auto-download + auto-parse the
providers' own real bulk file formats) was deliberately not attempted:
this project's established discipline (`short_interest_file_import.py`/
`institutional_holding_file_import.py`'s own module docstrings) is to
never guess an external provider's real, unverified file layout --
this sandboxed session cannot reach `finra.org`/`sec.gov` to observe
either format directly, and guessing risks silently encoding a wrong
assumption as if verified. Building an automated FINRA/SEC downloader
would require exactly that guess.

What *is* safely automatable, without guessing anything about FINRA/SEC:
this project's own side of the contract -- the requirement that the
user manually split their data into N per-symbol files before running
either ingestion script. That split serves no purpose the ingestion
logic itself needs; it exists only because the original CSV schema was
designed one-file-per-symbol.

## Decision -- Add an alternative, one-file, multi-symbol CSV input mode

Added `load_combined_short_interest_csv`/`load_combined_institutional_
holdings_csv` to the respective provider modules, and a `--combined-csv`
CLI flag (mutually exclusive with the existing `--data-dir`) to both
`scripts/ingest_short_interest_data.py` and `scripts/ingest_
institutional_holdings.py`.

The combined schema is simply the existing per-symbol schema plus one
extra `security_id` column -- rows for every symbol live in one file,
grouped by `security_id` internally:

```
security_id,settlement_date,short_interest_quantity,average_daily_volume,days_to_cover
AAPL,2026-08-15,45000000,52000000,0.87
MSFT,2026-08-15,38000000,41000000,0.93
```

```
security_id,quarter_end,institutional_shares,num_institutions
AAPL,2026-06-30,5200000000,3800
```

This required no new invention of an external format -- it is a
schema this project already owns and controls, exactly like the
existing per-symbol one; only the input SHAPE differs (one file vs.
N files), not the row semantics, honesty discipline, or downstream
`ShortInterestRecord`/`InstitutionalHoldingRecord` output. Both
provider modules were refactored to share one `_row_to_record` helper
between the per-symbol and combined loaders, so there is exactly one
place that defines how a row becomes a record.

The two CLI scripts now require exactly one of `--data-dir`/
`--combined-csv` (validated explicitly, a clear `FATAL` message on
either zero or both). A symbol requested (via `--symbols` or
`--universe`) but absent from the combined file is reported as
`missing_symbols`, identically to the existing per-symbol-file
behavior -- no change to that reporting contract.

## Consequences

### Positive

- Reduces the user's manual preprocessing from "one file per symbol"
  (87 files for `RESEARCH_UNIVERSE`) to "one file, however you already
  have the data shaped" -- the actual bottleneck this ADR responds to.
- Zero risk of encoding an unverified guess about FINRA/SEC's real
  format -- this is purely this project's own, already-owned schema,
  restructured.
- Both CLI scripts remain network-free and fully exercised by the
  automated test suite (same discipline as before) -- neither the new
  code path nor the old one ever makes a network call.

### Negative / Trade-offs

- The user must still acquire the real FINRA/SEC data themselves and
  reshape it into this schema (with a `security_id` column) -- this
  ADR removes a mechanical splitting step, not the acquisition step
  itself, which remains genuinely `ENVIRONMENT_BLOCKED` in this
  sandbox and requires the user's own network access.

## Tests

18 new tests: 6 in `test_short_interest_file_import.py`
(`TestLoadCombinedShortInterestCsv`), 6 in `test_institutional_
holding_file_import.py` (`TestLoadCombinedInstitutionalHoldingsCsv`),
4 in `test_ingest_short_interest_data_cli.py`
(`TestIngestShortInterestDataCliCombinedCsv`, including both
missing-flag and both-flags-given rejection cases), 4 in
`test_ingest_institutional_holdings_cli.py`'s equivalent class.

## Status of Implementation at Time of This ADR

`load_combined_short_interest_csv` added to `src/data_infra/providers/
short_interest_file_import.py`; `load_combined_institutional_holdings_
csv` added to `src/data_infra/providers/institutional_holding_file_
import.py`. `--combined-csv` added to `scripts/ingest_short_interest_
data.py` and `scripts/ingest_institutional_holdings.py`. Both scripts'
existing `--data-dir` mode is completely unchanged.
