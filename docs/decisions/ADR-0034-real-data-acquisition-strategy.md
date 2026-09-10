# ADR-0034: Real Data Acquisition Strategy (Phase 31)

## Context

Phase 30's ADR-0033 already classified 7 candidate providers against 6
capability dimensions (REALISTIC/PARTIAL/INSUFFICIENT/UNKNOWN), sourced
from public documentation gathered via web search, never live-verified
(network to every provider host remains blocked in this environment).
Phase 31 re-frames that same evidence under the instruction's own
required vocabulary (`VERIFIED_BY_DOCUMENTATION`/
`VERIFIED_BY_ACTUAL_ACCESS`/`UNKNOWN`/`NOT_AVAILABLE`/
`ENVIRONMENT_BLOCKED`), extends the matrix to the additional columns
instruction section 29 requires, and -- most importantly -- commits to
one of the instruction's five decision-framework states (section 30)
and makes the external-acquisition workflow concrete and implemented
(instruction section 21), rather than only documented as an intention.

No new web research was performed this phase specifically to re-derive
facts ADR-0033 already gathered and cited; those citations are carried
forward by reference rather than re-fetched. What changed this phase
and is genuinely new: (1) the network re-verification against 8 hosts
(unchanged results, see the Phase 31 Addendum in
`docs/research/STRATEGY-VALIDATION-REPORT.md`), (2) the explicit
`ACCESS STATUS` column below (every single row is `ENVIRONMENT_BLOCKED`
in this session, which ADR-0033 did not tabulate as its own column),
and (3) an actually-implemented external-import pathway (Decision 3).

## Decision 1 -- Access status is uniform across every provider: `ENVIRONMENT_BLOCKED`

Re-verified this phase (instruction section 20): DNS resolves for all
three primary provider hosts (`api.tiingo.com`, `stooq.com`,
`openapi.tossinvest.com`), a raw TCP connect to port 443 succeeds
directly, and a request that bypasses the configured proxy still
returns `HTTP/2 403` with `x-deny-reason: host_not_allowed` and body
"Host not in allowlist... Add this host to your network egress
settings to allow access." An additional 5 candidate provider hosts
(`data.nasdaq.com`, `api.polygon.io`, `www.alphavantage.co`,
`financialmodelingprep.com`, `crsp.org`) all return the identical `403`
via the configured proxy path; two control hosts (`github.com`,
`pypi.org`) return `200` in the same run. `MARKET_DATA_API_KEY` remains
unset.

Per instruction section 20's required distinction: this is
**NETWORK_BLOCKED at the environment's own egress-allowlist layer**,
not `AUTHENTICATION_FAILED` (no credential was ever sent — the request
is rejected before reaching the provider), not `PROVIDER_DOES_NOT_SUPPORT_FEATURE`
or `DATASET_DOES_NOT_EXIST` (neither is determinable — no request ever
reaches the provider to answer either question), and not
`USER_ACCOUNT_LIMITATION` (there is no account/key in this session to
be limited). Every row's `ACCESS STATUS` in the matrix below is
therefore `ENVIRONMENT_BLOCKED`, uniformly, regardless of what that
provider's documentation claims -- this is a property of the session,
not of any one provider.

## Decision 2 -- Provider sufficiency matrix

