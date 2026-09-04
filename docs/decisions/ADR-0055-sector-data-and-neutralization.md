# ADR-0055: real SIC sector data + sector-neutralization capability

**Status:** Accepted
**Session:** 36

## Context

Item #2 of the "전부 다 진행하는건?" 3-part request. Solution #2 of the
"why isn't strategy working" diagnosis was sector neutralization,
motivated by a real, already-diagnosed problem: `size_score` reaching
walk-forward `CANDIDATE` at top_n=5 turned out to be SLB (the sole
liquid Energy name in the universe at the time) supplying 76.3% of its
positive TEST PnL (`docs/research/STRATEGY-VALIDATION-REPORT.md`'s
"Phase 33 Addendum" section E) -- a sector-concentration artifact, not
a genuine cross-sectional size effect.

**A near-mistake caught before writing any code**: the first instinct
was to hardcode GICS sector classifications for the universe's 63
symbols from training-data/background knowledge. Before implementing
this, `src/data_infra/universe.py`'s own module docstring was
(re-)read and found to explicitly forbid exactly this: "even a widely-
known fact like 'AAPL trades on NASDAQ' is left unconfirmed here...
not from this module's authors' background knowledge." Filling in
sectors from memory would have repeated this project's own already-
documented mistake pattern. Redirected to the honest alternative: a
real, provider-sourced data path.

## Decision

**Part A -- a real sector data source.** Added `fetch_submissions`/
`normalize_submissions` to `SecEdgarFundamentalsProvider`
(`src/data_infra/providers/sec_edgar.py`), reaching SEC EDGAR's
`/submissions/CIK##########.json` endpoint (Tier 2 documentation, same
`data.sec.gov` host as `fetch_company_facts` -- no second-transport
workaround needed, unlike `fetch_ticker_map`'s `www.sec.gov` host).
This endpoint documents a real field this project had no source for
before: `sicDescription`, the SEC's own Standard Industrial
Classification text (e.g. "CRUDE PETROLEUM AND NATURAL GAS").
`normalize_submissions` maps it onto `SymbolMetadata.sector` -- the
honest counterpart to `TiingoDataProvider.normalize_symbol_metadata`,
whose own docstring already flags that Tiingo's metadata endpoint never
supplies `sector`. **SIC and GICS are different taxonomies** (SIC:
older, coarser, US-government; GICS: newer, finer, MSCI/S&P-licensed,
which this project has no access to) -- `normalize_submissions`'s
docstring states this explicitly so `sector` is never misread as a
GICS label.

Like every other real-provider capability this project has already
built without live network access in this environment (`ADR-0042`'s
company-facts provider, `TiingoDataProvider.fetch_symbol_metadata`
itself, never yet CLI-wired), this is tested only against a stubbed
transport (`tests/data_infra/test_sec_edgar_provider.py`), never a live
`data.sec.gov` request. Real population of `RESEARCH_UNIVERSE_STAGE3`'s
63 `SymbolMetadata.sector` values requires running this in the user's
own real environment -- deliberately not attempted here, matching the
same "build the pipe, defer real data" precedent `ADR-0053`'s
`idiosyncratic_volatility_score` already established for a different
kind of gap.

**Part B -- the sector-neutralization capability itself.** Added
`_select_target` to `src/strategy_research/factor_strategy.py`,
replacing the plain `ranked[:top_n]` slice all 4 generic Strategy
wrappers (`PriceFactorStrategy`/`FundamentalsFactorStrategy`/
`HybridFactorStrategy`/`UniverseFactorStrategy`) previously used
directly. Two new optional `FactorStrategyParameters` fields,
`sector_by_security: Optional[dict[str, str]]` and
`max_per_sector: Optional[int]`, both default `None` -- **opt-in only,
both required together**: with either left `None`, `_select_target`
returns byte-for-byte the same result as the old plain slice, so no
existing candidate's behavior changes. When both are supplied,
securities are still considered strictly in score-rank order (a
lower-ranked security is only ever skipped, never promoted ahead of a
higher-ranked one) -- capping changes WHICH `top_n` securities are
picked, never how many or in what priority.

**A security absent from `sector_by_security` is never capped** --
unconfirmed sector is not evidence of concentration, and treating it
as if it were would itself fabricate a fact, the same honesty
discipline `data_infra.universe`'s module docstring already
establishes for the field this reads.

**Deliberately not activated for any existing candidate in this ADR**
-- `run_long_horizon_validation.py`'s 28-candidate pool is untouched;
turning the cap on for `size`/`combined_factor`/anything else requires
real `sector` data (Part A, run in the user's environment) plus an
explicit decision about `max_per_sector`, which this ADR does not make.

## Tests

8 new tests in `tests/data_infra/test_sec_edgar_provider.py`
(`TestFetchSubmissions`, `TestNormalizeSubmissions`) -- path
construction, unexpected-shape error, `sicDescription`->`sector`
mapping, first-exchange selection (including an empty-string-entry
EDGAR quirk), missing-field honesty (`sector`/`exchange` stay `None`
rather than fabricated), and confirmation that fields this endpoint's
shape does not name (`market_cap_bucket`, `listed_from`, `listed_to`)
stay `None` too.

12 new tests in `tests/strategy_research/test_factor_strategy.py`
(`TestSelectTarget`, plus 2 in `TestParameterValidation`, plus 1
`TestSectorCapEndToEnd` integration test through a full
`BacktestEngine` run) -- no-sector-data and max-per-sector-without-a-
map both no-op identically to a plain slice, capping actually excludes
a same-sector security even though it scores higher, rank order is
still respected under a cap, an unconfirmed sector is never capped,
`top_n` is unchanged when enough distinct sectors already exist,
`max_per_sector<1` is rejected.

Full suite: 2241 passed (up from 2223).

## What this does NOT do

- Does not populate any real `sector` value into `universe.py`'s
  hardcoded `SymbolMetadata` tuples -- that requires running Part A's
  new fetch method against the live SEC EDGAR API, which this
  environment cannot reach (same network constraint as every other
  real-provider integration this project has built).
- Does not activate the sector cap for any candidate already in
  `run_long_horizon_validation.py`'s walk-forward pool.
- Does not touch `risk/engine.py`'s `sector_exposure=None`/
  `RiskConfig.max_sector_weight` -- those are Production's live risk
  layer, a different concept from this research-layer top-N selection
  cap (the same distinction this project's own
  `risk_controlled_momentum.py` docstring already establishes between
  research-strategy construction parameters and Production `RiskConfig`
  -- conflating the two was an earlier near-mistake this session
  self-corrected before ADR-0052, and is not repeated here).
- Does not add a GICS mapping or any GICS data source -- SIC is the
  only real classification this project has provider access to.
