# Market Data Provider -- Operations

Phase 20, universe superseded in Phase 22 (see below). Companion to
`docs/decisions/ADR-0025-market-data-provider-selection.md` (the *why*
for provider selection) and `docs/decisions/ADR-0028-us-longterm-paper-trading-operating-model.md`
(the *why* for the Phase 22 universe/strategy/operating-model
decisions); this document is the *what/how*: the pilot universe, the
credential this provider needs, and what remains unverified.

## Provider

**Primary: Tiingo** (`src/data_infra/providers/tiingo.py`,
`TiingoDataProvider`, implementing `data_infra.provider.DataProvider`
unmodified). Requires an API key in the environment variable
`MARKET_DATA_API_KEY` (already reserved in `.env.example` since Phase
1) -- **not set, not requested from the user this phase.** No real
network call has been made to Tiingo from this environment; see
ADR-0025's "Honest evidence-access constraint" section.

**Secondary/fallback: Stooq** -- `src/data_infra/providers/stooq.py`,
`StooqDataProvider`, implemented in Phase 22 against the same
`DataProvider` Protocol (see ADR-0028 section on Stooq for the exact
Tier 2 evidence basis and its real limitations: no corporate-action
feed, CSV rather than JSON, unauthenticated). Selects between Tiingo
and Stooq via `data_infra.providers.fallback.FallbackDataProvider`
(Phase 22, additive) -- primary-fails-try-secondary, with every
resulting record's `Provenance.source` naming which provider actually
answered, never silently presenting a fallback result as if the
primary had succeeded.

## Pilot Universe (Phase 22 -- supersedes Phase 20's list for Paper Trading)

Phase 20 originally selected a 16-symbol universe optimized for
exercising corporate-action edge cases (including GE specifically for
its reverse-split history). Phase 22's instruction specifies a
**different, fixed 16-symbol Paper Trading universe** directly --
today's actual large-cap composition rather than a
corporate-action-edge-case-optimized set. This document now treats the
Phase 22 list below as the authoritative **default Paper Trading
universe**; Phase 20's original list and rationale are kept below for
reference/history and remain valid for point-in-time/corporate-action
*testing* purposes (that test coverage lives in synthetic fixtures, not
real ingested data, so losing GE's real-world reverse-split example
from the default universe does not reduce actual test coverage).

