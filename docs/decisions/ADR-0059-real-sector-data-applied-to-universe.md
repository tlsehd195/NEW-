# ADR-0059: real SEC EDGAR sector/exchange data applied to `universe.py`

**Status:** Accepted
**Session:** 36

## Context

`scripts/fetch_sector_classifications.py` (ADR-0058) was run for real
by the user against Stage 4's 87 symbols. 86 resolved (`AVB`'s ticker-
map CIK lookup did not resolve on this run, same gap seen earlier for
fundamentals ingestion). This ADR covers applying those real findings
to `src/data_infra/universe.py`'s `SymbolMetadata` entries -- the
deliberate manual follow-up step ADR-0058 itself said would be needed,
since there is no established "apply this JSON to a Python source
literal" mechanism in this project.

## Decision

Added `_REAL_SEC_SECTOR_AND_EXCHANGE`, a module-level dict of the 86
real `(sector, exchange)` pairs the fetch run returned, and
`_real_symbol_metadata(symbol)`, a small helper that looks a symbol up
in that dict and returns a `SymbolMetadata` with real `sector`/
`exchange` when resolved, or the honest untouched `None` default when
not (never a fabricated value for `AVB` or any symbol this session did
not actually confirm). All 4 of `universe.py`'s `SymbolMetadata(symbol=s)`
generator call sites (`PILOT_UNIVERSE_V1`, and Stage 2/3/4's own
additions) now call `_real_symbol_metadata(s)` instead.

**This also updates `PILOT_UNIVERSE_V1`, not just the Stage 2-4
additions** -- a deliberate consequence, not an oversight. `sector`/
`exchange` describe a real-world fact about a company, not something
tied to which `UniverseDefinition` happens to list that symbol; leaving
`PILOT_UNIVERSE_V1`'s own `AAPL` entry as `sector=None` while
`RESEARCH_UNIVERSE_STAGE4`'s `AAPL` entry (the same real company) shows
`sector="Electronic Computers"` would itself be a kind of dishonesty --
two different in-memory representations of one confirmed real fact
disagreeing depending on which list is asked. Two existing tests
(`TestSymbolMetadataHonesty`/`TestConverters` in `tests/data_infra/
test_universe.py`) asserted the OLD "always None" state for
`PILOT_UNIVERSE_V1` specifically; both were updated to assert the new,
factually accurate state (`market_cap_bucket`/`listed_from`/
`listed_to` remain unconditionally `None` -- this project has no real
data source for those at all) rather than the fields this session now
has real confirmed values for.

**`sector` is the SEC's own SIC classification TEXT
(`sicDescription`), never a GICS sector label** -- restated here at the
point of consumption (not just in `SecEdgarFundamentalsProvider.
normalize_submissions`'s own docstring, ADR-0055) since this is the
first place `SymbolMetadata.sector` is actually populated and a future
reader of `universe.py` alone should not need to trace back to the
provider module to learn this.

**Module docstring updated**: the honesty-discipline paragraph
explicitly promised ("once real ingestion actually runs... a future
phase should populate these fields from that real response") is now
marked fulfilled for `sector`/`exchange` specifically, with the same
caveat about `AVB` staying unconfirmed rather than silently dropped.

## What this deliberately does NOT do

- **Does not activate the sector-neutralization cap
  (`ADR-0055`'s `factor_strategy._select_target`,
  `sector_by_security`/`max_per_sector`) for any existing walk-forward
  candidate.** Doing so now -- after `size` has already been observed
  to drop below `CANDIDATE` at `top_n=10` without any sector cap --
  would be exactly the post-hoc "does this change make my already-seen
  result look better" tuning RULE 0.8 forbids. The capability remains
  available, opt-in, and untouched; any future candidate could
  pre-register a sector cap before its own first result is seen, but
  that is a separate decision this ADR does not make.
- Does not fetch or apply `AVB`'s sector -- its CIK lookup did not
  resolve on the real run; re-running `fetch_sector_classifications.py`
  with `--cik-overrides AVB:0000915912` (the real CIK the user already
  found for the earlier fundamentals-ingestion gap) would close this,
  deferred to a future session/run.
- Does not touch `market_cap_bucket`/`listed_from`/`listed_to` -- no
  real data source for these has ever been integrated into this
  project; they remain honestly `None` everywhere.

## Tests

4 new tests (`tests/data_infra/test_universe.py`,
`TestRealSymbolMetadata`): a resolved symbol gets its real sector/
exchange; an unresolved symbol (`AVB`) and a never-fetched symbol both
get the honest all-`None` default; a symbol with a confirmed sector but
no confirmed exchange (`XOM`) leaves `exchange` `None` rather than
guessing. 2 existing tests updated (not deleted) to assert the new,
factually accurate state rather than the outdated "always None"
assumption.

Full suite: 2267 passed (up from 2262).
