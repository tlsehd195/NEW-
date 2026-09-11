# ADR-0003: Core Data Domain Model

**Status:** Accepted
**Date:** 2026-08-24
**Deciders:** Claude Code (Phase 1 session), pending project owner review
**Related documents:** `docs/specifications/PHASE-1-data-infrastructure.md`
§5-9, `src/data_infra/models.py`

---

## Context

`PROJECT_MASTER_PLAN.md` §7.1/§7.5 require: data metadata and a Feature
Registry separate from raw data (a Security Master rather than a bare
ticker is not itself in the master plan -- it comes from the Phase 1
initialization instruction, which additionally requires):
explicit `adjusted_close` semantics, a Security Master separating
`security_id/ticker/exchange/currency/company_id/instrument_type/
valid_from/valid_to/status`, and Corporate Action modeling with
`event_time/announcement_time/effective_time/available_time`. This ADR
records the concrete domain model shape and the reasoning behind key
choices, since these schemas will be depended on by every later phase
(Feature Engine, Backtest, Trade Journal, Learning).

## Decision

Adopt the following core domain types (implemented as type-hinted,
validating Python `dataclasses` in `src/data_infra/models.py`):

1. **`SecurityMaster`** — identity is `security_id` (a stable internal
   identifier), not a ticker. `ticker`, `exchange`, `currency`,
   `company_id`, `instrument_type` (enum; Phase 1 populates only
   `EQUITY`), `valid_from`/`valid_to` (half-open validity interval),
   and `status` (`ACTIVE|DELISTED|RENAMED|MERGED`) are separate fields.
   All time-series data (`PriceBar`, `CorporateAction`) references
   `security_id`.
2. **`PriceBar`** — OHLCV with the required/optional fields in Phase 1
   spec §5.1. `adjusted_close` is optional, stored alongside (never
   replacing) `close`, with its own `retrieved_at`/`data_version`,
   documented semantics in Phase 1 spec §5.2.
3. **`CorporateAction`** — one record per event, `action_type` (enum
   from Phase 1 spec §7), with `event_time`, `announcement_time`,
   `effective_time`, `available_time` as four distinct optional-where-
   inapplicable fields (e.g., some provider feeds may not carry
   `announcement_time` for older events — modeled as `Optional`, not
   backfilled with a guessed value).
4. **`BenchmarkPoint`** — a benchmark index level series, structurally
   similar to `PriceBar` but without an OHLC invariant (benchmark levels
   are typically a single value per period in Phase 1's mock scope, price
   or total return distinguished by an explicit `return_type` field
   documented per-dataset in the Data Catalog rather than assumed).
5. **`UniverseMembership`** — `(security_id, universe, valid_from,
   valid_to)`, supporting `get_universe(..., as_of_time=T)` (Phase 1 spec
   §8).
6. **Provenance/versioning fields** (`source`, `source_dataset`,
   `source_record_id`, `retrieved_at`, `data_version`, `schema_version`)
   are embedded as a shared `Provenance` value object composed into
   `PriceBar`, `CorporateAction`, `BenchmarkPoint` — not duplicated ad
   hoc per type — so provenance handling stays consistent across data
   kinds.
7. **Raw / Clean / Derived separation is structural, not just
   documentational**: Raw-layer storage keeps the originally-ingested
   payload keyed by `(source_record_id, retrieved_at)` (append-only);
   Clean-layer records are the normalized domain types above, keyed by
   `(security_id, timestamp, data_version)`; Derived-layer types are not
   defined in Phase 1 at all (deferred to the Feature Engine phase) so
   there is no way for Feature code to accidentally write into Clean/Raw.
8. **Data vs. Feature separation**: no Feature type exists in this
   phase's model. This is deliberate — Feature Engine (Phase 5+) will
   consume `PriceBar`/`CorporateAction`/etc. through `DataRepository`
   and produce its own, separately-versioned Feature records; it will
   never mutate a `PriceBar`.

## Alternatives Considered

- **Ticker as primary key for time series**: Rejected — cannot correctly
  represent ticker changes, mergers, or two different companies reusing
  a ticker over time (a documented real-world occurrence). `security_id`
  with a `SecurityMaster` validity interval is required to satisfy
  `PROJECT_MASTER_PLAN.md`'s Corporate Action / Security Master
  requirements (master plan §7.4, §7 of this spec).
- **Single `close` field, provider-adjusted only**: Rejected — would
  make historical backtests silently non-reproducible whenever the
  provider recomputes its adjustment factors, and would hide corporate
  action handling inside an opaque vendor number instead of the
  first-class, auditable `CorporateAction` model the master plan
  requires (`PROJECT_MASTER_PLAN.md` §7.4; this ADR's context).
- **Ad hoc per-type provenance fields** (duplicating `source`,
  `data_version`, etc. on every dataclass by hand): Rejected in favor of
  a shared `Provenance` composed value object, to avoid drift between
  types and to keep `DatasetVersion`/content-hash logic in one place
  (`PROJECT_MASTER_PLAN.md` §1.3 — avoid unnecessary duplication/
  complexity).
- **Defining Fundamental/Macro/News/Alternative data types now, even as
  empty stubs**: Rejected — no current design decision requires them
  (`PROJECT_MASTER_PLAN.md` §17.3), and stubbing unused types
  would add speculative complexity without validating anything.

## Consequences

### Positive

- Ticker changes, mergers, and delistings can be represented correctly
  from day one without a future data-model migration.
- Corporate-action-aware adjustment logic has a first-class, versioned
  source of truth (`CorporateAction`) instead of depending on an opaque
  provider-adjusted field.
- Every later phase (Feature, Backtest, Trade Journal, Learning) inherits
  a data model that already satisfies point-in-time and provenance
  requirements, avoiding a rewrite (`PROJECT_MASTER_PLAN.md` §1.2).

### Negative / Trade-offs

- Slightly more upfront modeling work than a flat "ticker + OHLCV" table
  would require. Accepted per `PROJECT_MASTER_PLAN.md` §1.3 — this
  complexity directly serves reproducibility/auditability, not
  speculative future features.
- `instrument_type` currently only supports `EQUITY`; extending to
  options/futures/ETFs (which have materially different corporate-action
  and pricing semantics) is deferred and will likely require schema
  additions — tracked as a known limitation, not solved here.

## Status of Implementation at Time of This ADR

Implemented in `src/data_infra/models.py` and `src/data_infra/enums.py`,
exercised by `tests/data/test_models.py`.
