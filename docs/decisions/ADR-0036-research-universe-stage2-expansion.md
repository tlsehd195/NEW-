# ADR-0036: RESEARCH_UNIVERSE Stage 2 (concentration-risk expansion)

## Context

`RESEARCH_UNIVERSE_STAGE1` (`src/data_infra/universe.py`, Phase 24) was
deliberately left identical to `PILOT_UNIVERSE_V1` because this
session's own environment could not verify Tiingo's actual free-tier
request limits (ADR-0030's no-guessing discipline). That precondition
was met this session: the user checked their real Tiingo account "API
USAGE" dashboard (not documentation, not a guess) and reported the
confirmed numbers directly:

- Hourly Requests: 50/hour allocation
- Daily Requests: 1,000/day allocation (904 left at the time of
  checking)
- Monthly Bandwidth: 2.00 GB allocation (1.96 GB left)

This is the first time in this project's history these limits have
been empirically confirmed from a real source rather than left
`UNKNOWN`.

This ADR is deliberately **separate** from the real 2010-2026 16-symbol
walk-forward result and its PBO/Deflated Sharpe Ratio finding
(`STRATEGY-VALIDATION-REPORT.md`, ADR-0035): that result showed none of
the 4 existing strategies reach `CANDIDATE` evidence, with
`trend_volatility`'s apparent 70%-fold-win-rate edge specifically
flagged by PBO (62.86%) as more likely noise than a real, persistent
signal on that 16-symbol dataset. This ADR does **not** attempt to fix
that PBO finding -- broadening the universe addresses a *different*
problem (concentration risk: `PILOT_UNIVERSE_V1` is 15/16 mega-cap
tech/growth names, so a handful of outsized movers can dominate a
walk-forward result) and does not, by itself, change whether an
overfitting finding is real. Conflating the two would risk exactly the
kind of post-hoc, result-driven universe change RULE 0.8 forbids -- this
expansion's symbol list was fixed before any Stage 2 backtest is ever
run, for that reason.

## Decision 1 -- Populate `RESEARCH_UNIVERSE_STAGE2` with 24 new symbols, fixed before any Stage 2 result exists

Added to `src/data_infra/universe.py`. Selection criterion, stated
precisely and decided in this order (never adjusted after seeing a
result):

1. Keep all 16 `PILOT_UNIVERSE_V1` symbols unchanged, for direct
   comparability with the already-completed real run.
2. Add exactly 24 additional large-cap US companies, hand-picked
   (`source="manual_curation"`, the same convention `PILOT_UNIVERSE_V1`
   already uses) to cover GICS sectors `PILOT_UNIVERSE_V1`
   under-represents or omits entirely (Industrials, Health Care,
   Utilities) or covers thinly (Financials, Consumer Staples, Consumer
   Discretionary, Communication Services, Energy, Information
   Technology).
3. Deliberately **not** labeled or claimed to be "the current S&P 500"
   or "the current Dow Jones Industrial Average" -- this session has no
   network access to verify live index membership, and reciting an
   index's composition from training-data recall would risk presenting
   a possibly-stale fact as a confirmed one, which `universe.py`'s own
   documented honesty discipline (every unconfirmed field stays `None`,
   every unconfirmed claim stays disclosed) forbids. It is exactly what
   `PILOT_UNIVERSE_V1` already honestly is: a disclosed, hand-curated
   list -- wider and more sector-balanced, nothing more.

`RESEARCH_UNIVERSE_STAGE1` is left in the module unchanged, importable
for historical reference (it is what none of this project's real runs
have ever actually used -- every real run so far used `PILOT_UNIVERSE`
directly). `_UNIVERSES["RESEARCH_UNIVERSE"]` in every script that
defines it (`ingest_real_market_data.py`,
`run_long_horizon_validation.py`, `run_first_real_strategy_evaluation.py`,
`import_external_market_data.py`) now resolves to Stage 2 -- the same
"always the latest populated stage" convention `PILOT_UNIVERSE` already
uses for `PILOT_UNIVERSE_V1`.

## Decision 2 -- What this does NOT address

Every symbol in Stage 2, like every symbol in `PILOT_UNIVERSE_V1` and
Stage 1, still carries `listed_from=listed_to=None`. Per
`audit_survivorship` (Phase 31, unmodified), this universe still
classifies as `CURRENT-UNIVERSE-ONLY`: today's constituents projected
across the whole backtest date range, with no delisted or failed
company included, by construction. Stage 2 mitigates concentration
risk, not survivorship bias. Fixing survivorship bias remains a
separate, already-documented, deliberately deferred decision requiring
paid historical-constituent data (ADR-0034 Decision 4,
`EXTERNAL_DATASET_REQUIRED`) -- untouched by this ADR.

## Decision 3 -- Request-budget arithmetic, computed from the confirmed limits, not assumed

`scripts/ingest_real_market_data.py` (unmodified) makes 2 Tiingo
requests per symbol: one price-history fetch, one corporate-actions
fetch. The 16 `PILOT_UNIVERSE_V1` symbols are already ingested in the
user's existing `--db-path` from the prior real run -- only the 24 NEW
Stage 2 symbols need fetching to complete the expansion. 24 x 2 = 48
requests, which fits inside the confirmed 50-requests/hour cap in a
single hourly window (2-request margin for retries), and is trivial
against the 1,000/day and 2.00 GB/month caps (the prior full
16-symbol/16.5-year run consumed roughly 0.04 GB of the 2 GB monthly
allocation, per the dashboard). `IngestionRunner`'s own retry/backoff
(`src/data_infra/provider.py`, unmodified) caps backoff at 30 seconds
across 3 retries -- it cannot itself ride out an hour-long rate-limit
window, so staying under 50 requests in one CLI invocation is a real
operational requirement here, not just a courtesy.

Practical command for the user's Codespaces environment (same
`--db-path` as the existing real run, so the already-ingested 16
symbols are not re-fetched and existing bars are preserved):

