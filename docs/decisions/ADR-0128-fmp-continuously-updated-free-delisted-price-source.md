# ADR-0128: Financial Modeling Prep — A Second, Continuously-Updated Free Delisted-Price Source (Covering the Post-2018 Window)

**Status:** Accepted
**Date:** 2026-09-12
**Deciders:** Claude Code (session continued), pending project owner review
**Related documents:** `docs/decisions/ADR-0126-quandl-wiki-prices-free-delisted-price-source.md`,
`docs/decisions/ADR-0127-post-2018-delisted-price-data-still-blocked.md`

---

## Context

`ADR-0127` concluded Yahoo Finance and Stooq were both empirically
rejected as free sources for tickers delisted after WIKI Prices'
2018-03-27 freeze (`ADR-0126`). Continuing the search, `Financial
Modeling Prep` (FMP) turned up two real, free-tier, API-key-based
endpoints (no anti-bot browser gate, unlike Stooq/Macrotrends -- both
of which were also tried this round and rejected for the same
Cloudflare/proof-of-work reasons as `ADR-0127`):

- `stable/delisted-companies` -- a list of recently delisted companies.
- `stable/historical-price-eod/full?symbol=...` -- real EOD OHLCV.

## Decision 1 -- Empirically verify real coverage, not just documentation, before trusting it

