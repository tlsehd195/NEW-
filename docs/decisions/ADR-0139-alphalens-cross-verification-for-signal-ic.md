# ADR-0139: `alphalens-reloaded` Cross-Verification for Signal IC

**Status:** Accepted
**Date:** 2026-09-17
**Deciders:** Claude Code (session continued), pending project owner review
**Related documents:** `docs/decisions/ADR-0138-quantstats-tearsheet-for-paper-trading.md`
(this session's immediately preceding "verify an external library
directly before trusting it" precedent), `scripts/compute_signal_ic_from_catalog.py`
(the sibling script this one cross-verifies against, unmodified)

---

## Context

One of the account owner's own uploaded external-resource-recommendation
reports named `alphalens-reloaded` as "highest priority, zero conflict
with the existing pipeline" for factor IC/quantile diagnostics.
Continuing the account owner's "쉬운거부터 순서대로" (easiest-first)
pass through these reports' findings, and continuing this session's own
established discipline (ADR-0138) of testing an externally-recommended
library directly against this project's real usage shape before
adopting it, rather than trusting a recommendation at face value.

Unlike `quantstats-reloaded` (ADR-0138), direct testing found no crash
in `alphalens-reloaded==0.4.6` itself -- but it did surface a real,
structural mismatch between alphalens's own design assumption and this
project's own Signal IC convention, described in Decision 2 below.

## Decision 1 -- a diagnostic cross-check script, never a replacement for `compute_ic_series`

`scripts/verify_signal_ic_with_alphalens.py` computes this project's
own `strategy_research.signal_ic.compute_ic_series` (unmodified, same
call any existing script makes) AND alphalens's own independent
`factor_information_coefficient`, for the same real factor/universe/
window/horizon, and prints both side by side. Matches RULE 0.8 exactly
as it already governs every other raw-IC result in this project: this
script's own output is explicit that `compute_ic_series`'s number is
what the walk-forward/PBO/DSR pipeline actually consumes, and alphalens's
number is a diagnostic corroboration, never a silent override.

## Decision 2 -- alphalens needs a DAILY factor; this project's own IC uses a monthly rebalance cadence -- disclosed, not forced to match

Direct testing (constructing a real `factor`/`prices` pair and calling
`alphalens.utils.get_clean_factor_and_forward_returns`) found: passing
the factor at this project's own `--step-months` rebalance cadence
(e.g. one score per security per calendar month) raises a real
`ValueError` ("Inferred frequency ... does not conform to passed
frequency..."). Traced to `alphalens.utils.infer_trading_calendar`:
it infers ONE shared trading calendar from the union of the factor's
own dates and the (dense, daily) price index, then attempts to apply
that inferred calendar to validate the whole combined index -- a
sparse, monthly-spaced factor date set cannot satisfy a calendar
inferred from (and meant to describe) a dense daily one, regardless of
whether each individual sparse date is itself a real trading day
(confirmed separately: snapping each rebalance date to the nearest
real trading date did NOT fix the crash on its own).

Rather than force this project's own rebalance cadence to match
alphalens's assumption (which would make the two numbers describe
functionally different experiments while pretending otherwise), or
silently give up on the cross-check, this script evaluates the factor
on EVERY real trading date in `[--start, --end)` for alphalens's own
side specifically -- `compute_ic_series`'s own call, a few lines
earlier in `main()`, is completely unaffected and still uses
`--step-months` exactly as `compute_signal_ic_from_catalog.py` already
does. The printed output says this explicitly (both mean_ic values are
labeled with their own real cadence) so a reader is never misled into
treating the two numbers as measuring the identical experiment -- a
disclosed, deliberate difference, not a hidden discrepancy.

## Decision 3 -- optional `research` extra; scope limited to price-only factors

`alphalens-reloaded` pulls in `pandas`/`numpy`/`matplotlib` -- added as
a new `research` entry under `[project.optional-dependencies]`,
alongside the identical `reporting` extra ADR-0138 already established
(`src/` stays free of a hard pandas/numpy dependency). Only the
price-only factors from `strategy_research.factor_scores` (16 of
`compute_signal_ic_from_catalog.py`'s own factor choices) are wired in
-- the momentum-strategy-class-based ones need constructing a stateful
strategy instance first, a small, separate extension left for later,
not done here.

## Consequences

### Positive

- A real, working, independently-implemented cross-check for this
  project's own Signal IC computation exists for the first time,
  reusing (never duplicating) the exact same real factor-scoring
  functions and DuckDB-backed price data every other Signal IC script
  already uses.
- The daily/monthly cadence mismatch is now a documented, reusable
  finding -- any future integration of a dense-cadence-expecting
  library (alphalens or otherwise) against this project's own sparse
  rebalance convention should expect the same class of issue.

### Negative / Trade-offs

- The two mean_ic values this script reports are not a strict
  apples-to-apples comparison (different rebalance density) -- a
  genuine limitation of the cross-check's precision, disclosed in the
  script's own printed output and this ADR, not hidden.
- Momentum-strategy-class factors (`long_term_momentum`/`risk_
  controlled_momentum`) are not yet wired into this cross-check script
  -- left for a future session.
- Cannot be run against real market data in this session's own
  sandbox (no real DuckDB catalog exists here) -- proven correct only
  against a synthetic fixture, matching every other catalog-reading
  script in this repository's own existing precedent
  (`compute_signal_ic_from_catalog.py` itself is in the same position).

## Tests

`tests/strategy_research/test_verify_signal_ic_with_alphalens_cli.py`
(6 tests: rebalance-date stepping, TEST-1 locked-window refusal with
no override, a real end-to-end cross-verification run against a
synthetic low/high-volatility catalog, direct shape checks on the
`build_factor_and_prices` adapter, and an insufficient-data failure
mode) -- `pytest.importorskip("alphalens")` guards every test so the
suite skips cleanly wherever the optional `research` extra was never
installed. Full suite re-run clean after these changes, with the extra
installed in this session's own sandbox.

## Status of Implementation at Time of This ADR

Code, tests, and documentation complete and committed.