```
python3 scripts/ingest_real_market_data.py \
  --symbols CAT HON UPS BA UNH PFE ABBV MRK BAC GS PG KO PEP HD MCD NKE CVX VZ T DIS ORCL IBM CSCO NEE \
  --start 2010-01-01 --end 2026-08-27 \
  --db-path ./data/real_2010_latest
```

After this succeeds, `scripts/run_long_horizon_validation.py
--universe RESEARCH_UNIVERSE --data-status REAL` (now resolving to the
full 40-symbol Stage 2 set) re-runs the same 4 strategies' walk-forward
against the wider universe, and
`scripts/compute_pbo_dsr_from_report.py` (ADR-0035, unmodified) applies
PBO/DSR to that new result exactly as it did for the 16-symbol run --
no code changes needed for either step.

## Decision 4 -- No new dependency, no Live/broker/risk code touched

Purely additive to `src/data_infra/universe.py` (one new
`UniverseDefinition` constant) and a one-line import/dict-value change
in the four scripts that already referenced `RESEARCH_UNIVERSE_STAGE1`.
No `src/broker/`, `src/risk/`, `src/learning/`, `src/evolution/`, or
`src/ai_gateway/` file touched (confirmed via `git diff --stat` scope
check). All 1,759 pre-existing tests plus 6 new
`TestResearchUniverseStage2` tests pass.

## Consequences

- Running the command above lets the user complete a real, wider
  (40-symbol) walk-forward and PBO/DSR pass using exactly the same,
  already-implemented pipeline -- no new script, no new statistical
  method.
- The Stage 2 result will answer a narrower question than it might
  appear to: whether concentration in a handful of mega-cap movers was
  inflating or distorting the 16-symbol result, not whether the
  PBO-flagged overfitting concern goes away or whether survivorship
  bias is resolved. Both remain open questions after this expansion,
  and this ADR does not claim otherwise.
