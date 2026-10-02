# ADR-0236: Skip live price/corporate-action fetch for confirmed-delisted symbols before window

**Status:** Accepted
**Date:** 2026-10-02
**Deciders:** Claude Code (daily Paper Trading Actions health-check routine)
**Related documents:** `docs/decisions/ADR-0122-avb-real-delisting-and-left-censoring-query.md`
(the real, confirmed 2026-08-18 AVB/AvalonBay delisting this ADR acts
on), `docs/decisions/ADR-0215` (reordered Twelve Data before Tiingo for
price bars specifically because Twelve Data's own permanent "not
found" for AVB was already a known problem), `docs/decisions/ADR-0203`
(the corporate-action fallback/severity fix this ADR's corporate-action
skip extends), `docs/decisions/ADR-0085-incremental-ingestion-window.md`
(the incremental-window/overlap mechanism this ADR's second fix
corrects)

## Context

Run #53 (2026-10-01, `36829673996`, workflow_dispatch) failed at the
"Ingest latest market data" step with `ingestion_status: PARTIAL_
SUCCESS`. The only non-SUCCESS per-symbol result was AVB:
`all providers failed for AVB: twelvedata=PermanentProviderError(not
found calling /time_series); tiingo=TransientProviderError(rate
limited calling /tiingo/daily/AVB/prices); alphavantage=
TransientProviderError(Alpha Vantage rate limited for AVB: ... 25
requests per day ...)`.

AVB is not a transient failure -- `ADR-0122` already confirmed, via two
independent real sources, that AvalonBay Communities and Equity
Residential completed a real merger on 2026-08-18 and AVB stopped
existing as a tradeable security that day. `RESEARCH_UNIVERSE_STAGE4`'s
own `SymbolMetadata` for AVB already carries this as a real, confirmed
`listed_to = 2026-08-18`. Twelve Data's permanent "not found" for AVB
is therefore CORRECT, not a bug -- but `ingest_real_market_data.py`
retried it through the full Tiingo/Alpha Vantage fallback chain every
single day regardless, for a security that will never again produce a
bar. `ADR-0215` had already partly worked around this (reordering
Twelve Data before Tiingo so AVB's guaranteed failure wouldn't also
burn Tiingo's budget first) but a day where Tiingo and Alpha Vantage
both separately also lacked spare quota (rate limited / 25-requests/day
cap already spent) still left AVB with `status: FAILED`, which alone
drags the whole run's `IngestionRunner` status to `PARTIAL_SUCCESS` and
fails this script's own exit code (`result.status.value == "SUCCESS"`
gate) -- skipping "Run paper trading cycle" that day on an otherwise
clean run, purely because of one already-known-dead symbol.

**A second, larger effect found while tracing the first**: run #53's
own `--start` was `2026-08-10` -- a ~52-day window, not the few-day
trailing window `ADR-0085`'s incremental design normally produces.
Read `scripts/compute_incremental_ingestion_start.py` in full: it
computes the global `--start` as the MINIMUM of each requested symbol's
own `MAX(timestamp)` in the catalog, specifically so a symbol lagging
behind the rest is not silently skipped (`ADR-0115`). AVB's own last
real bar is frozen at its real delisting-eve date (~2026-08-17) and can
never advance, since every later run's fetch attempt for it fails by
design (it is delisted). With AVB counted in that minimum, it has been
anchoring the GLOBAL incremental start backward by a growing amount
every single day since 2026-08-18 -- the observed `2026-08-10` is
exactly `~2026-08-17 minus the 7-day overlap`, confirming this
directly, not inferred. This means every daily run has been
re-requesting an ever-growing historical window for all ~86 OTHER,
healthy symbols too (not just AVB), which is the most direct
explanation for the `1575 duplicate_records` WARNING-severity data
quality findings observed the same run (`ADR-0168` already documents
`duplicate_records` as the expected, correctly-downgraded-to-WARNING
side effect of re-requesting an overlap window with provider
revisions) and for "Ingest latest market data" taking the bulk of its
~14-minute runtime.

## Decision

Two complementary fixes, both narrowly scoped to a symbol with a REAL,
CONFIRMED `SymbolMetadata.listed_to` (never a guessed or assumed
delisting -- the same discipline `ADR-0122` itself established):

1. **`scripts/compute_incremental_ingestion_start.py`** now excludes
   any symbol with a confirmed `listed_to` from the "least caught-up
   symbol" computation that drives the global `--start` date. `compute_
   start_date()` itself (the pure, universe-agnostic function, already
   directly unit-tested) is unchanged; the exclusion is applied at the
   CLI's own `main()`, which is the only layer that has universe
   metadata at all. A confirmed-delisted symbol is still part of the
   `symbols` list `ingest_real_market_data.py` separately uses for its
   own security-master/membership bookkeeping -- this is a narrower,
   catch-up-only exclusion.

2. **`scripts/ingest_real_market_data.py`** now computes
   `delisted_before_window` (symbols whose confirmed `listed_to`
   already precedes the REQUESTED `--start` entirely) and skips them
   from both the corporate-action loop and the price-bar `IngestionRunner.
   run()` call -- via a new `live_fetch_symbols` list used only for
   those two calls. `symbols` itself is left completely untouched
   everywhere else (bar-count reporting, checksum, `missing_symbols`,
   `quality.run(known_security_ids=...)`), so a delisted symbol's own
   already-persisted historical bars within the window are still read
   back and reported exactly as before -- only the hopeless NEW-data
   attempt is skipped. `unexplained_zero_bar_symbols` additionally
   excludes `delisted_before_window`, so a delisted symbol correctly
   showing zero bars once the window moves entirely past its delisting
   date does not re-trip the FATAL unexplained-zero-bars gate
   (`ADR-0175`). The manifest gains `symbols_skipped_delisted_before_
   window` for transparency, and a skip is printed to the CI log.

Both fixes are needed together: fix 1 stops the window from staying
pinned to AVB's frozen last-bar date (closing the growing-re-fetch/
duplicate-records problem); fix 2 stops the daily wasted-quota-and-
PARTIAL_SUCCESS problem once the window (correctly, after fix 1) moves
past the delisting date. Neither alone fully resolves run #53's
observed failure.

### Why not just drop AVB from `RESEARCH_UNIVERSE_STAGE4` entirely?

Considered and rejected: `ADR-0122` deliberately keeps a delisted
symbol as a real, dated `SecurityMaster`/`UniverseMembership` record
(`SecurityStatus.DELISTED`, not deleted) so its own historical bars and
membership window remain queryable for any as-of-date backtest that
predates 2026-08-18 -- removing it from the universe definition would
silently erase that history's point-in-time availability, which is
exactly the survivorship-bias risk `ADR-0122`/`ADR-0061` exist to
avoid. This ADR's fix operates only on the live-fetch/catch-up layer,
never on universe membership itself.

## Consequences

### Positive

- Closes the exact gap run #53 exposed: a confirmed-delisted symbol no
  longer drags the whole run to `PARTIAL_SUCCESS`/skips Paper Trading,
  and no longer burns shared Tiingo/Alpha Vantage quota on a guaranteed
  failure every single day.
- Stops the incremental window from silently growing backward forever
  -- future daily runs should return to the normal few-day trailing
  window `ADR-0085` designed, reducing both runtime and the
  `duplicate_records` WARNING volume.
- Both exclusions are keyed on the SAME real, confirmed `listed_to`
  fact `ADR-0122` already established -- no new delisting judgment is
  introduced, and a symbol without a confirmed date is completely
  unaffected (still forces the full fallback range if uncaught-up,
  still attempted live every run).

### Negative / Trade-offs

- A symbol whose `listed_to` is confirmed only AFTER this project has
  already let its last-known-bar drag the window backward for a while
  will not retroactively un-grow an already-widened window -- this fix
  only stops further growth from the moment it is applied, same as
  `ADR-0122`'s own "a human applies it" precedent for how confirmed
  dates enter this project.
- `delisted_before_window`'s comparison (`listed_to <= args.start`) is
  deliberately conservative: a window that straddles the delisting date
  itself (starts before it, ends after) still attempts the live fetch,
  since there may be real final-days data still missing from the
  catalog. Only a window ENTIRELY after the confirmed delisting date is
  skipped.

## Tests

- `tests/deploy/test_compute_incremental_ingestion_start.py`: new
  `TestConfirmedDelistedSymbolsExcludedFromCatchUp` (2 tests) --
  verifies a confirmed-delisted symbol's frozen old bars no longer
  anchor the computed `--start` backward, and that an ordinary
  zero-bar (never confirmed-delisted) symbol still correctly forces
  the full fallback range unchanged.
- `tests/data_infra/test_ingest_real_market_data_wiring.py`: new
  `TestConfirmedDelistedSymbolsSkipLiveFetch` (6 tests, source/AST-based
  -- this script is never imported/executed by the suite, real network
  calls only) -- `delisted_before_window`'s computation, `live_fetch_
  symbols`'s use in both the corporate-action loop and `IngestionRunner.
  run()` instead of raw `symbols`, the manifest key, the CI log
  message, `unexplained_zero_bar_symbols`'s exclusion, and that bar-
  count/checksum reporting still reads from the full `symbols` list.
  One pre-existing test (`test_unexplained_zero_bar_symbols_is_empty_
  when_no_trading_days_expected`) updated for the assignment's new
  multi-line shape -- no behavior change to what it verifies.

Full suite re-run: see `docs/PROJECT_STATUS.md`'s session log.

## Status of Implementation at Time of This ADR

Code, tests, and documentation complete and committed.
