# ADR-0042: Fundamentals Data Source Selection (SEC EDGAR)

## Context

Phase 32's real diagnostics closed out three independently-motivated,
pre-committed rule-based hypotheses -- momentum score IC (mean_ic =
-0.0078), low-volatility factor IC (mean_ic = -0.0486), and
`trend_volatility`'s filter bucket-return spread (mean_spread =
-0.0078) -- against the real 40-symbol catalog. All three came back
null or negative (see `docs/research/STRATEGY-VALIDATION-REPORT.md`
Section G/Q3). The user then asked which direction better serves the
project: ML on the existing price/volume features, or a genuinely
different data source. The recommendation given (and accepted): a
different data source first, since ML on a feature space already shown
to carry near-zero information mostly adds model complexity without
adding information, and the sample this project has (40 symbols, ~13
years) is small for training a data-hungry model in the first place.
Fundamentals data (financial-statement line items) is the natural
candidate: it is a different information source than price/volume
entirely, independent of the three now-null hypotheses, and has an
established academic basis (value/quality factors) distinct from
momentum/low-volatility.

## Decision 1 -- Provider: SEC EDGAR (XBRL company facts API)

Selected over commercial fundamentals providers (Financial Modeling
Prep, Alpha Vantage's `OVERVIEW`/`EARNINGS` endpoints, Tiingo
fundamentals) for reasons specific to this project's existing
constraints and priorities, not a general claim that it is the best
fundamentals source for every use case:

- **Free with no API key**: SEC EDGAR's XBRL company-facts endpoint
  (`data.sec.gov/api/xbrl/companyfacts/CIK##########.json`) is a
  public US-government data source, no signup or credential required
  -- this project has already hit free-tier rate/coverage limits with
  every commercial price-data provider evaluated in ADR-0025/0033/0034;
  a fundamentals source with the same limitation would just move the
  problem rather than solve it.
- **Official, primary source**: every commercial fundamentals provider
  ultimately derives its numbers from the same SEC filings this API
  serves directly -- going to the primary source removes one layer of
  unverifiable vendor-side transformation.