**Phase 22 default Paper Trading universe (fixed for now; expansion is
a future phase's decision, per instruction section 4):**

| Symbol | Sector (approximate) |
|---|---|
| AAPL | Technology |
| MSFT | Technology |
| NVDA | Technology / Semiconductors |
| AMZN | Consumer Discretionary / Internet |
| GOOGL | Communication Services / Internet |
| META | Communication Services / Internet |
| AVGO | Technology / Semiconductors |
| TSLA | Consumer Discretionary / Automotive |
| JPM | Financials |
| V | Financials / Payments |
| MA | Financials / Payments |
| COST | Consumer Staples / Retail |
| WMT | Consumer Staples / Retail |
| JNJ | Healthcare |
| XOM | Energy |
| SPY | Benchmark ETF (S&P 500 proxy, not part of the equity universe itself) |

**Honest limitation carried over from Phase 20, unchanged**: no
provider has real network access verified from this environment for
any of these 16 symbols (Tiingo or Stooq) -- see "What remains
UNKNOWN" below. This list defines what *would* be ingested once access
exists; it does not itself constitute ingested data.

### Phase 20's original pilot universe (historical, kept for reference)

10-20 US large-caps was Phase 20's instructed range. That document
selected **15 equities + 1 benchmark ETF (SPY)** = 16 symbols, chosen
against these criteria (not popularity):

- **Liquidity**: every symbol is a mega/large-cap S&P 500 constituent
  with consistently high daily volume -- none should ever produce a
  "insufficient volume to compute a reference price" data-quality
  issue.
- **Long historical data availability**: every symbol has been
  continuously listed for decades, avoiding the "how does point-in-time
  ingestion behave for a security that didn't exist yet" edge case
  (a real question, but not this pilot's purpose) and giving a long
  enough history to meaningfully test the point-in-time/corporate-action
  machinery over many real historical events.
- **Corporate action history**: every symbol has a real, documented
  history of at least one stock split and regular dividends (several
  have decades of consecutive dividend payments) -- picked
  specifically so the pilot ingestion actually exercises
  `CorporateActionType.SPLIT`/`DIVIDEND`, not just price bars with an
  empty corporate-action table.
- **Sector representativeness**: spread deliberately across GICS
  sectors (not all technology) so no single sector's data
  characteristics (e.g. tech's higher volatility) dominates any later
  Paper Trading or research use of this pilot data.
- **Stable ticker history**: no symbol in this list has undergone a
  ticker-symbol change in a way that would complicate this pilot
  (`CorporateActionType.TICKER_CHANGE` handling is left for a
  future pilot expansion, deliberately not exercised here).

| Symbol | Sector | Rationale |
|---|---|---|
| AAPL | Technology | Very high liquidity, multiple historical splits, regular dividends since 2012 |
| MSFT | Technology | Very high liquidity, historical splits, long dividend history |
| IBM | Technology (legacy) | Multi-decade listed history, long dividend history, useful contrast to AAPL/MSFT's growth profile |
| JNJ | Healthcare | Multi-decade "dividend aristocrat" history, defensive sector representative |
| PFE | Healthcare | Large-cap pharma, different volatility/event profile than JNJ |
| JPM | Financials | Large-cap money-center bank, financial-sector representative |
| XOM | Energy | Multi-decade history, commodity-linked volatility profile, dividend history |
| CVX | Energy | Second energy-sector representative for within-sector contrast |
| KO | Consumer Staples | One of the longest continuously-listed dividend/split histories available |
| PG | Consumer Staples | Long dividend-aristocrat history, defensive sector representative |
| WMT | Consumer Staples / Retail | Large-cap retail, historical splits |
| HD | Consumer Discretionary | Large-cap retail/discretionary contrast to WMT |
| DIS | Consumer Discretionary / Media | Media/entertainment representative, historical splits |
| CAT | Industrials | Cyclical industrials representative, long dividend history |
| GE | Industrials | Multi-decade history **including a reverse split** -- a deliberately chosen edge case for `CorporateActionType.REVERSE_SPLIT` handling, distinct from every other pilot symbol's forward-split-only history |
| SPY | Benchmark ETF (not part of the equity pilot universe) | S&P 500 proxy -- see ADR-0025 and the benchmark ADR for why SPY, not the index itself |

## What remains UNKNOWN / not done this phase

- Tiingo's exact free-tier numeric rate limits (Tier 2 only).
- Whether `api.tiingo.com` is reachable from any real deployment
  environment (untested; blocked from this sandboxed environment).
- Whether `TiingoDataProvider`'s parsing logic matches Tiingo's actual
  live response shape (built against Tier 2 documentation of a
  long-stable, widely-referenced public API shape, not verified
  against a live response).
- No `MARKET_DATA_API_KEY` value exists anywhere in this repository or
  environment; none was requested from the user.
- No real data has been ingested for any of the 16 pilot symbols **from
  this sandboxed session**. A user has separately ingested real Tiingo
  data (15 tradeable symbols + SPY, 2023-01-02 to 2024-12-31) from their
  own network-enabled environment (Phase 24 follow-up) -- that data
  exists only in the user's own environment, not in this repository or
  session (`data/` is empty and gitignored). See
  `docs/research/STRATEGY-RESEARCH-REPORT.md`'s Addendum for the actual
  results obtained from it.

## Phase 23 reachability re-verification

Re-checked this session, directly rather than assumed unchanged: the
environment's egress proxy status (`curl "$HTTPS_PROXY/__agentproxy/status"`)
recorded a 403 CONNECT rejection for `api.tiingo.com`, `stooq.com`, and
`openapi.tossinvest.com` -- all three still **BLOCKED**, identical to
Phase 20's finding. No real ingestion was performed this phase either.

`scripts/ingest_real_market_data.py` was added this phase specifically
so this reachability question (and the actual ingestion it blocks) can
be answered from a different environment without needing another
Claude Code session to rebuild the wiring -- it reuses
`FallbackDataProvider`/`IngestionRunner`/`DuckDBDataRepository`/
`DataQualityFramework` exactly as they exist in `src/`, unmodified.

## Phase 24 free-tier limits checklist (instruction section 6)

Re-attempted this session via two independent paths -- direct `curl`
through the egress proxy, and `WebFetch` (a separate fetch path) against
`www.tiingo.com` and `stooq.com` -- both returned `EGRESS_BLOCKED` for
every domain tried. **No new Tier 1 or Tier 2 evidence could be
gathered this session**; every item below either restates ADR-0025's
existing Phase 20 findings (re-cited, not re-derived) or is marked
UNKNOWN where Phase 20 also found nothing.

| Item | Tiingo | Stooq |
|---|---|---|
| Historical data availability | "30+ years free" per independent secondary sources (ADR-0025, Tier 2) | Commonly cited as a lightweight free source (ADR-0025, Tier 2); depth **UNKNOWN** |
| US equity coverage | Described as broad in Tier 2 sources; not independently confirmed | **UNKNOWN** |
| ETF coverage (needed for SPY) | Assumed included (SPY is treated as an ordinary pilot symbol, ADR-0025/26); not independently confirmed | **UNKNOWN** |
| EOD availability | Yes, per Tier 2 sources (this is the data shape `TiingoDataProvider` is built against) | Yes -- `stooq.com/q/d/l/` is a daily-EOD CSV endpoint by construction (ADR-0028) |
| Request limits | **UNKNOWN** -- no exact number found even at Tier 2 in Phase 20 | **UNKNOWN** |
| Symbol limits | **UNKNOWN** | **UNKNOWN** |
| Rate limits | **UNKNOWN** | **UNKNOWN** |
| Corporate action availability | Yes -- "explicit, separate Split/Dividend APIs" per Tier 2 sources (ADR-0025) | **No** -- `StooqDataProvider` documents `supports_corporate_actions=False` by design (Phase 22); no corporate-action feed found in any source |
| Adjusted/unadjusted price availability | Both -- raw OHLCV plus separate adjusted-close/-high/-low fields per Tier 2 sources (the latter two parsed starting Session 36 continued, ADR-0103 -- always present in the same response, just never read before) | Unadjusted (raw) CSV only; `StooqDataProvider.normalize()` always sets `adjusted_close`/`adjusted_high`/`adjusted_low` to `None` |
| Delayed/real-time | **UNKNOWN** (irrelevant to this project's EOD/long-term use case either way) | **UNKNOWN** |
| Licensing / redistribution restrictions | **UNKNOWN** -- not found in Tier 2 sources | **UNKNOWN** -- ADR-0025 already flags Stooq as having "weakest documentation of licensing/redistribution terms" among the candidates considered |

**Consequence for universe expansion (instruction section 31)**: because
request/symbol/rate limits are UNKNOWN for both providers, this phase
does not add any ticker beyond the existing 15-symbol
`PILOT_UNIVERSE`/16 including `SPY` (`src/data_infra/universe.py`).
`RESEARCH_UNIVERSE` Stage 2 (~30-50 symbols) remains a documented,
ready extension point, not populated -- populating it would mean
guessing a limit this project's own discipline forbids guessing.

## Phase 25 reachability re-verification

Re-checked this session via `curl` through the egress proxy directly
against each domain (rather than only the proxy status endpoint):
`api.tiingo.com`, `stooq.com`, and `openapi.tossinvest.com` all still
return a CONNECT 403 rejection. **BLOCKED**, unchanged since Phase 20
-- this is the fourth consecutive phase to re-confirm rather than
assume this. No new real ingestion was performed by this session; see
the note above this session's own status is separate from the real
2023-2024 data a user has already obtained externally.

Free-tier limits (request/symbol/rate) remain UNKNOWN for both
providers, unchanged from Phase 24's table above -- this phase gathered
no new evidence on that question (nothing in Phase 25's own scope
touches ingestion or provider limits; see
`docs/decisions/ADR-0031-long-horizon-walk-forward-validation.md`).

## Phase 26 precise block diagnosis (instruction section 7)

Prior phases (20-25) all recorded the block as "CONNECT 403 through the
egress proxy" without further diagnosis. Phase 26 was explicitly asked
to distinguish DNS failure / provider-side block / auth failure /
malformed response / environment block from each other, so this session
ran each layer independently rather than re-citing the prior finding:

| Layer | Check | Result |
|---|---|---|
| DNS | `socket.gethostbyname()` for all three domains | **RESOLVES CORRECTLY** -- `api.tiingo.com` -> `170.23.105.95`, `stooq.com` -> `159.69.202.225`, `openapi.tossinvest.com` -> `23.55.236.140` |
| TCP | Raw `socket.connect()` to `api.tiingo.com:443`, bypassing the configured HTTPS proxy entirely | **SUCCEEDS** -- the underlying network path to the host is reachable |
| HTTP/TLS (via configured proxy) | `curl` through `$HTTPS_PROXY` | `403`, `CONNECT tunnel failed` |
| HTTP/TLS (bypassing the proxy, `curl --noproxy '*'`) | Direct HTTPS GET | **Still `403`** -- confirming the block is not merely a client-side proxy-config issue |
| Response headers/body (bypassing the proxy) | `curl -D -` | `x-deny-reason: host_not_allowed` / body: `"Host not in allowlist: <host>. Add this host to your network egress settings to allow access."` -- **identical for all three domains** |

**Conclusion**: this is unambiguously an **environment-level network
egress allowlist** block, not a Tiingo/Stooq/Toss-side rejection, not a
DNS failure, not an authentication failure (no credential was even
sent), not a rate limit, and not a malformed request/response. The
response is generated by this sandboxed environment's own network
policy layer before the request ever leaves the environment (DNS
resolves and the TCP handshake succeeds; only the actual HTTP request is
denied, with a header that names the exact reason and the exact remedy).
**BLOCKED_BY_ENVIRONMENT** (instruction section 7's status vocabulary),
not `BLOCKED_BY_PROVIDER_LIMIT` and not `UNKNOWN`.

**Actionable remedy** (new this phase -- not previously identified):
the exact fix is to add `api.tiingo.com` (and, if Stooq fallback or a
future Toss integration is wanted, `stooq.com`/`openapi.tossinvest.com`)
to this environment's network egress allowlist. This is a workspace/
environment configuration setting outside this session's own
permissions to change -- see
[Claude Code on the web's environment configuration docs](https://code.claude.com/docs/en/claude-code-on-the-web)
for where an environment's network policy is configured. This does not
change the fact that the user's own separate environment (Codespaces)
already has real 2023-2024 data ingested and unaffected by this.

## Phase 27 re-verification

Re-checked this session (not assumed unchanged): direct HTTPS request
bypassing the configured proxy still returns `x-deny-reason:
host_not_allowed` for `api.tiingo.com`. **BLOCKED_BY_ENVIRONMENT**,
identical to Phase 26's diagnosis -- no change in this environment's
network egress policy between Phase 26 and Phase 27. No
`MARKET_DATA_API_KEY` set (checked). `data/` remains empty and
gitignored -- no real data exists locally in this session.

## Phase 28 re-verification + exhaustive real-data location search

Re-checked network (identical `x-deny-reason: host_not_allowed` for
`api.tiingo.com`, DNS resolves, TCP connects, only the HTTP request is
denied) and `MARKET_DATA_API_KEY` (still unset) -- unchanged from
Phase 26/27. This phase went further than prior phases' checks and
searched exhaustively (not just `data/`) for a real data location
anywhere in the environment, per instruction section 4's required
order: project docs (this file and `STRATEGY-VALIDATION-REPORT.md`
name the location the user's Codespaces session used, `./data/real_market_data`
-- not present here), ingestion manifests (none found outside `/tmp`
pytest/scratch artifacts), data_version/checksum records (none),
DuckDB files (`find / -iname "*.duckdb"` outside test/scratch
directories -- none), Parquet files (none), environment
variables/config (`env | grep -i "market_data\|tiingo\|db_path"` --
empty), existing execution scripts (`scripts/ingest_real_market_data.py`
exists and is ready, but has never been run in this session). **No
real data exists anywhere in this session's filesystem.**
`BLOCKED_BY_ENVIRONMENT` (root cause: network egress) and
`BLOCKED_BY_DATA` (immediate finding: no data file present) both apply
and are not in tension -- the only way real data could exist locally is
via network ingestion, which is blocked.

Also added this phase: a REAL-provenance plausibility check in
`scripts/run_long_horizon_validation.py` -- `--data-status REAL` is now
cross-checked against the actual `Provenance.source` values recorded on
the catalog's own bars (must be `"tiingo"` or `"stooq"`, the exact
strings the real provider implementations stamp) and the script refuses
to proceed (exit code 1) if they don't match, rather than trusting the
caller's `--data-status REAL` claim at face value. Verified at runtime
this phase: the same synthetic-fixture catalog pattern Phase 25-27 used
for dry runs is now correctly refused under `--data-status REAL` and
still runs correctly under `--data-status SYNTHETIC`.

## Phase 29 re-verification + fetch_symbol_metadata

Re-checked network (identical `x-deny-reason: host_not_allowed` for
`api.tiingo.com`, DNS resolves, TCP connects, only HTTP denied) and
`MARKET_DATA_API_KEY` (still unset) -- unchanged from Phase 26-28. An
exhaustive filesystem search again found no real data anywhere in this
session. **REAL WALK-FORWARD EXECUTION: NOT COMPLETED**, unchanged root
cause.

Added `TiingoDataProvider.fetch_symbol_metadata`/`normalize_symbol_metadata`
(broad-universe discovery groundwork, instruction section 15 Stage 1)
against Tier 2 documentation of Tiingo's `GET /tiingo/daily/<ticker>`
metadata endpoint (`ticker`/`name`/`exchangeCode`/`startDate`/`endDate`)
-- never exercised against a live response, same unverified-until-real-access
status as every other Tiingo method in this module (see this file's own
module docstring). `sector`/`market_cap_bucket` are never populated
from this endpoint's documented shape and stay `None`. See
`docs/decisions/ADR-0032-security-identity-and-survivorship-aware-universe.md`
for the full Phase 29 architecture decision this groundwork supports.

## Phase 30 re-verification + data source decision tree

Re-checked network -- identical block, `api.tiingo.com`/`stooq.com`/
`openapi.tossinvest.com` all still `x-deny-reason: host_not_allowed`.
**New this phase**: also tested four additional candidate provider
hosts (`data.nasdaq.com`, `api.polygon.io`, `www.alphavantage.co`,
`financialmodelingprep.com`, `crsp.org`) -- all five return the
identical `403`/`host_not_allowed`, while two control hosts
(`github.com`, `pypi.org`) return `200` in the same run. This confirms
the block is a scoped market-data-provider allowlist, not a total
network outage, and that switching providers within this environment
would not itself unblock anything. `MARKET_DATA_API_KEY` remains
unset. Exhaustive filesystem search again found no real data anywhere.
**REAL WALK-FORWARD EXECUTION: NOT COMPLETED**, unchanged root cause,
now more broadly confirmed.

Also fixed a genuine gap in `scripts/ingest_real_market_data.py`'s
manifest (instruction section 16): it previously reported only the
*requested* start/end, never what a provider actually returned. Now
reports `actual_data_start`/`actual_data_end` (computed from the real
persisted bars, `None` when no bars were persisted), `delisted_count`,
and an explicit `data_status: "REAL"` field; the old ambiguous
`start`/`end` keys were renamed to `requested_start`/`requested_end`.
8 new AST-based wiring tests
(`tests/data_infra/test_ingest_real_market_data_wiring.py`).

See `docs/decisions/ADR-0033-real-data-source-decision-tree.md` for
the full provider capability classification (Tiingo/Stooq/Nasdaq Data
Link/Polygon/Alpha Vantage/Financial Modeling Prep/CRSP across
historical prices, delisted coverage, ticker changes, corporate
actions, historical universe membership, point-in-time metadata, and
licensing/access) -- desk research from public documentation only,
never live-verified, since network access remains blocked.

## Phase 31 re-verification + external import pathway

Re-checked network with a distinct-layer diagnosis (instruction
section 20): DNS resolves and a raw TCP connect to port 443 succeeds
for all three primary hosts (`api.tiingo.com`/`stooq.com`/
`openapi.tossinvest.com`); only the HTTP request itself is denied
(`403`/`x-deny-reason: host_not_allowed`), confirmed
`ENVIRONMENT_BLOCKED` specifically -- not `AUTHENTICATION_FAILED`
(no request ever reaches a provider), not
`PROVIDER_DOES_NOT_SUPPORT_FEATURE`/`DATASET_DOES_NOT_EXIST` (neither
determinable), not `USER_ACCOUNT_LIMITATION` (no account/key exists in
this session). Also tested 5 additional candidate provider hosts
(Nasdaq Data Link, Polygon, Alpha Vantage, Financial Modeling Prep,
CRSP) -- identical `403`; github.com/pypi.org return `200` in the same
run. `MARKET_DATA_API_KEY` remains unset.

Built the external-acquisition pathway instruction section 21 asks
for, as actual runnable code rather than only a documented intention:
`src/data_infra/providers/file_import.py` (`LocalFileDataProvider`, a
`DataProvider` Protocol implementation reading pre-downloaded,
normalized CSV files from local disk -- no network call, ever) and
`scripts/import_external_market_data.py` (wires it through the same
`IngestionRunner`/`DataQualityFramework`/`DuckDBDataRepository`
pipeline `ingest_real_market_data.py` uses). Because this path makes no
network call, it is directly exercised end-to-end by the automated
test suite (`tests/data_infra/test_import_external_market_data_cli.py`,
`tests/data_infra/test_file_import_provider.py`) against real
temporary CSV fixtures and a real on-disk DuckDB catalog -- unlike
`ingest_real_market_data.py`, which remains untestable in this way.

Extended `ingest_real_market_data.py`'s manifest further
(`providers_used`, `missing_symbols`, `active_count`,
`historical_universe_membership_available`/
`survivorship_mitigation_applied`) to answer the remaining unanswered
questions from instruction section 18's 17-question list.

Added `audit_survivorship` (`src/data_infra/universe.py`) -- an honest
FULLY_SUPPORTED/PARTIALLY_MITIGATED/CURRENT-UNIVERSE-ONLY/UNKNOWN
classifier answering instruction section 28's ten survivorship
questions, tested only against synthetic fixtures this phase.

See `docs/decisions/ADR-0034-real-data-acquisition-strategy.md` for
the full provider matrix re-labeled under this phase's required
VERIFIED_BY_DOCUMENTATION/VERIFIED_BY_ACTUAL_ACCESS/UNKNOWN/
NOT_AVAILABLE/ENVIRONMENT_BLOCKED vocabulary, and the decision
framework conclusion (both EXTERNAL_DATASET_REQUIRED and
ENVIRONMENT_BLOCKED apply simultaneously).
