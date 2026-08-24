# ADR-0004: Point-in-Time Data Handling & Look-ahead Guard

**Status:** Accepted
**Date:** 2026-08-24
**Deciders:** Claude Code (Phase 1 session), pending project owner review
**Related documents:** `PROJECT_MASTER_PLAN.md` §16, §29 (Point-in-Time
Principle, Look-ahead Guard), `docs/specifications/PHASE-1-data-infrastructure.md`
§10, §12, §15, §16

---

## Context

The master plan's single most important invariant for this project is:
a decision simulated at time `T` must never see information that did not
exist (from the system's point of view) at `T`. Getting this wrong
invalidates every backtest and every trained model built on top of it,
no matter how good the resulting metrics look
(`PROJECT_MASTER_PLAN.md` §53, §92; Phase 1 spec §16). This ADR fixes how
point-in-time correctness is enforced at the data layer, since Phase 1
is the only layer where it can be enforced structurally — every later
phase (Backtest, Feature, Decision) inherits this guarantee rather than
re-implementing it.

## Decision

### 1. Four distinct timestamps

Every time-sensitive record (`PriceBar`, `CorporateAction`,
`BenchmarkPoint`) carries, where applicable:

```
event_time         # when the underlying real-world event happened
publication_time    # when it was first made public (may be absent for
                     # data that has no separate publication step, e.g.
                     # a routine daily close price — in that case
                     # publication_time == available_time by convention)
available_time      # when OUR system could have used it in a decision
ingestion_time      # when it actually arrived in OUR system
```

`available_time` is the field every point-in-time query filters on. It
is deliberately allowed to be later than `publication_time` (e.g., a
provider publishes a number but our ingestion pipeline only picks it up
some time afterward — in that case `available_time` reflects *our*
system's actual capability, not an idealized "as soon as published"
assumption) but must never be set earlier than `publication_time`. This
constraint is validated by the Data Quality Framework (Phase 1 spec
§13.1) as a timestamp-ordering check, and by `SecurityMaster`/
`CorporateAction` model validation in `__post_init__`.

### 2. `available_time` is set conservatively

When a real provider does not explicitly expose a publication/
availability timestamp (common for routine end-of-day price data),
`available_time` defaults to `ingestion_time` for that record, **never**
to `event_time` — i.e., the system assumes it did not have the data
until it actually ingested it, not "as soon as the market event
happened." This is the conservative direction required by
`PROJECT_MASTER_PLAN.md` §1.4 (fail-closed posture applied to data
availability, not just to broker/risk state).

### 3. `DATA_EXISTS` vs. `DATA_AVAILABLE`

These are modeled as two different predicates, never conflated:

- `DATA_EXISTS`: the record is present in the Clean-layer store (an
  administrative/catalog-level fact).
- `DATA_AVAILABLE(as_of_time)`: `record.available_time <= as_of_time` —
  the fact that matters for any point-in-time query.

`DataRepository` (Phase 1 spec §12) exposes **only** `DATA_AVAILABLE`
semantics to its consumer-facing methods; there is no method on the
interface that returns "all data regardless of `as_of_time`" for
consumer use. `as_of_time` is a required, non-optional parameter on
every time-sensitive `DataRepository` method precisely so that no future
caller (Backtest, Feature Engine, Decision Replay) can accidentally omit
it and get an un-filtered, leakage-prone result.

### 4. Look-ahead guard is structural, not conventional

The filter `available_time <= as_of_time` is applied **inside** the
repository implementation, at the point results are constructed, before
returning to any caller — not left as a documented convention that
calling code must remember to apply itself. This is deliberately
redundant with correct provider-side `available_time` tagging: even if
an upstream ingestion bug set an incorrect `available_time`, the guard
still enforces whatever value was actually stored, and a wrong
`available_time` becomes a detectable data-quality bug (caught by
timestamp-ordering checks) rather than a silent leakage bug in every
downstream consumer.

### 5. `as_of_time` and UTC

`as_of_time` arguments are required to be timezone-aware; comparison
against `available_time` happens after both are normalized to UTC
(Phase 1 spec §10). This avoids a class of bugs where a naive local-time
`as_of_time` is compared against a UTC-stored `available_time` and
silently shifts the effective cutoff by several hours — which, for a
same-day decision, could be exactly the size of a real leakage bug.

## Alternatives Considered

- **Single `timestamp` field with an implicit "assume available
  immediately" convention**: Rejected — this is precisely the pattern
  that causes look-ahead bias in naive backtests (using a data
  provider's as-of-today dataset applied uniformly to all historical
  dates). The master plan explicitly calls this out as a failure mode to
  design against (`PROJECT_MASTER_PLAN.md` §1.1, §16).
- **Leaving look-ahead filtering as a documented responsibility of
  caller code** (e.g., "Backtest engine must remember to filter by
  `available_time`"): Rejected — a convention that must be remembered
  correctly by every future caller, forever, is exactly the kind of
  fragile safety mechanism `PROJECT_MASTER_PLAN.md` §90 (Fail-Closed)
  argues against. Enforcing it once, structurally, inside the
  `DataRepository` implementation removes an entire class of future bugs.
- **Defaulting missing `available_time` to `event_time`** (optimistic):
  Rejected — would systematically leak information earlier than a real
  investor could have had it. Defaulting to `ingestion_time`
  (conservative) is the fail-closed choice.
- **Making `as_of_time` optional with a "return everything" default**:
  Rejected — an optional parameter with an unsafe default is exactly how
  look-ahead bugs get introduced by omission. Making it required removes
  the unsafe default entirely.

## Consequences

### Positive

- Look-ahead bias is prevented by construction at the one layer
  (`DataRepository`) every future consumer must go through, rather than
  relying on every future phase's authors to re-derive and correctly
  implement the same discipline.
- The conservative `available_time` default (§2 above) means any
  ambiguity in real provider data errs toward *not* leaking information,
  consistent with the project's overall fail-closed philosophy.
- Because the guard operates on stored `available_time` rather than
  trusting callers, a wrong value becomes a detectable, testable data
  quality issue instead of a silent modeling error discovered only much
  later (e.g., during Phase 2 backtest validation).

### Negative / Trade-offs

- Providers that do not expose a true publication/availability timestamp
  will have their `available_time` pinned to `ingestion_time`, which can
  be later than the real-world "could have known" time if our ingestion
  pipeline runs with a lag. This is intentionally conservative
  (understating availability) rather than optimistic (overstating it) —
  accepted as the safe direction, per §2.
- Enforcing `as_of_time` as a required parameter on every
  `DataRepository` method is a small ergonomic cost for any future
  "just give me the latest data" convenience use case (e.g., a
  dashboard). Such use cases must pass `as_of_time=now()` explicitly
  rather than relying on an implicit default — considered an acceptable
  cost for removing an unsafe default globally.

## Status of Implementation at Time of This ADR

Implemented in `src/data_infra/repository.py`
(`InMemoryDataRepository`), validated by `tests/data/test_repository_asof.py`
and `tests/data/test_lookahead_guard.py`.
