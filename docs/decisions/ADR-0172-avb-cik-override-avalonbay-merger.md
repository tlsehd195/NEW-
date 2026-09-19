# ADR-0172: Add AVB to `ingest_insider_transactions.py`'s known CIK overrides (real corporate action, not a data-quality bug)

**Status:** Accepted
**Date:** 2026-09-19
**Deciders:** Claude Code (session continued), account owner (asked to
check the real shard-8 failure of the running full-universe sharded
insider-transaction collection, ADR-0171)

## Context

During the real `ingest_insider_transactions_full.yml` run (run id
`35422789625`), matrix job `ingest (8)` (shard 8 of 10) completed with
`conclusion: failure`. Its own real logs show 7 of its 8 symbols
succeeding normally (19,855 transactions persisted, zero filing
errors); only `AVB` failed, with `resolve_cik` returning `None`
("Unresolved symbols (no CIK found): ['AVB']"), which
`failed_symbols_from` correctly treats as a non-zero-exit condition
(`main()`'s own `return 0 if not failed_symbols and ... else 1`).

This is NOT a repeat of ADR-0042/ADR-0050's XOM incident (a live
ticker resolving to the WRONG CIK due to a holding-company
reorganization) -- AVB resolved to no CIK at all, because it is no
longer a live, tradeable ticker: `src/data_infra/universe.py` already
documents, with independent corroboration (a real `fja05680/sp500`
dataset entry plus a real WebSearch against news coverage), that
AvalonBay Communities merged with Equity Residential on 2026-08-17,
forming "Vivmark Residential" trading under a new ticker (`VMRK`) from
2026-08-18. SEC EDGAR's *live* `company_tickers.json` -- the only
source `resolve_cik` consults -- naturally drops a ticker once its
issuer stops filing under it, so this run (2026-09-19, over a month
after the merger) legitimately found nothing for `AVB`.

The real historical CIK for AvalonBay (`0000915912`) is not a new
lookup -- it is the exact value `universe.py`'s own sector/exchange
backfill already found and verified after hitting this identical
ticker-map miss earlier (`fetch_sector_classifications.py
--cik-overrides AVB:0000915912`, see `universe.py` lines 42-47,
149-151, 253-258).

## Decision

Added `"AVB": "0000915912"` to `_KNOWN_CIK_OVERRIDES` in
`scripts/ingest_insider_transactions.py`, the same dict and mechanism
ADR-0050 already established for XOM -- both entries are baked-in
defaults so re-running the full universe never depends on a human
remembering a `--cik-overrides` flag.

This intentionally does NOT touch `RESEARCH_UNIVERSE_STAGE4`'s own
membership or the S&P-500 point-in-time listing windows
(`_SP500_PIT_CONFIRMED_LISTED_TO["AVB"] = "2026-08-18"`) -- AVB's real
Form 4 filing HISTORY (up through the real merger date) is exactly the
data this ingestion pipeline is supposed to collect for a symbol that
was a real, listed member of the universe for the vast majority of its
history; only the CIK *lookup path* needed a fix, matching the same
override-not-network-request-workaround discipline XOM's fix used.

## Consequences

- Shard 8's 7 already-succeeded symbols are untouched (already uploaded
  as a real, valid `insider-transactions-shard-8` artifact); this fix
  only lets a follow-up run collect AVB's own history, which will be
  merged into the combined catalog as an additional input to
  `merge_insider_transaction_catalogs.py` (idempotent
  `ON CONFLICT ... DO NOTHING`, safe regardless of what shard 8's
  artifact already contains for AVB, i.e. nothing).
- No other symbol in `RESEARCH_UNIVERSE_STAGE4` is known to have this
  problem -- like ADR-0050, this fixes only the one confirmed case,
  not a general "ticker no longer resolves" detector.

## Tests

`tests/data_infra/test_ingest_insider_transactions_wiring.py`: added
`test_known_cik_overrides_dict_has_avb`, same AST/source-text
discipline as the existing XOM test. Full suite re-run: 3406 passed.
