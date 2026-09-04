# ADR-0058: `fetch_sector_classifications.py` -- real SIC data collection CLI

**Status:** Accepted
**Session:** 36

## Context

Item ② of a user-selected set of post-screening next steps (alongside
ratifying the 3 proposed `LiveTradingConfig` risk limits, item ①, a
human decision this ADR does not make, and resuming the Learning Engine
track, a separate piece of work). ADR-0055 built `SecEdgarFundamentals
Provider.fetch_submissions`/`normalize_submissions` (real SEC EDGAR SIC
data) but deliberately stopped short of a CLI wrapper, since the
Tiingo-side equivalent (`fetch_symbol_metadata`/`normalize_symbol_
metadata`) had none either at the time. The user has now asked to
proceed with this piece of work.

## Decision

`scripts/fetch_sector_classifications.py` added, mirroring `ingest_
fundamentals_data.py`'s own structure almost exactly (ticker-map
resolution, the same `_KNOWN_CIK_OVERRIDES`/`--cik-overrides` pattern,
the same per-symbol resilience discipline -- `except (Transient
ProviderError, PermanentProviderError, ValueError)`, applied from the
start here rather than discovered the same way twice as it was for the
sibling script's own LMT bug).

**Deliberately does NOT write into `src/data_infra/universe.py`.**
Every `SymbolMetadata` entry there is a hand-curated Python literal
(Stage 1-4's consistent `source="manual_curation"` discipline) --
this script writes its real, provider-sourced findings to a JSON
report instead (`--out`). Applying the findings to `universe.py`
(setting each symbol's real `sector=` value) is left as a deliberate
manual follow-up step -- there is no established "apply this JSON to a
Python source literal" mechanism in this project, and building one for
a one-time application would be more machinery than the task needs.
This also means the script needs no `SymbolMetadata`/`UniverseDefinition`
import at all -- it only reads the two existing universe constants for
their symbol lists, never constructs a new definition.

Like every other real-provider script this project has built without
live network access in this environment, this is tested only via
source-text/AST inspection (`tests/data_infra/test_fetch_sector_
classifications_wiring.py`, 9 tests, mirroring `test_ingest_
fundamentals_data_wiring.py`'s structure) -- never imported, never
executed, matching the explicit discipline every sibling real-ingestion
script's own test file already states.

## Tests

9 new tests: syntax validity, no wall-clock reads, `--user-agent`
required with no silent default, the report never imports/constructs
`SymbolMetadata`/`UniverseDefinition`, the report's expected keys,
unresolved symbols never silently dropped, `--cik-overrides` +
`_KNOWN_CIK_OVERRIDES` (XOM) present, and the per-symbol loop's
`except` clause catches `ValueError` alongside the two provider errors.

Full suite: 2262 passed (up from 2253).

## What this does NOT do

- Does not run against the real network in this environment (no access
  here) -- real execution against Stage 4's 87 symbols is deferred to
  the user's own environment, same as every prior real-ingestion step.
- Does not apply any findings to `universe.py`'s `SymbolMetadata`
  entries -- that is a deliberate manual follow-up, not automated by
  this script or this ADR.
- Does not activate the sector-neutralization cap (`ADR-0055`'s
  `_select_target`) for any walk-forward candidate -- that still
  requires real sector data to exist first (this script's own output),
  then a separate decision about which candidate(s) and what
  `max_per_sector` value to use.
