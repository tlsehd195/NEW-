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

Still unconfirmed: the exact field names inside one `units` entry
(`end`/`start`/`val`/`accn`/`fy`/`fp`/`form`/`filed`) that
`normalize_company_facts` actually parses -- the relayed snippet was
truncated by `head -c 500` before reaching any `us-gaap` concept's
`units` array. A follow-up fetch targeting a `us-gaap` concept
directly (e.g. `Assets` or `Revenues`) is needed before this can be
upgraded from "top-level shape confirmed" to "full parsing contract
confirmed."

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

## Next step (requires the user's own network-capable environment) -- reachability done, entry-level shape still open

Reachability is now confirmed (see the Decision 2 addendum above).
What remains, still cheap and still requiring the user's own
environment (this session's own `data.sec.gov` access stays blocked
regardless): confirm the exact field names inside a `us-gaap` concept's
`units` array, since that is the part `normalize_company_facts`
actually parses record-by-record and the truncated first fetch never
reached it.

```
curl -sS -A "research-project contact@example.com" \
  "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json" \
  -o /tmp/aapl_facts.json
python3 -c "
import json
d = json.load(open('/tmp/aapl_facts.json'))
entry = d['facts']['us-gaap']['Assets']['units']['USD'][-1]
print(json.dumps(entry, indent=2))
"
```

If that one entry has `end`, `val`, `accn`, `fy`, `fp`, `form`, and
`filed` keys (with `start` present for a duration concept like
`Revenues` but absent for an instant one like `Assets`, per XBRL's own
distinction), `normalize_company_facts`'s parsing contract is fully
confirmed against real data, not just its top-level shape. Per SEC's
fair-access policy, the `User-Agent` string must be a genuine
descriptive contact -- the placeholder above must be replaced with a
real one before any sustained use, matching `SecEdgarConfig.
user_agent`'s own docstring.