- **Genuinely point-in-time-safe by construction**: each XBRL fact in
  the response carries its own `filed` date (the actual date the
  10-K/10-Q reporting it was filed with the SEC), distinct from `end`
  (the reporting period's end date). This project's entire
  point-in-time discipline (ADR-0004, `available_time` on every
  record) depends on knowing when a fact became knowable, not just
  what period it describes -- SEC EDGAR is one of the few sources that
  publishes this distinction as a first-class field rather than
  requiring it to be inferred or purchased separately (the
  price-data providers evaluated in ADR-0034 mostly do not expose an
  equivalent for fundamentals at all on their free tiers).
- **Well-documented, stable, long-standing public API** -- unlikely to
  disappear or change its free-tier terms, unlike a commercial vendor's
  free tier.

Trade-off accepted: EDGAR's `us-gaap` XBRL tags are raw filing-line
concepts (e.g. `Revenues`, `NetIncomeLoss`, `Assets`), not
pre-computed ratios (P/E, ROE, etc.) -- those must be derived from raw
concepts in a later stage, not fetched directly. This is judged
acceptable: deriving a ratio from two already point-in-time-safe raw
facts is straightforward and keeps the point-in-time property intact
end to end, versus trusting a vendor's own (unverifiable) ratio
computation.

## Decision 2 -- Access status: `ENVIRONMENT_BLOCKED`, uniformly, same as every prior provider

Re-verified this phase, mirroring ADR-0034's own methodology exactly:
a direct HTTPS request to `data.sec.gov` from this session's remote
execution environment returns `CONNECT tunnel failed, response 403`
at the configured egress proxy, with the proxy's own status report
recording `"kind": "connect_rejected", "detail": "gateway answered 403
to CONNECT (policy denial or upstream failure)"`. The same result was
obtained for `www.sec.gov`, `www.alphavantage.co`,
`financialmodelingprep.com`, and `stooq.com` in the same run -- this is
a property of this session's network egress allowlist, not of SEC
EDGAR specifically or of fundamentals data as a category. This is the
same `ENVIRONMENT_BLOCKED` finding ADR-0034 already established for
every price-data provider; it now applies to fundamentals providers
too, with no exception found.

Per ADR-0034's own required distinction: this is `ENVIRONMENT_BLOCKED`
at the egress-allowlist layer, not `AUTHENTICATION_FAILED` (SEC EDGAR
requires no credential at all), not
`PROVIDER_DOES_NOT_SUPPORT_FEATURE` (never reached), and not
`USER_ACCOUNT_LIMITATION` (no account exists to be limited).

**Update -- real access confirmed from the user's own environment,
same-day.** The user ran the exact `curl` command in this ADR's own
"Next step" section from their own machine (not this remote execution
environment) and relayed the response back verbatim:

```
{"cik":320193,"entityName":"Apple Inc.","facts":{"dei":{"EntityCommonStockSharesOutstanding":{"label":"Entity Common Stock, Shares Outstanding","description":"...",...
```

This is the first `VERIFIED_BY_ACTUAL_ACCESS` result (not merely Tier
2 documentation) this project has obtained for *any* market-data
provider, price or fundamentals, across every prior phase (ADR-0025
through ADR-0041 all recorded `ENVIRONMENT_BLOCKED`/Tier 2 only). Two
things are now confirmed, not merely assumed:

1. **`data.sec.gov` is reachable** -- from the user's environment,
   not this session's. The `ENVIRONMENT_BLOCKED` finding above is
   therefore precisely scoped: it describes this remote execution
   container's own egress allowlist, never SEC EDGAR's actual
   availability.
2. **The top-level response shape matches this module's Tier 2
   assumption** -- `cik`, `entityName`, `facts` -> taxonomy (`dei`
   shown here; `us-gaap`, the taxonomy `sec_edgar.py` actually reads,
   not yet confirmed at the field level -- see the follow-up request
   below) -> concept -> `label`/`description`/`units`, exactly the
   nesting `normalize_company_facts` was written against.

**Second update -- entry-level shape confirmed too, same day.** The
user ran the follow-up fetch this ADR's "Next step" section requested
(`facts.us-gaap.Assets.units.USD`, the most recent entry) and relayed
the real result back verbatim:

```json
{
  "end": "2026-06-27",
  "val": 383266000000,
  "accn": "0000320193-26-000020",
  "fy": 2026,
  "fp": "Q3",
  "form": "10-Q",
  "filed": "2026-07-31",
  "frame": "CY2026Q2I"
}
```

Every field `normalize_company_facts` reads (`end`, `val`, `accn`,
`fy`, `fp`, `form`, `filed`) is present with the assumed type and
meaning; `start` is absent, exactly as expected for `Assets` (a
balance-sheet/instant concept, not a duration concept like `Revenues`)
-- matching `FundamentalRecord.period_start`'s own documented "`None`
for instant concepts" contract precisely. The one field present in the
real response but not read by `normalize_company_facts` (`frame`, an
EDGAR-internal cross-period grouping label) is harmless to ignore --
`normalize_company_facts` never assumed a closed field set, only that
the fields it does read exist with the right shape, and they do.

**This closes out ADR-0042's own "still unconfirmed" gap.**
`SecEdgarFundamentalsProvider`'s parsing contract is now
`VERIFIED_BY_ACTUAL_ACCESS` end to end (top-level shape and
entry-level fields both), not merely Tier 2 documentation -- the first
time this project has reached that status for any provider integration
without first shipping to a live ingestion run. No code change is
needed in `sec_edgar.py`; the Tier 2 assumptions it shipped with
(Decision 3, below) turned out correct on first real contact.

## Decision 3 -- Build the provider now against Tier 2 documentation, same pattern as `TiingoDataProvider`

Rather than wait for network access that may never come from inside
this specific environment, `SecEdgarFundamentalsProvider` (this phase)
is implemented and tested now, against publicly documented Tier 2
knowledge of EDGAR's response shape, exactly mirroring how
`TiingoDataProvider` (Phase 20) was built and shipped before any real
Tiingo response was ever seen from this environment. Every parsing
assumption is isolated in `normalize_company_facts` alone (see that
module's own "Honesty about evidence tier" docstring), so it can be
corrected in one place once a real response is available -- the same
discipline `tiingo.py` already established, which this project has
since carried through several phases without needing structural
rework once real access was later confirmed for price data.

New code, all additive:
- `src/data_infra/fundamentals_models.py` -- `FundamentalRecord`, a new
  domain model parallel to `PriceBar`/`CorporateAction`, with the
  point-in-time-critical constraint that `available_time` (the actual
  filing date) can never be earlier than `period_end` (the reporting
  period), enforced in `__post_init__`.
- `src/data_infra/providers/sec_edgar_config.py`,
  `sec_edgar_transport.py`, `sec_edgar.py` -- config/transport/provider
  triad mirroring `tiingo_config.py`/`tiingo_transport.py`/`tiingo.py`'s
  existing shape. `SecEdgarFundamentalsProvider` deliberately does NOT
  implement `data_infra.provider.DataProvider` (see `sec_edgar.py`'s
  module docstring for why that Protocol's shape does not fit a
  filings-based source).
- 42 new tests across `tests/data_infra/test_fundamentals_models.py`,
  `test_sec_edgar_transport.py`, `test_sec_edgar_config.py`,
  `test_sec_edgar_provider.py` -- no test ever reaches the real network
  (`urllib.request.urlopen` is monkeypatched throughout), same
  discipline as every existing provider test in this repository.

## Decision 4 -- Not yet built this phase (deferred, explicitly)

- **Ingestion/storage wiring**: no `FundamentalRepository` or DuckDB
  persistence layer exists yet -- `data_repository.py`'s existing
  schema is price/corporate-action-shaped. Deferred until real EDGAR
  access exists to know what's actually needed, avoiding the same
  speculative-schema risk ADR-0039 already flagged for portfolio
  optimization.
- **Ratio derivation** (P/E, ROE, debt/equity, etc.) from raw
  `FundamentalRecord`s, and any actual value/quality factor signal
  built on top -- out of scope until the raw data itself is real.
- **Which concepts to fetch for the 40-symbol universe** -- a short,
  deliberately chosen set (e.g. `Revenues`, `NetIncomeLoss`, `Assets`,
  `Liabilities`, `StockholdersEquity`) is the obvious starting point
  but is not fixed here; left for whoever runs real ingestion.

## Verification status: complete

Both open items from the original "Next step" section are now
resolved (see the two Decision 2 addenda above) --
`VERIFIED_BY_ACTUAL_ACCESS` for both reachability and the parsing
contract, from the user's own environment, same day this ADR was
written. This session's own `data.sec.gov` access remains
`ENVIRONMENT_BLOCKED` regardless (a property of this container, not of
SEC EDGAR).

## Decision 5 -- Storage + ingestion CLI, built same day

With the provider verified, the user asked to proceed. Built:

- `src/storage/fundamentals_repository.py` -- `DuckDBFundamentalsRepository`,
  a persistent, point-in-time-safe store for `FundamentalRecord`s.
  Backed by a new `fundamental_records` DuckDB table (`schema.py`),
  not Parquet -- same low-volume, point-lookup/filter-heavy criterion
  ADR-0010 section 1 already applied to Benchmark data.
  `get_fundamentals(security_id, concept, as_of_time, ...)` applies
  the same `available_time <= as_of_time` look-ahead guard
  `DuckDBDataRepository.get_bars`/`get_corporate_actions` already
  apply for prices, extended to fundamentals' own point-in-time field.
  `latest_known_value(...)` additionally resolves ties on `period_end`
  toward the most-recently-*filed* record (`available_time` DESC) --
  the practical query a point-in-time-safe feature actually needs
  ("the latest value we could have known as of this moment"), distinct
  from `get_fundamentals`'s full, unresolved history (a period can
  legitimately have more than one filing, e.g. an original 10-Q and a
  later restatement).
- `scripts/ingest_fundamentals_data.py` -- real ingestion CLI, mirrors
  `ingest_real_market_data.py`'s structure and discipline exactly
  (never reads wall-clock time; `--user-agent` is required with no
  silent default, since SEC's fair-access policy needs a genuine
  contact string; writes a reproducibility manifest with a content
  checksum). Resolves each universe symbol's CIK via
  `provider.fetch_ticker_map`/`resolve_cik`, then fetches and persists
  a short default concept set (`Revenues`, `NetIncomeLoss`, `Assets`,
  `Liabilities`, `StockholdersEquity`) via `SecEdgarFundamentalsProvider`.
  Like the price-ingestion script, this one is never imported or
  executed by the automated test suite (it makes a real network call)
  -- verified instead by AST/source-text structural tests
  (`tests/data_infra/test_ingest_fundamentals_data_wiring.py`), the
  same discipline `test_ingest_real_market_data_wiring.py` already
  established.
- 22 new tests (15 for the repository -- persistence/restart,
  idempotency, the look-ahead guard, `period_end` range filtering,
  `latest_known_value`'s tie-break behavior, `None`/set `period_start`
  round-tripping; 7 structural tests for the ingestion script). Full
  suite: 1944 passed.

## Decision 6 -- Real ingestion run against the 39-symbol universe, and a real ticker->CIK resolution failure it surfaced

The user ran `ingest_fundamentals_data.py --universe RESEARCH_UNIVERSE`
from their own environment. Result: 39/39 symbols resolved a CIK, 0
`TransientProviderError`/`PermanentProviderError` failures,
**28,672 total `FundamentalRecord`s persisted** -- the first real
fundamentals data this project has ever stored. (`RESEARCH_UNIVERSE`
is 39 tradeable symbols, not 40 -- prior phases' "40-symbol universe"
phrasing included `SPY`, the benchmark, tracked separately and
deliberately excluded from fundamentals ingestion since an ETF has no
`us-gaap` financial-statement concepts to speak of.)

Per-symbol record counts ranged ~200-1100, except **XOM: 14 records**,
a stark outlier. Investigated live (not assumed):

1. `resolve_cik("XOM", ticker_map)` returned CIK `2115436`, whose
   `entityName` is **"ExxonMobil Holdings Corp"**, not "Exxon Mobil
   Corporation" -- and that CIK's `company_tickers.json` entry is the
   *only* one for ticker `XOM` (no simple duplicate-ticker collision).
2. Fetching that CIK's company facts directly confirmed the low count
   is real: only 4 `Revenues` entries exist under it.
3. Checking CIK `0000034088` (Exxon Mobil's long-standing, widely
   known CIK -- flagged explicitly as an *unverified* recollection
   before checking, per this project's evidence-tier discipline)
   confirmed the hypothesis: `entityName: "Exxon Mobil Corporation"`,
   **127 `Revenues` entries** -- the real multi-decade history.

**Root cause, OBSERVED not merely inferred**: at some point Exxon
Mobil underwent a holding-company reorganization -- a new legal entity
was created, given a newly-issued CIK, and SEC's *current*
`company_tickers.json` now maps ticker `XOM` to that new entity, which
has only filed a handful of times since its creation. The operating
company's real, decades-deep filing history sits under its own
CIK, permanently orphaned from the ticker as far as the *current*
ticker map is concerned. `resolve_cik` did exactly what it was built
to do (resolve a ticker via SEC's current map) -- the map itself no
longer points to the CIK with the history a naive "ticker -> current
CIK -> fetch" pipeline needs.

**This is not a new category of problem for this project.** It is
structurally the same failure mode ADR-0032 (Phase 29) already
documented for *price* data: a ticker's *current* identity mapping can
silently discontinue from the entity that actually carries the
historical record, and any pipeline that resolves identity from only
the current mapping will silently miss (or misattribute) history
across that discontinuity. ADR-0032 built survivorship-aware
membership tracking for price data; fundamentals data now has the
same class of gap, unaddressed by anything built so far.

**What was fixed this phase (narrow, not general)**: `--cik-overrides
SYMBOL:CIK` (e.g. `--cik-overrides XOM:0000034088`), checked before
`resolve_cik` for that symbol. The per-symbol manifest entry now also
records `cik_source` (`"ticker_map"` vs `"override"`) so a future
reader can tell which symbols needed manual correction without
re-deriving it. This is a manual escape hatch, not an automatic fix --
there is no general, reliable way to detect "this ticker's current CIK
has anomalously little history relative to how long this company has
plausibly existed" without either a hardcoded rule (fragile, and this
project's own discipline against unjustified speculative machinery
argues against building one on a sample of one) or a genuinely
different data source for entity-identity history (e.g. SEC's own
former-name/CIK-history endpoints, not yet investigated).

**Honest scope of what was and wasn't checked**: only XOM's anomaly
was investigated, because it was the one dramatic enough (14 vs.
~200-1100) to be visible by eye in a simple record-count comparison. A
less extreme version of the same problem -- a company whose holdco
reorg happened, say, 5 years into the data window instead of last year
-- would produce a record count still "in range" and would NOT have
been caught by this check. **The other 38 symbols have NOT been
individually verified to be free of this issue** -- their more
plausible-looking counts are evidence of absence only in the weak
sense that nothing this crude a check can catch was visible, not a
confirmation that no subtler version of the same problem exists among
them. This is recorded as an explicit, unresolved caveat, not
smoothed over.

## Decision 7 -- a second, more serious real bug: `source_record_id` collided across periods within the same filing

The XOM correction re-run (`--symbols XOM --cik-overrides
XOM:0000034088`) printed "771 records persisted", but a direct DB
query afterward found only **317** rows actually stored for XOM --
less than half. Investigated live, not assumed:

`normalize_company_facts`'s `Provenance.source_record_id` was built as
`f"{security_id}:{concept}:{accn or entry['end']}"` -- keyed only on
the filing's accession number (`accn`), never the period the entry
actually describes. A single 10-K or 10-Q routinely reports the *same*
concept for *more than one period at once* (comparative figures --
e.g. a balance sheet showing both the current and prior fiscal
year-end, or a 10-Q showing both the current quarter and
year-to-date), all under the identical `accn`. Every one of those
period-distinct entries collapsed onto the same natural key, so
`DuckDBFundamentalsRepository.add_fundamental`'s `ON CONFLICT (
provenance_source_record_id) DO NOTHING` silently kept only whichever
period-entry was processed first per `(concept, accn)` and dropped
every other period sharing that filing -- a real, silent data-loss bug,
not a hypothetical one; XOM's own 771 -> 317 collapse is the direct,
measured evidence.

**This affected every symbol ingested in Decision 6's run, not just
XOM.** XOM's anomaly was caught by chance (this ADR was already
mid-investigation into XOM for the unrelated CIK issue) -- every other
symbol's per-symbol counts reported in Decision 6 are undercounts of
what real distinct-period data actually exists for them, by however
much of their history XBRL reports as multi-period entries within one
filing (plausibly common for most symbols, though not separately
measured per symbol).

**Fix**: `source_record_id` now includes `unit`, `accn`, `end`, and
`start` -- `f"{security_id}:{concept}:{unit}:{accn}:{entry['end']}:
{entry.get('start') or ''}"` -- so two entries can only collide on this
key if they are the identical (concept, unit, filing, period) tuple,
which is the correct idempotency boundary (re-ingesting the same real
fact twice should still no-op; two distinct real facts must never
collide). 2 new regression tests in
`tests/data_infra/test_sec_edgar_provider.py`
(`TestSameAccnMultiplePeriodsAreAllPreservedNotCollapsed`) construct
exactly this same-accn-different-period shape and assert both periods
survive with distinct `source_record_id`s -- a fixture the original
test suite never exercised (every existing fixture entry happened to
use a distinct `accn` per period, which is why this shipped
undetected in Decision 5/6). Full suite: 1950 passed.

**Consequence for already-ingested data**: this fix only changes
future ingestion; it does not repair rows already persisted under the
old, collapsed key. **All 39 symbols' existing local data (from
Decision 6's run) is undercounted and should be re-ingested from
scratch** -- the pragmatic path is deleting the local `data/
fundamentals_data` directory and re-running the full 39-symbol
ingestion once more, now with both fixes in place
(`--cik-overrides XOM:0000034088` and the corrected key), rather than
attempting a partial in-place repair.

## Decision 8 -- clean full re-ingestion, confirmed

The user deleted the local DB and re-ran the full 39-symbol ingestion
with both Decision 6/7 fixes in place (`--cik-overrides
XOM:0000034088`, corrected `source_record_id`). Result: 39/39 CIKs
resolved, 0 provider errors, XOM at **771 records** (matching the
independently curl-verified real figure from Decision 6's
investigation -- neither the wrong-CIK 14 nor the key-collision-
collapsed 317), **29,429 total records**. The per-symbol counts printed
during the run were independently summed and matched the script's own
reported total exactly (29,429 == 29,429) -- an inexpensive
cross-check that the manifest's arithmetic is internally consistent,
not just self-reported.

This is the first time this project has held a **verified-clean**
(both known bugs fixed, one full-universe pass, printed totals
independently checked) set of real fundamentals data. It is not
proof no further data-quality issue exists (see the still-open
identity-continuity caveat below), only that the two specific,
confirmed defects found this phase are actually fixed in what is now
stored, not merely fixed in code with stale bad data still sitting
underneath.

## What's still not built

Concept selection (which `us-gaap` tags to fetch) is a starting
default, not fixed for all time -- `--concepts` overrides it. Ratio
derivation (P/E, ROE, debt/equity, etc.) from raw `FundamentalRecord`s,
and any actual value/quality factor signal built on top of them, are
the natural next step now that clean real data exists (Decision 8) --
not yet started. A systematic per-symbol identity-continuity check
(the general version of what caught XOM's CIK issue -- Decision 6's
own caveat that the other 38 symbols were never individually verified
free of a subtler version of the same holdco-reorg problem still
stands) also remains unbuilt. Any future fundamentals-based signal
evaluation must reuse `strategy_research.locked_windows.
overlaps_any_locked_window` against TEST-1 exactly as the rule-based
research this phase followed on from already does (RULE 0.8) -- this
was designed generally in ADR-0041/`ML-RESEARCH-PROTOCOL.md` and
applies to fundamentals signals with no special-casing needed.
