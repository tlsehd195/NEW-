# ADR-0126: Quandl WIKI Prices (Kaggle Mirror) as a Free, Partial Source of Real Delisted-Ticker Prices

**Status:** Accepted
**Date:** 2026-09-11
**Deciders:** Claude Code (documentation cleanup session, continued), pending project owner review
**Related documents:** `docs/decisions/ADR-0123-delisted-price-data-deep-search-still-blocked.md`,
`docs/decisions/ADR-0034-real-data-acquisition-strategy.md`,
`docs/decisions/ADR-0125-finra-equity-short-interest-real-response-converter.md`

---

## Context

`ADR-0123` concluded the delisted-ticker real-price-data problem was
still `ENVIRONMENT_BLOCKED` with no viable free source, after
empirically testing and rejecting `eliangcs/pystock-data` (its
"initial" backfill batch was itself a then-currently-listed-tickers
snapshot -- `DELL` was entirely absent). The user, having been told
about paid options (Norgate, EODHD, Sharadar, CRSP/WRDS) and rejecting
all of them ("유료는 절대 안돼" -- "paid is absolutely not allowed"),
asked for a deeper free-only search.

This session found and downloaded (in the user's own environment,
which this sandbox cannot reach -- `kaggle.com` is `connect_rejected`
here, consistent with every other financial-data host tested across
this project's history) the **Quandl WIKI/PRICES** dataset via its
Kaggle mirror, `marketneutral/quandl-wiki-prices-us-equites`. This is
the same dataset Quandl distributed for free until discontinuing
updates on 2018-04-11 (`quantopian/zipline` issue #2145, cited in prior
research) -- ~3,200 US tickers, EOD OHLCV + adjusted columns, frozen at
that date.

## Decision 1 -- Empirically verify real delisted coverage before trusting it (not a repeat of the pystock-data mistake)

The user ran real `grep`/`awk` commands against their own downloaded
`WIKI_PRICES.csv` (1.8GB, confirmed real via file size and content) and
reported back real output, which this ADR is built from -- not from
documentation or a hopeful reading of a README, the same discipline
`ADR-0123` applied when it rejected `pystock-data`.

Real, confirmed findings:

- Header (real, user-reported): `ticker,date,open,high,low,close,volume,
  ex-dividend,split_ratio,adj_open,adj_high,adj_low,adj_close,adj_volume`.
- `DELL` (Dell Inc., taken private by Michael Dell/Silver Lake): 6,388
  rows total. Real trading rows (`volume != 0`) run through
  **2013-10-29 at $13.84-13.86/share**. Dell's well-documented LBO
  closed on exactly that date at **$13.75/share**. The match between a
  real, independently-known corporate event's date and price and this
  dataset's own last real row is strong, concrete evidence this is
  genuine historical data, not fabricated or hopeful pattern-matching.
- `DTV` (DirecTV, acquired by AT&T 2015): 3,084 rows. `LNKD` (LinkedIn,
  acquired by Microsoft 2016): 1,399 rows. `TWX` (Time Warner, acquired
  by AT&T 2018): 6,554 rows. `YHOO` (Yahoo, acquired by Verizon 2017):
  5,332 rows. All confirmed present.
- `LEH` (Lehman Brothers), `BSC` (Bear Stearns), `WCOM` (WorldCom),
  `MER` (Merrill Lynch), `ENRN` (Enron), `MOT` (Motorola), `WMIH`
  (Washington Mutual reorg): **all absent (0 rows)**. This dataset's
  ~3,200-ticker universe was curated at some point well after these
  2001-2008-era failures; they were never added to begin with. This is
  a coverage-boundary gap, not evidence the present data is fake --
  distinguished explicitly here so this ADR does not overclaim.

## Decision 2 -- The dummy zero-volume tail is a confirmed scraper artifact, filtered by `volume == 0`, never guessed

Immediately after `DELL`'s last real trade (2013-10-29), the user's
`tail`/`awk` output showed repeating rows: `31.3,31.3,31.3,31.3,
volume=0.0`, starting 2014-04-16 and recurring sparsely through the
dataset's 2018-03-27 freeze date. $31.30 matches neither the $13.75
buyout price nor any real post-privatization quote -- this is a
scraper artifact (most likely a stale last-known-quote the underlying
feed kept returning after the real feed stopped), not real trading
data. `scripts/convert_quandl_wiki_prices_to_file_import_csv.py` drops
every row with `volume == 0.0`, based on this concrete, dated evidence
(exact transition point + exact price mismatch), not a guess -- a
genuine zero-volume day is not realistic for any security in this
project's own research universe.

## Decision 3 -- Convert into the EXISTING `LocalFileDataProvider` schema; no new provider/pipeline code

`data_infra.providers.file_import.LocalFileDataProvider` (Phase 31)
and `scripts/import_external_market_data.py` already implement exactly
the pipeline this data needs: one `{security_id}.csv` per symbol with
`date,open,high,low,close,volume` (required) and
`adj_close,adj_high,adj_low` (optional) -- built for exactly this kind
of externally-acquired, user-preprocessed dataset (`ADR-0034`
"external acquisition workflow"). No changes to that existing code were
needed. `scripts/convert_quandl_wiki_prices_to_file_import_csv.py`
(new) is the only new code: it streams the (potentially multi-GB) raw
WIKI file, extracts only the requested tickers, drops the confirmed
dummy tail, and writes the per-symbol CSVs this pipeline already
consumes.

A ticker requested but absent from the raw file (e.g. `LEH`) is
skipped with a warning, not fatal, unless *every* requested ticker is
missing -- matching this project's existing "missing_symbols" reporting
convention (`ingest_short_interest_data.py`/`import_external_market_data.py`
itself already report, rather than fail on, a request for a symbol
with zero real data).

## Decision 4 -- Bulk coverage check against the real S&P 500 removed-ticker list, not just 5 hand-picked names

Decision 1's evidence was 5 tickers checked by hand. This project
already has a real, previously-fetched list of every ticker that has
ever left the S&P 500 (`data/sp500_ticker_start_end.csv`, `fja05680/
sp500`, ADR-0120) -- 737 distinct tickers with a real `end_date`, 575
of them on or before this dataset's 2018-03-27 freeze date. This is
exactly the candidate set worth checking in bulk, rather than continuing
to spot-check names one at a time.

`scripts/check_wiki_prices_delisted_coverage.py` (new) streams the raw
`WIKI_PRICES.csv` once, keeps only rows for tickers in that removed-
ticker set, drops `volume == 0` dummy rows (Decision 2's filter), and
reports which candidate tickers have any real rows at all, each one's
real first/last date, and its recorded S&P 500 `end_date`(s) for
comparison -- the same DELL-style "does the real data's last date line
up with the real corporate event" check, done for every candidate at
once instead of one grep at a time. This session ran it against the
real, already-present `sp500_ticker_start_end.csv` to confirm it parses
correctly (735/737-ish candidates load without error); running it
against the actual `WIKI_PRICES.csv` still requires the account owner's
own environment (this sandbox never had that file) -- the real
coverage-count results are pending that run.

## Consequences

### Positive

- The first genuinely free source, with concrete verified evidence
  (not a guess, not a rejected hypothesis), of real historical prices
  for real delisted US securities -- partially reversing `ADR-0123`'s
  "no viable free source" conclusion for the specific window this
  dataset covers.
- Reuses the existing external-import pipeline unmodified; only a
  preprocessing converter was added, following the same "convert from
  a REAL observed sample, never a guessed format" discipline as
  `ADR-0125`'s FINRA converter.
- `source_name="quandl_wiki_prices_kaggle_mirror"` (honest, specific --
  never a generic default) becomes `Provenance.source` on every bar
  imported this way, so downstream REAL-data provenance checks
  (`run_long_horizon_validation.py`) can distinguish it from any other
  source.

### Negative / Trade-offs

- **Coverage is bounded and partial, not a general solution.** Only
  ~3,200 tickers, and evidently curated well after the 2001-2008 wave
  of failures -- Lehman, Bear Stearns, WorldCom, Enron, Washington
  Mutual, and likely many other historically important delistings are
  simply absent. This helps specifically with 2013-2018-era
  acquisitions/buyouts among tickers that happened to be in this
  dataset's universe; it does not give this project general
  survivorship-bias-free coverage across its full history or universe.
- **Frozen at 2018-03-27.** No delistings from 2018 onward (including
  this project's own real, current AVB removal from `ADR-0122`) are
  covered by this source at all -- that gap remains fully
  `ENVIRONMENT_BLOCKED`, unchanged from `ADR-0123`.
- The account owner acquired this file in their own environment; this
  sandboxed session never touched Kaggle or the raw file directly and
  cannot independently re-verify the dataset beyond the specific
  `grep`/`awk` output the user reported. If this dataset's shape
  changes (a different Kaggle re-upload, for instance), this converter
  would need re-verification against a fresh real sample, the same as
  any other external-format-dependent code in this project.
- The `volume == 0` filter is a heuristic justified by the one
  concrete case examined in depth (`DELL`) -- it was not independently
  re-verified against a second ticker's own real/dummy transition
  point. If a future real sample shows a genuine (non-artifact) zero-
  volume trading day for some illiquid security, this filter would
  incorrectly drop it; this is judged an acceptable risk for this
  project's own research-universe-scale (liquid, index-member-class)
  securities.
- The raw multi-GB `WIKI_PRICES.csv` file itself is never committed to
  this repository (third-party data, not code, far too large) -- the
  user must keep re-running the converter against their own local copy
  whenever they need a fresh set of symbols extracted.

## Tests

21 new tests total: 11 in `tests/data_infra/test_convert_quandl_wiki_
prices_to_file_import_csv.py`, using fixture rows shaped exactly like
the real `DELL`/`AAPL` rows the account owner reported this session --
including one true end-to-end test that pipes this script's output
directly into `scripts/import_external_market_data.py`, proving the
two scripts' schemas actually agree in practice; 10 in
`tests/data_infra/test_check_wiki_prices_delisted_coverage.py` for the
bulk coverage-check script (Decision 4).

## Status of Implementation at Time of This ADR

`scripts/convert_quandl_wiki_prices_to_file_import_csv.py` and
`scripts/check_wiki_prices_delisted_coverage.py` (both new, no network
call, pure CSV transforms). No changes to `data_infra/providers/
file_import.py` or `scripts/import_external_market_data.py` -- both
already supported this exact workflow. The real bulk coverage numbers
(how many of the 737 ever-removed S&P 500 tickers this dataset
actually covers) are pending the account owner running `check_wiki_
prices_delisted_coverage.py` against their own downloaded
`WIKI_PRICES.csv`.