| Capability | Tiingo | Stooq | Nasdaq Data Link (Sharadar) | Polygon.io | Alpha Vantage | Financial Modeling Prep | CRSP (via WRDS) |
|---|---|---|---|---|---|---|---|
| Historical prices | VERIFIED_BY_DOCUMENTATION | VERIFIED_BY_DOCUMENTATION | VERIFIED_BY_DOCUMENTATION (paid tier) | VERIFIED_BY_DOCUMENTATION | VERIFIED_BY_DOCUMENTATION | VERIFIED_BY_DOCUMENTATION | VERIFIED_BY_DOCUMENTATION |
| 2010 coverage | VERIFIED_BY_DOCUMENTATION (30+ yrs claimed) | UNKNOWN (depth per-symbol unconfirmed) | VERIFIED_BY_DOCUMENTATION (back to 1998, paid tier) | VERIFIED_BY_DOCUMENTATION (since ~2003-2004) | VERIFIED_BY_DOCUMENTATION (20+ yrs claimed) | UNKNOWN | VERIFIED_BY_DOCUMENTATION |
| Latest data | UNKNOWN (lag unconfirmed) | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN (institutional refresh cadence unconfirmed) |
| US equities | VERIFIED_BY_DOCUMENTATION | VERIFIED_BY_DOCUMENTATION | VERIFIED_BY_DOCUMENTATION | VERIFIED_BY_DOCUMENTATION | VERIFIED_BY_DOCUMENTATION | VERIFIED_BY_DOCUMENTATION | VERIFIED_BY_DOCUMENTATION |
| Delisted securities | NOT_AVAILABLE on free tier (metadata only, no dedicated feed found) | NOT_AVAILABLE | VERIFIED_BY_DOCUMENTATION, paid tier only | VERIFIED_BY_DOCUMENTATION (vendor claim) / UNKNOWN (independent reviews call coverage inconsistent) | NOT_AVAILABLE | VERIFIED_BY_DOCUMENTATION (dedicated endpoint documented, gated to paid) | VERIFIED_BY_DOCUMENTATION (purpose-built) |
| Permanent IDs | NOT_AVAILABLE (ticker-keyed) | NOT_AVAILABLE | UNKNOWN | UNKNOWN | NOT_AVAILABLE | UNKNOWN | VERIFIED_BY_DOCUMENTATION (PERMNO) |
| Ticker history | NOT_AVAILABLE (no endpoint found) | NOT_AVAILABLE | UNKNOWN | UNKNOWN | NOT_AVAILABLE | UNKNOWN | VERIFIED_BY_DOCUMENTATION |
| Corporate actions | VERIFIED_BY_DOCUMENTATION (integrated, Phase 20) | NOT_AVAILABLE (ADR-0028) | VERIFIED_BY_DOCUMENTATION, paid tier | UNKNOWN | VERIFIED_BY_DOCUMENTATION | UNKNOWN | VERIFIED_BY_DOCUMENTATION |
| Historical membership | NOT_AVAILABLE | NOT_AVAILABLE | NOT_AVAILABLE (no index-constituent-history evidence found) | NOT_AVAILABLE | NOT_AVAILABLE | NOT_AVAILABLE | VERIFIED_BY_DOCUMENTATION (equities product) |
| Point-in-time metadata | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | VERIFIED_BY_DOCUMENTATION |
| Bulk download | UNKNOWN | VERIFIED_BY_DOCUMENTATION (CSV download) | VERIFIED_BY_DOCUMENTATION | UNKNOWN | NOT_AVAILABLE (API-only, rate-limited) | UNKNOWN | VERIFIED_BY_DOCUMENTATION |
| API | VERIFIED_BY_DOCUMENTATION, integrated | VERIFIED_BY_DOCUMENTATION, integrated | VERIFIED_BY_DOCUMENTATION | VERIFIED_BY_DOCUMENTATION | VERIFIED_BY_DOCUMENTATION | VERIFIED_BY_DOCUMENTATION | NOT_AVAILABLE (file/query access via WRDS, not a public API) |
| Free availability | VERIFIED_BY_DOCUMENTATION (free tier exists, limits UNKNOWN) | VERIFIED_BY_DOCUMENTATION (free) | NOT_AVAILABLE for delisted coverage | NOT_AVAILABLE for delisted coverage | VERIFIED_BY_DOCUMENTATION (25 req/day, 5/min -- INSUFFICIENT for broad universe) | UNKNOWN | NOT_AVAILABLE |
| Paid availability | VERIFIED_BY_DOCUMENTATION | UNKNOWN | VERIFIED_BY_DOCUMENTATION | VERIFIED_BY_DOCUMENTATION | VERIFIED_BY_DOCUMENTATION | VERIFIED_BY_DOCUMENTATION | VERIFIED_BY_DOCUMENTATION (institutional subscription) |
| **Actual access verified** | **ENVIRONMENT_BLOCKED** | **ENVIRONMENT_BLOCKED** | **ENVIRONMENT_BLOCKED** | **ENVIRONMENT_BLOCKED** | **ENVIRONMENT_BLOCKED** | **ENVIRONMENT_BLOCKED** | **ENVIRONMENT_BLOCKED** (also: no WRDS credential exists in this session regardless of network) |
| Survivorship-aware (as actually usable by this project today) | NO -- price/corp-action only | NO | PARTIAL (paid tier only, unverified) | PARTIAL (paid tier only, unverified, delisted metadata quality disputed) | NO | PARTIAL (paid tier only, unverified) | YES (by design, if accessible) |

`UNKNOWN` is never upgraded to a more favorable label without an
actual verified response -- several cells above were `PARTIAL`-flavored
findings in ADR-0033 and are intentionally split here into more precise
`UNKNOWN` cells per capability rather than one blended per-provider
rating, since the instruction's five-label vocabulary does not have a
`PARTIAL` option.

## Decision 3 -- External acquisition workflow: designed AND implemented

Instruction section 21 asks for the external-acquisition workflow to
be "designed clearly," and section 31 lists "external import adapter"
as a legitimate implementation area. Rather than only documenting the
pipeline, this phase implements it:

