# ADR-0061: wire real S&P 500 point-in-time `listed_from` into `universe.py`

**Status:** Accepted
**Session:** 36

## Context

The user asked to proceed with several open items excluding two
explicitly named categories (Toss/FX operational work, and Learning
Engine resumption). One item was "survivorship bias infra" -- earlier
in this session this was mis-described to the user as blocked on a
paid data-source decision. That was stale: `ADR-0037` (an earlier
session) already found and adopted a real, free, MIT-licensed dataset
(`hanshof/sp500_constituents`, point-in-time S&P 500 index membership
scraped from Wikipedia) and built
`data_infra.providers.sp500_pit_membership` to parse it, but
deliberately left wiring its output into an actual `UniverseDefinition`
as a future step (that ADR's own "Consequences" section).

This session, GitHub was directly reachable from this sandboxed
environment (confirmed by cloning the real repository), unlike every
market-data/SEC EDGAR provider host checked in prior sessions. This
made it possible to do the real computation directly in this session,
rather than needing the user to run a script in their own environment
(the pattern ADR-0058/0059 needed for SEC EDGAR data).

## Decision 1 -- `scripts/compute_sp500_pit_listed_from.py`, a reproducible computation CLI

Built a script that parses a local copy of
`sp_500_historical_components.csv` (not committed to this repo, per
ADR-0037's own decision -- a caller supplies the path at run time),
calls the already-existing, already-tested
`sp500_pit_membership.parse_snapshots`/`reconstruct_intervals`, and
emits a JSON report of `confirmable_listed_from`/censoring flags per
requested symbol. Deliberately makes no network call itself and writes
no output into `universe.py` directly -- same division of
responsibility ADR-0058 established for sector data (script computes
and reports; applying the result to a hand-curated Python literal is a
separate, explicit step).

Run against the real file this session (cloned directly, real MIT
license, matching ADR-0037's own verification): 32 of the 87
`RESEARCH_UNIVERSE_STAGE4` symbols (also covering all 15
`PILOT_UNIVERSE_V1` symbols, a subset) have a confirmable
`listed_from` -- the symbol was NOT already present in the dataset's
very first snapshot (1996-01-02), so its apparent join date is a real,
dateable event. Zero symbols in either universe had left the index by
the dataset's last snapshot (2025-08-23) -- expected, since both
universes were selected from today's current large caps.

7 new tests (`tests/data_infra/test_compute_sp500_pit_listed_from_cli.py`)
run this script end-to-end against a small synthetic fixture CSV
(unlike `fetch_sector_classifications.py`, this script makes no network
call, so it can be tested for real rather than only at the AST/source
level) -- covering a left-censored symbol, a confirmable-date symbol,
a symbol that left the index (flagged, never auto-converted to a
`listed_to`), a never-seen symbol, and the `ALL`-universe selection.

## Decision 2 -- apply `listed_from` only, never `listed_to`, to `universe.py`

Added `_SP500_PIT_CONFIRMED_LISTED_FROM` (the 32 real confirmed dates)
and extended `_real_symbol_metadata` (ADR-0058's own function) to also
populate `listed_from` from it, independently of `sector`/`exchange`
(a symbol can have either, both, or neither -- verified by a new test,
`TestRealSymbolMetadata::test_sector_exchange_and_listed_from_are_
independently_populated`, using `AVB`: no confirmed sector/exchange,
but a real confirmed `listed_from`).

**`listed_to` is never set from this data.** Every symbol in this
project's universes was selected because it is a CURRENT holding; the
real data confirms none of them have left the S&P 500 as of the
dataset's last snapshot, so setting `listed_to` would fabricate a
delisting that never happened. This also means this change does NOT
add back any company that was removed from the index and is therefore
simply absent from `RESEARCH_UNIVERSE_STAGE4`/`PILOT_UNIVERSE_V1`
entirely -- that class of survivorship bias (a symbol never appearing
in the universe at all) is unchanged by this ADR, exactly as
ADR-0037 Decision 3 already said it would be.

## Decision 3 -- the ticker-vs-corporate-identity caveat is stated, not resolved

Several of the 32 confirmed dates are for tickers this session has
background-knowledge reason to suspect involve a merger, spinoff, or
rename (e.g. `META`'s 2022-06-09 date is very plausibly the FB->META
ticker rename, not Facebook's original 2013 index addition; `RTX`/
`LIN`/`DOW`/`PSX` involve known corporate restructurings). **This ADR
deliberately does NOT hand-classify which of the 32 are "clean" vs.
"ticker-identity-discontinuous" using background knowledge** -- doing
so without a verified source would itself be exactly the kind of
fabrication this project's discipline forbids elsewhere (the same
reasoning that has repeatedly declined to guess a CIK, an exchange, or
a rate from memory). Instead, the module docstring and the
`_SP500_PIT_CONFIRMED_LISTED_FROM` dict's own comment state the caveat
generally and prominently: every date is a REAL date from a REAL
licensed dataset, but the INTERPRETATION "this is when the company
joined" carries this caveat for any ticker that was ever renamed or
reissued -- the same class of gap `audit_survivorship`'s own
"permanent identity is not yet distinct from ticker" finding already
documents structurally (`security_id == ticker` in this project's own
model, unchanged by this ADR).

## Consequences

- `audit_survivorship`'s classification of `RESEARCH_UNIVERSE_STAGE4`/
  `PILOT_UNIVERSE_V1` moves from `CURRENT-UNIVERSE-ONLY` toward
  `PARTIALLY_MITIGATED` (32/87 and a subset of 15 symbols now carry a
  provider-confirmed date) -- a real, if partial and caveated,
  improvement, not a claim that survivorship bias is resolved.
- `build_universe_memberships`/`build_security_masters`'s existing
  `s.listed_from or valid_from` fallback (Phase 29, unchanged) now
  actually uses a real date for these 32 symbols instead of always
  falling through to the caller-supplied uniform `valid_from` -- 2
  existing tests updated to reflect this (`test_build_universe_
  memberships_uses_supplied_valid_from`, using AAPL for the
  still-unconfirmed case and NVDA for the now-confirmed case).
- 3 existing "carries no provider-confirmed dates" tests (Stage 2/3/4)
  updated from an unconditional `listed_from is None` assertion to the
  real, split state (confirmed for the 32, still honestly `None` for
  the rest) -- same treatment ADR-0059 already gave the equivalent
  sector/exchange tests.
- Does not touch `market_cap_bucket` -- no real data source for it
  exists in this project.
- Does not touch `RESEARCH_UNIVERSE_STAGE1`/`STAGE2`/`STAGE3` symbol
  lists themselves, `factor_strategy.py`, `strategy_research/*`, or any
  walk-forward result -- purely a metadata-accuracy change to
  `universe.py`.

## Tests

7 new (`test_compute_sp500_pit_listed_from_cli.py`), 3 new
(`TestRealSymbolMetadata` additions), 5 existing tests updated (not
weakened) to reflect the real, split state. Full suite: 2278 passed
(up from 2267).
