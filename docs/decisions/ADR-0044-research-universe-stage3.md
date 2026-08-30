# ADR-0044: Research universe Stage 3 -- 24 more hand-curated symbols to fill sector gaps

## Context

By ADR-0043 Decision 6, every hypothesis this project has tested against
the real 40-symbol `RESEARCH_UNIVERSE_STAGE2` catalog -- 3 price/volume
Signal ICs, 4 fundamentals-factor Signal ICs, `leverage` and `ml_ols`/
`ml_ridge`/`rank_average_ensemble` as full walk-forward strategies (9
candidates in total) -- has failed to reach CANDIDATE. Asked "다음은 뭐
해야해?" (what's next), the assistant recommended universe expansion as
the highest-expected-impact remaining lever: the other levers already
tried this round (regularization, ensembling, a longer effective
training window via caching) all only extract more signal from the
same ~39-40-symbol cross-section, whereas widening the cross-section is
a structurally different kind of change. The user then said "너가
프로젝트 완성에 더 가까운 방향으로 진행해줘" (proceed in whichever
direction is closer to completion), explicitly delegating the choice.
This ADR documents that expansion.

## Decision -- add 24 more hand-curated symbols, chosen to fill this project's own confirmed GICS sector gaps

A GICS-sector audit of the pre-Stage-3 40-symbol universe (`PILOT_
UNIVERSE_V1`'s 16 + `RESEARCH_UNIVERSE_STAGE2`'s additional 24) found:

- **Real Estate: 0 symbols** (completely absent)
- **Materials: 0 symbols** (completely absent)
- **Utilities: 1 symbol** (`NEE` only -- thinnest present sector)

These three gaps are a real, checkable property of the existing
universe definition (not a subjective judgment call), and are the
selection criterion for Stage 3's new symbols -- the same kind of
non-cherry-picked, documented rule ADR-0030 established for Stage 1/2
(there: mega-cap-tech concentration; here: sector coverage). 24 new
large/mid-cap US companies were added:

```
Real Estate:              PLD, AMT, EQIX, SPG
Materials:                LIN, APD, ECL, NEM
Utilities:                DUK, SO, D
Energy (was 2, now 5):    SLB, COP
Financials:                MS, WFC, AXP
Health Care:                LLY, TMO, ABT
Information Technology:    ADBE, CRM, QCOM
Consumer Discretionary:    LOW
Consumer Staples:          PM
```

Real Estate, Materials, and Utilities got dedicated slots to directly
close the confirmed gaps; the remaining 14 symbols were spread across
already-represented sectors to keep the universe's overall sector mix
roughly balanced rather than concentrating the entire 24-symbol
addition into 3 sectors alone.

**Same hand-curation honesty discipline as Stage 1/2, explicitly
restated**: `RESEARCH_UNIVERSE_STAGE3` is a **hand-curated list**, not
a verified snapshot of any real index's actual constituents at any
historical date, and not a survivorship-bias mitigation -- every
`SymbolMetadata` entry still carries `source="manual_curation"` and
`listed_from=listed_to=None` (this session has no network access to
verify live index membership or listing history against a real
provider; see `data_infra/universe.py`'s own module docstring for why
this project refuses to fill such fields from general background
knowledge). This is a breadth improvement only -- it does not, and is
not claimed to, address survivorship bias.

**RULE 0.8 compliance**: this symbol list was fixed, reviewed, and
committed to before any backtest using `RESEARCH_UNIVERSE_STAGE3` was
run. `strategy_research.locked_windows.TEST_1`'s own comments continue
to name `RESEARCH_UNIVERSE_STAGE2` specifically, as an accurate
historical record of which universe that locked TEST result was
actually observed against -- that reference is deliberately left
unchanged by this ADR.

**Same versioning pattern as Stage 1/2**: `RESEARCH_UNIVERSE_STAGE3`
shares `name="RESEARCH_UNIVERSE"` with Stage 1/2 but carries its own
`version="stage3"`; every CLI script's `_UNIVERSES["RESEARCH_UNIVERSE"]`
alias was repointed from `RESEARCH_UNIVERSE_STAGE2` to `RESEARCH_
UNIVERSE_STAGE3` (9 scripts), so `--universe RESEARCH_UNIVERSE` now
resolves to the 64-symbol Stage 3 definition by default; `--universe
PILOT_UNIVERSE` is unaffected.

**Request-budget arithmetic, reusing Stage 2's own already-confirmed
numbers** (this session has no network access to re-verify them): the
user's real Tiingo free-tier dashboard, checked once for Stage 2,
confirmed a 50-requests/hour cap. `scripts/ingest_real_market_data.py`
issues 2 requests/symbol (price history + corporate actions) and has
no built-in rate-limiting/pacing logic (confirmed via grep -- no
`rate.limit`/`sleep`/`throttle`/`per.hour` anywhere in that script).
Stage 3's 24-symbol addition was deliberately sized to mirror Stage
2's own identical arithmetic shape for exactly this reason: 24 x 2 = 48
requests, fitting the confirmed 50/hour cap in a single window with a
2-request margin, rather than requiring multi-window batching logic
the script does not have.

7 new tests (`tests/data_infra/test_universe.py`, `TestResearchUniverse
Stage3`), mirroring `TestResearchUniverseStage2`'s structure exactly:
superset-of-Stage-2, exactly 24 new symbols, no duplicates, benchmark
symbol never a member, distinct version from Stage 2, no provider-
confirmed dates on any entry, request budget fits one hourly window.

## What this does NOT do

**No real data has been ingested for these 24 new symbols in this
session** -- this ADR only fixes the universe DEFINITION; the actual
price/fundamentals ingestion for the new symbols must run in the
user's own network-enabled environment (`scripts/ingest_real_market_
data.py --universe RESEARCH_UNIVERSE ...` and `scripts/ingest_
fundamentals_data.py --universe RESEARCH_UNIVERSE ...`), same as every
prior real-data step in this project. No backtest against Stage 3 has
been run by anyone, in any environment, as of this ADR. No claim is
made that these 24 symbols are, or ever were, actual constituents of
any real index at any date -- see the honesty discipline above.