- `src/data_infra/providers/file_import.py` -- `LocalFileDataProvider`,
  a `DataProvider` Protocol implementation that reads pre-downloaded,
  already-normalized CSV files from local disk instead of making any
  network call. It defines one explicit CSV schema
  (`date,open,high,low,close,volume[,adj_close][,adj_high][,adj_low]`
  -- the two optional adjusted-high/low columns added Session 36
  continued, alongside `PriceBar.adjusted_high`/`.adjusted_low`, see
  ADR-0103) and requires the
  caller to supply an honest `source_name` (e.g.
  `"nasdaq_data_link_sharadar"`, `"crsp"`) that becomes
  `Provenance.source` on every persisted bar -- never a hardcoded or
  guessed provider name. It deliberately does NOT attempt to parse any
  specific real provider's actual bulk-file format (CRSP's or Nasdaq
  Data Link's own export layout), since this project has never seen a
  real sample of one; that transformation is the user's own
  responsibility, external to this repository.
- `scripts/import_external_market_data.py` -- wires
  `LocalFileDataProvider` through the exact same
  `IngestionRunner`/`DataQualityFramework`/`DuckDBDataRepository`
  pipeline `ingest_real_market_data.py` already uses (Phase 1/4/20,
  unmodified), producing a manifest with the same reproducibility
  fields (`actual_data_start`/`actual_data_end`/`providers_used`/
  `missing_symbols`/`checksum`/`data_version`, Phase 30/31). Unlike
  `ingest_real_market_data.py`, this script makes NO network call at
  all, so it is (and is) directly exercised end-to-end by the automated
  test suite (`tests/data_infra/test_import_external_market_data_cli.py`)
  against real temporary CSV fixtures and a real on-disk DuckDB
  catalog -- the strongest test category this project's own
  conventions allow for a CLI script.

The resulting workflow:

```
external environment (user's own network access)
    -> provider/dataset acquisition (Tiingo, Nasdaq Data Link, CRSP, ...)
    -> user's own preprocessing into file_import's CSV schema
    -> one CSV file per security_id in a local directory
    -> scripts/import_external_market_data.py --source-name ... --data-dir ...
    -> LocalFileDataProvider + IngestionRunner (unmodified)
    -> DataQualityFramework validation (unmodified)
    -> DuckDBDataRepository / Parquet storage (unmodified)
    -> historical universe / Walk-Forward (unmodified)
```

No API key is ever read by this pathway (it makes no network call),
and none is written to git.

## Decision 4 -- Decision framework classification (instruction section 30)

Both apply simultaneously, at different layers, and neither is chosen
for convenience:

**D. ENVIRONMENT_BLOCKED** -- true for every provider tried, including
Tiingo/Stooq (already integrated). This is a property of this
sandboxed session, not of any provider's actual capability, and is the
binding constraint on real ingestion happening *from this session*
today.

**C. EXTERNAL_DATASET_REQUIRED** -- also true, independent of (D): even
setting the network block aside, no already-integrated or free-tier
provider (Tiingo, Stooq, Alpha Vantage free tier) supplies delisted
securities, permanent identity distinct from ticker, or historical
index/universe membership. Achieving the instruction's own stated goal
(a genuinely survivorship-bias-aware 2010-latest dataset) requires
either a paid tier of a documented provider (Nasdaq Data Link/Sharadar,
Polygon, Financial Modeling Prep -- all `UNKNOWN`/unverified for
delisted-data quality in this audit) or an institutional CRSP/WRDS
subscription, none of which exists in or is obtainable by this
session autonomously.

**Not chosen: A (SINGLE_PROVIDER_SUFFICIENT)** -- no evidence supports
this; every free/already-integrated provider is missing at least
delisted coverage and historical membership.
**Not chosen: B (MULTI_PROVIDER_REQUIRED) alone** -- combining
Tiingo+Stooq (already done, `FallbackDataProvider`, Phase 22) still
does not add delisted coverage or historical membership; more
providers of the *same* free-tier character would not close the gap.
**Not chosen: E (DATASET_NOT_AVAILABLE)** -- incorrect; CRSP-class data
demonstrably exists and is obtainable, just not by this session
autonomously (that is (C) and (D), not (E)).

## Consequences

- The single most useful next action (instruction section 41) is
  external: the user acquires real data from a source of their
  choosing (informed by Decision 2's matrix) in an environment with
  real network access, preprocesses it into `file_import`'s documented
  CSV schema, and runs `scripts/import_external_market_data.py`
  locally or in that external environment against this repository's
  code.
- This project should NOT spend a further phase adding more validation
  infrastructure while (C) and (D) remain unresolved (instruction
  section 41's explicit strategic priority). Decision 3's
  implementation is judged sufficient scope for this phase precisely
  because it is the last piece of *infrastructure* actually blocking
  an external import once real data exists -- everything downstream
  (quality validation, DuckDB storage, universe construction,
  Walk-Forward) was already correct and unmodified.
- `audit_survivorship` (`src/data_infra/universe.py`, Phase 31) gives
  any future real ingestion an immediate, honest
  FULLY_SUPPORTED/PARTIALLY_MITIGATED/CURRENT-UNIVERSE-ONLY/UNKNOWN
  classification instead of a bare "survivorship bias solved" claim
  the moment real data is imported -- proven this phase only against
  synthetic fixtures (see `tests/data_infra/test_survivorship_audit.py`).
