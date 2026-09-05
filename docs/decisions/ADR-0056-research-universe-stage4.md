# ADR-0056: Research universe Stage 4 -- deepening the 5 sectors Stage 3 leaves thinnest

**Status:** Accepted
**Session:** 36

## Context

Item #3 of the "전부 다 진행하는건?" 3-part request (alongside
`combined_factor_score` and the sector-neutralization capability,
ADR-0054/ADR-0055). Stage 3's own audit found Real Estate/Materials
completely absent and Utilities thin (ADR-0044); this ADR revisits the
same kind of audit against Stage 3's OWN state, one stage later, using
the same non-cherry-picked "count the thinnest sectors" rule.

## Decision -- deepen the 5 sectors tied at 4 explicitly-curated symbols after Stage 3

Counting each stage's own explicitly section-commented additions
(Stage 2 + Stage 3, `data_infra/universe.py`'s existing per-sector
comments -- not a new audit invented for this ADR), five sectors sit at
exactly 4 symbols after Stage 3: **Energy, Industrials, Utilities, Real
Estate, Materials**. This tie is the selection criterion, fixed before
any Stage 4 backtest was run (RULE 0.8) -- not a subjective judgment
call, and not a reaction to anything observed in a Stage 4 backtest
(none has been run).

**Energy's thinness is not merely a count** -- it is the DIRECTLY
DIAGNOSED root cause of a real finding from earlier this same session:
`size_score` reaching walk-forward `CANDIDATE` at top_n=5 turned out to
be SLB (Energy's only name besides XOM/CVX at the time) supplying
76.3% of its positive TEST PnL (`docs/research/
STRATEGY-VALIDATION-REPORT.md`'s "Phase 33 Addendum" section E) -- a
concentration artifact, not a genuine size effect. Deepening Energy
specifically addresses that already-diagnosed problem; the other 4
sectors are included because they are equally thin by the same count,
kept symmetric rather than singling out Energy alone.

24 new large-cap US companies added, 4-5 per sector:

```
Energy (4 -> 9):        PSX, VLO, OXY, WMB, KMI
Industrials (4 -> 9):   GE, RTX, LMT, DE, EMR
Utilities (4 -> 9):     AEP, EXC, SRE, XEL, ED
Real Estate (4 -> 9):   O, PSA, WELL, DLR, AVB
Materials (4 -> 8):     SHW, FCX, DOW, NUE
```

`RESEARCH_UNIVERSE_STAGE4` added to `src/data_infra/universe.py`,
`Stage 3's 63 symbols + these 24`, same hand-curation honesty
discipline as every prior stage (`source="manual_curation"`,
`listed_from=listed_to=None` on every entry -- not a survivorship-bias
fix, not a claim of verified live index membership).

**Same versioning pattern as Stage 1-3**: shares `name="RESEARCH_
UNIVERSE"`, carries `version="stage4"`. **Every CLI script's
`_UNIVERSES["RESEARCH_UNIVERSE"]` alias was repointed from
`RESEARCH_UNIVERSE_STAGE3` to `RESEARCH_UNIVERSE_STAGE4`** (9 scripts
-- the identical set ADR-0044 repointed for Stage 3:
`compute_signal_ic_from_catalog.py`, `compute_fundamentals_ic_from_
catalog.py`, `compute_filter_bucket_returns_from_catalog.py`,
`run_long_horizon_validation.py`, `run_first_real_strategy_
evaluation.py`, `ingest_real_market_data.py`, `ingest_fundamentals_
data.py`, `import_external_market_data.py`, `train_ml_model_from_
catalog.py`), so `--universe RESEARCH_UNIVERSE` now resolves to the
87-symbol Stage 4 definition by default; `--universe PILOT_UNIVERSE`
unaffected. This follows ADR-0044's own precedent exactly (Stage 3 was
also repointed immediately at definition time, before any real
ingestion for its new symbols) rather than deferring the pointer
switch until after ingestion.

**Request-budget arithmetic, reusing the same confirmed Tiingo
numbers** (this session cannot re-verify them; re-check the user's
actual account limits if they may have changed): 24 new symbols x 2
requests/symbol (`scripts/ingest_real_market_data.py`, unmodified) = 48
requests, fitting the confirmed 50-requests/hour cap in one window --
identical arithmetic shape to Stage 2's and Stage 3's own additions.

8 new tests (`tests/data_infra/test_universe.py`,
`TestResearchUniverseStage4`), mirroring `TestResearchUniverseStage3`'s
structure exactly, plus one additional collision guard (new symbols
are genuinely new against ALL prior stages, not just a duplicate check
within Stage 4's own tuple).

Full suite: 2249 passed (up from 2241).

## What this does NOT do

**No real data has been ingested for these 24 new symbols in this
session** -- this ADR only fixes the universe DEFINITION and repoints
the script aliases; actual price/fundamentals ingestion for the new
symbols must run in the user's own network-enabled environment
(`scripts/ingest_real_market_data.py --universe RESEARCH_UNIVERSE ...`
and `scripts/ingest_fundamentals_data.py --universe RESEARCH_UNIVERSE
...`), same as every prior real-data step in this project. Until that
ingestion runs, every score function's existing missing-data discipline
(`None`, never fabricated) means these 24 symbols are silently excluded
from any cross-section computed against the user's current catalog --
nothing crashes, but results before that ingestion do not yet reflect
Stage 4's full breadth. No backtest against Stage 4 has been run by
anyone, in any environment, as of this ADR. No claim is made that these
24 symbols are, or ever were, actual constituents of any real index at
any date.