The account owner tested both endpoints directly with a real, free
API key. Real, observed results (not guessed from FMP's docs):

- `delisted-companies` (legacy `v3` version): **`404`-equivalent
  `Error Message` -- legacy endpoints were retired 2025-08-31.** The
  current path is under `stable/`.
- `stable/delisted-companies?page=0`: real, current data (entries dated
  as recently as 2026-09-09/2026-12-30 -- this list is continuously
  updated, unlike WIKI Prices' 2018 freeze). **`page` is capped at `0`
  on the free plan** (`HTTP 402 Payment Required` for `page=1`) --
  confirmed real, not guessed -- so the free tier can only see the
  ~100 MOST RECENT delistings this way, not the full historical list.
- `stable/historical-price-eod/full?symbol=ATVI` (Activision Blizzard,
  acquired by Microsoft, delisted 2023-10-18): **real price data
  returned.** Real last trade **2023-10-12, close $94.42, volume
  7,323,451** -- Microsoft's acquisition closed **2023-10-13**, one day
  later, an even tighter match than `DELL`'s own confirming evidence in
  `ADR-0126`. Rows after that are an IDENTICAL `open=high=low=close=
  94.42, volume=0` flat-fill -- the exact same dummy-tail artifact
  `ADR-0126` found in WIKI Prices, confirmed independently in a second,
  unrelated data source.
- Without explicit `from`/`to` params, the endpoint defaults to
  roughly the last 5 years from TODAY's date (not from the ticker's own
  history) -- confirmed by the returned window starting almost exactly
  5 years before the request date (2026), not near the company's real
  founding. Passing `from=1990-01-01&to=2023-10-20` returned **5,000
  rows, real data 2003-12-10 through 2023-10-20** -- ~20 years of
  history, evidently truncated at a fixed row cap (5,000) rather than
  the ticker's true full history, but still far more than what
  `ADR-0126`'s window (frozen at 2018) alone can offer for this ticker.
- Free plan: 250 requests/day, 500MB/30-day rolling bandwidth cap
  (confirmed via FMP's own current FAQ).

## Decision 2 -- Don't rely on FMP's own delisted-companies list; reuse this project's own S&P 500 removal data instead

Because `page` is capped at `0` on the free plan (Decision 1), FMP's
own list endpoint cannot enumerate the full historical population of
delisted tickers for free. This is not actually a blocker: this
project already has a real, comprehensive candidate list for exactly
this purpose -- `data/sp500_ticker_start_end.csv` (`fja05680/sp500`,
`ADR-0120`), the same source `ADR-0126`'s bulk coverage check used.
`scripts/fetch_fmp_delisted_prices.py` (new) takes `--since` (intended
as `2018-03-28`, the day after WIKI Prices' own freeze) and checks
every S&P 500 ticker with a real `end_date` on/after that date -- 195
such tickers, per this session's own earlier count -- directly against
FMP's `historical-price-eod/full` endpoint, one real HTTP request per
candidate (well under the 250/day budget).

## Decision 3 -- Classify genuine delisting the same way `ADR-0126` Decision 5 does, for consistency across sources

FMP's dummy-tail artifact (Decision 1) is filtered by the identical
`volume == 0` rule `ADR-0126` established, and the same "is the real
data's last date within 90 days of a real S&P 500 removal date"
heuristic (`ADR-0126` Decision 5) classifies genuine delistings vs.
tickers that simply left the index and kept trading -- implemented in
`data_infra.providers.fmp_delisted_price_import.is_likely_genuine_
delisting`, sharing its exact threshold and semantics with `check_wiki_
prices_delisted_coverage.py`'s own function so the two sources'
results are directly comparable, never silently using a different bar
for one source than the other.

## Decision 4 -- No adjusted-price columns; reuse the existing `LocalFileDataProvider` schema unmodified

FMP's response has no split-adjusted price fields at all (`vwap`/
`change`/`changePercent` instead, none of which is a split-adjusted
price) -- `to_file_import_row` leaves `adj_close`/`adj_high`/`adj_low`
blank, never fabricating them from `vwap`, the same "never mislabel a
different metric as an optional field" discipline `ADR-0125` applied
to FINRA's `averageShortShareNumber`. As with `ADR-0126`, no changes
were needed to `data_infra/providers/file_import.py` or `scripts/
import_external_market_data.py` -- both already support this exact
per-symbol CSV shape.

## Consequences

### Positive

- A second, real, free, **continuously-updated** source for delisted-
  ticker prices -- unlike `ADR-0126`'s WIKI Prices (frozen 2018-03-27),
  this source can in principle cover delistings up to and including
  the present day, closing exactly the gap `ADR-0127` left open.
- Confirmed via two independent real corporate events now (`DELL`'s
  2013-10-29 LBO close in `ADR-0126`, and `ATVI`'s 2023-10-13
  Microsoft acquisition close here) that the "real data ends within
  days of the real delisting event" signature reliably distinguishes
  genuine free-tier delisted-ticker coverage from a currently-listed-
  tickers-only snapshot -- this project's empirical test methodology
  (established rejecting `pystock-data` and the Kaggle "Huge Stock
  Market Dataset" mirror) generalizes cleanly to a new source.
- Reuses this project's own already-real S&P 500 removal data
  (`ADR-0120`) as the candidate list, avoiding the free tier's `page`
  cap on FMP's own delisted-companies endpoint entirely.

### Negative / Trade-offs

- **Coverage is still bounded to S&P 500 constituents that later left
  the index**, exactly like `ADR-0126`'s own candidate set -- a
  delisted ticker that was never an S&P 500 member is not checked by
  this script either. A more exhaustive search would need a broader
  candidate list this project does not currently have.
- **250 requests/day free-tier limit.** Checking all 195 post-2018
  candidates fits in one day, but re-checking regularly (e.g. to catch
  newly-delisted tickers) consumes budget against the same daily cap
  other future FMP usage would need.
- **History per ticker is capped (observed 5,000 rows without an
  explicit narrower `from`/`to`), not necessarily a company's true full
  history** -- acceptable for this project's purposes (which need
  prices up to and through the delisting event, not necessarily the
  company's entire multi-decade history), but disclosed here rather
  than assumed unlimited.
- Real coverage counts (how many of the 195 post-2018 candidates FMP
  actually has real data for, and how many of those classify as
  genuine delistings) are pending the account owner running `scripts/
  fetch_fmp_delisted_prices.py` for real -- not yet measured as of this
  ADR.
- The account owner's real FMP API key was pasted into this
  conversation multiple times while testing. It is a free-tier,
  read-only-scoped key (no write/billing capability), so the practical
  risk is low, but as with the FINRA OAuth token earlier this session
  (`ADR-0125`'s related conversation), rotating it via FMP's dashboard
  is a reasonable precaution -- this session never stored or reused
  the key itself beyond relaying it back in example commands.

## Tests

13 new tests (`tests/data_infra/test_fmp_delisted_price_import.py`),
using fixture rows shaped exactly like the real ATVI response the
account owner fetched this session (real values, not invented).
`scripts/fetch_fmp_delisted_prices.py` itself makes real network
calls and is therefore not exercised by the automated test suite,
matching `fetch_sp500_index_history.py`'s own precedent -- its
argument parsing and no-API-key fail-closed path were manually
verified this session (`--help` output, and confirmed `FATAL: no API
key given` with a nonzero exit when no key is supplied).

## Status of Implementation at Time of This ADR

`src/data_infra/providers/fmp_delisted_price_import.py` (new, pure, no
network) and `scripts/fetch_fmp_delisted_prices.py` (new, real network
calls, never test-suite-executed). No changes to `data_infra/providers/
file_import.py` or `scripts/import_external_market_data.py`. Real bulk
coverage results and actual ingestion (mirroring `ADR-0126` Decision 6)
are the next step, pending the account owner running this script.
