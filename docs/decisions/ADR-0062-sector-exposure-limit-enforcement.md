# ADR-0062: opt-in sector exposure limit enforcement in `PortfolioRiskEngine`

**Status:** Accepted
**Session:** 36

## Context

`LIVE-RISK-POLICY.md` item #5 (sector exposure) had been classified
**BLOCKING** since Phase 17: `data_infra.models.SecurityMaster` has no
`sector` field, so `RiskConfig.max_sector_weight` had nowhere to get
sector data from. The user asked to proceed on this item as part of a
3-part risk-infrastructure request.

Adding `sector` directly to `SecurityMaster` was considered and
rejected as the wrong-sized fix: `SecurityMaster` is a foundational
Phase 1 model referenced by `storage/schema.py`, `storage/
serialization.py`, and every constructor site across backtest/paper/
live -- a schema change there is a much larger, more invasive change
than this gap actually requires, and `RiskConfig`'s own prior comment
already pointed at a lighter-weight "Feature Registry"-style extension
point instead of a schema change.

This project already has a working precedent for exactly this shape of
problem: `ADR-0055`'s `factor_strategy._select_target` added an opt-in
`sector_by_security: Optional[dict[str, str]]` parameter the CALLER
supplies, rather than touching any core model. This ADR applies the
same pattern to `PortfolioRiskEngine.assess`.

## Decision

`PortfolioRiskEngine.assess` (Protocol and
`DeterministicPortfolioRiskEngine`, `src/risk/engine.py`) gains a new
keyword-only parameter, `sector_by_security: Optional[dict[str, str]] =
None` -- same shape and same "caller supplies it per call" contract as
the existing `turnover`/`liquidity_state` parameters, fully backward
compatible (no existing call site passes it, so behavior is unchanged
unless a caller opts in).

`_compute_risk_state` now populates `PortfolioRiskState.sector_exposure`
(a field that already existed, previously always hardcoded `None`)
whenever `sector_by_security` is supplied: for each held position with
a known sector, sums that position's weight into its sector's total. A
position whose security is absent from the mapping is excluded from
every sector total, never guessed.

A new `sector_limit` check, positioned after `turnover_limit` and
before `liquidity_limit` (same ordering rationale as every other
check -- cheapest/most-certain-data-first), fires only when
`config.max_sector_weight is not None`:

- If `sector_by_security` was not supplied, or the security being
  evaluated has no entry in it, the check REJECTs `sector_unknown` --
  fail-closed, mirroring `max_turnover`'s own "configured means
  fail-closed on missing data" pattern exactly. **Configuring
  `max_sector_weight` without also wiring `sector_by_security` at every
  call site does not silently disable the check** -- it blocks every
  BUY until the caller supplies sector data too, matching this
  project's fail-closed discipline (instruction section 7: "알 수 없는
  위험을 안전하다고 간주하지 않는다").
- Otherwise, if the sector's existing exposure plus the proposed new
  weight would exceed `max_sector_weight`, the position is clamped
  (mirroring `gross_exposure`'s own clamp-or-reject-outright logic) or
  rejected outright if the sector is already at or past the cap.

## What this deliberately does NOT do

- **Does not add a `sector` field to `SecurityMaster`.** The opt-in
  parameter is the whole fix -- no core model schema change, no
  `storage.schema`/`storage.serialization` change, no change to any
  existing `SecurityMaster` constructor call site anywhere in the
  repository (verified: zero test failures outside `tests/risk/`).
- **Does not wire `sector_by_security` into any Live/Paper/backtest
  caller.** No code anywhere in `src/broker/live/`, `src/broker/
  paper/`, or `src/backtest/` calls `.assess(...)` at all today (a
  repo-wide grep found zero non-`risk/engine.py` call sites) -- this
  ADR builds and tests the enforcement mechanism itself, matching this
  project's incremental, one-verified-piece-at-a-time discipline. A
  future phase that DOES wire Live/Paper order submission through
  `PortfolioRiskEngine.assess` would need to also source and pass a
  real `sector_by_security` mapping for `max_sector_weight` to have any
  live effect.
- **Does not set `RiskConfig.max_sector_weight` to any value.** It
  remains `None` (not enforced) by default -- same "a human must
  explicitly set this" discipline `max_turnover`/`max_daily_loss`/
  `max_order_frequency_per_hour` already established. Choosing a
  number is a separate financial-policy decision this ADR does not
  make.
- **Does not add `max_factor_exposure` enforcement.** No factor-
  exposure data source exists anywhere in this project; that item
  remains genuinely BLOCKING, unchanged.

## Consequences

- `LIVE-RISK-POLICY.md` item #5 reclassified from **BLOCKING** to
  **UNDEFINED** (same category as #1/#6/#7 -- a real enforcement path
  exists, only the number and the Live-caller wiring remain open).
- `docs/risk/models.py`'s `PortfolioRiskState` docstring updated: it no
  longer claims `sector_exposure` is "always `None` today."

## Tests

7 new (`tests/risk/test_engine.py::TestSectorLimit`): a sector-limit
breach reduces a new BUY; a sector already at cap rejects outright; no
mapping supplied with `max_sector_weight` configured rejects
`sector_unknown`; the target security missing from a supplied mapping
also rejects `sector_unknown`; `max_sector_weight=None` skips the check
even with no mapping supplied; `sector_exposure` on `PortfolioRiskState`
is populated only when a mapping is supplied; a security absent from
the mapping is excluded from every sector total. Full suite: 2285
passed (up from 2278).
