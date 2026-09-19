# ADR-0176: Opt-in point-in-time universe for backtests (independent audit P1-2)

**Status:** Accepted
**Date:** 2026-09-19
**Deciders:** Claude Code (session continued), account owner (independent
audit finding P1-2; explicitly asked, when presented with 4 scoping
options, for the "limited connection" option -- wire the already-
existing point-in-time data into an opt-in backtest path, leave
production/default behavior completely untouched)

## Context

Independent audit finding P1-2 (already independently verified real
during this same session, before this fix): `RESEARCH_UNIVERSE_STAGE4`
(`src/data_infra/universe.py`) is a hand-curated list of TODAY's
current S&P 500 holdings -- every symbol's `listed_from`/`listed_to`
metadata may carry a real confirmed join date (ADR-0061), but the
membership LIST ITSELF never includes a ticker that has since left the
index. Any backtest run against this universe over a historical window
implicitly and silently excludes every real constituent removed since
-- a genuine survivorship-bias exposure. This limitation is **already
self-disclosed** in `universe.py`'s own docstring (unlike P1-1, which
was a genuinely silent gap) -- so this is a known, deliberate trade-off
question, not a hidden bug, and "fixing" it required a real scoping
decision rather than a single obvious code change.

The account owner was asked directly (P1-2 differs in kind from P1-1/
P1-3) how far to take this, with four concrete options ranging from
"wire the already-existing point-in-time data into an opt-in backtest
path" through "make `RESEARCH_UNIVERSE_STAGE4` itself point-in-time by
default" (a much larger, higher-risk architectural change touching
every consumer of that universe) to "documentation only" or "defer to
P1-3". The account owner chose the first, scoped option explicitly.

**The relevant machinery already existed, unused**: this project
already has real, MIT-licensed, point-in-time S&P 500 constituent
interval data (`fja05680/sp500`'s `sp500_ticker_start_end.csv`,
verified reachable via `raw.githubusercontent.com`), already parsed by
`data_infra.providers.sp500_index_constituent_history.
parse_ticker_intervals`, and already queryable point-in-time via that
module's own `constituents_as_of(intervals, as_of) -> frozenset` --
"every ticker that was a real index member on this exact historical
date, including tickers no longer in today's index." A `grep` across
this repository confirmed this function, and the module's own
`build_sp500_index_universe_memberships`/`SP500_INDEX_HISTORICAL`
persistence path (`scripts/fetch_sp500_index_history.py`), were used
by nothing except that one fetch script and their own unit tests --
exactly the audit's own characterization: "the mechanism exists, but
the production universe is a static current-membership list."

## Decision

Two small, additive, opt-in pieces -- no existing default behavior
changes at all:

1. **`scripts/select_point_in_time_universe.py`** (new): given
   `--sp500-intervals-csv` (an already-fetched real CSV) and `--as-of
   DATE`, prints the real, historical S&P 500 constituent set for that
   date. Pure reuse of `parse_ticker_intervals`/`constituents_as_of` --
   no new selection logic -- mirroring
   `select_delisted_candidates_since.py`'s established shape exactly
   (same real-schema CSV input, same "no network call, real logic only"
   discipline, same FATAL-on-empty-result convention). Its output is
   directly usable as an explicit `--symbols` list for
   `scripts/ingest_real_market_data.py` (which already accepts
   `--symbols` as a full override of `--universe`), closing the loop
   from "which tickers were real members on this historical date" to
   "let's actually ingest real price data for them."

2. **`scripts/run_long_horizon_validation.py`** gained two new, entirely
   optional CLI flags: `--point-in-time-universe-as-of` and
   `--point-in-time-universe-csv`. When BOTH are given (giving only one
   is a caller error, rejected before any repository is opened), this
   run's `security_ids` is overridden to the real, historical
   constituent set for that one date via the same
   `constituents_as_of`/`parse_ticker_intervals` functions, instead of
   `--universe`'s own static current-membership list. `universe` itself
   (the `UniverseDefinition` object) is deliberately left unreassigned
   -- its `.name`/`.version` still identify which NAMED universe was
   requested, for provenance, even though the actual symbol set being
   evaluated may now differ from that universe's own static list. Both
   new fields (`point_in_time_universe_used`,
   `point_in_time_universe_as_of`) are added to the JSON report, and
   `point_in_time_universe_as_of` is folded into `experiment_id`'s hash
   input so a point-in-time run of an otherwise-identical configuration
   can never collide with an ordinary one (same collision-prevention
   discipline this script's own `experiment_id` docstring already
   applies to `--fundamentals-db-path`/`--insider-db-path`/etc.).
   `data_version` already hashes `sorted(security_ids)`, so it
   automatically reflects the override with no separate change needed.

When neither new flag is passed (the default, and every existing real
run to date), both scripts' behavior is byte-for-byte identical to
before this ADR.

## Consequences

### Positive
- The exact "mechanism exists but isn't connected to anything" gap the
  audit named is now closed for the one use case the account owner
  actually asked for: a caller CAN now run (or ingest data for) a
  survivorship-bias-corrected universe for a specific historical date,
  using only already-existing, already-tested real data -- no new
  external dataset, no new parsing/selection logic.
- Zero risk to any existing default path: `RESEARCH_UNIVERSE_STAGE4`,
  `PILOT_UNIVERSE_V1`, production paper trading, and every existing
  real run of `run_long_horizon_validation.py`/
  `ingest_real_market_data.py` are completely untouched -- both new
  flags default to `None`/absent and every override branch is gated
  behind both being explicitly supplied together.
- `select_point_in_time_universe.py` follows an established,
  already-reviewed pattern (`select_delisted_candidates_since.py`)
  exactly, minimizing real design risk.

### Negative / Trade-offs (disclosed, not hidden)
- **This is a single static universe for the WHOLE backtest run, not a
  per-fold time-varying one.** `run_long_horizon_validation.py`'s
  walk-forward loop (`strategy_research/walk_forward_evaluation.py`)
  still hands every fold the exact same `security_ids` list -- a
  ticker that was a real member on the chosen `--as-of` date but left
  the index partway through the backtest's own date range is still
  treated as tradeable for the ENTIRE range (and vice versa for a
  ticker that joined after `--as-of`). A fully time-varying,
  per-fold-correct universe (the "전면 개편"/full-rewrite option the
  account owner explicitly did NOT choose) would require plumbing
  changes through `walk_forward_evaluation.py`'s fold loop and every
  `Strategy` factory this script builds -- out of scope for this fix.
- **`RESEARCH_UNIVERSE_STAGE4` itself is completely unchanged** and
  remains the default for every real production ingestion/paper-
  trading path -- this fix does not reduce the audit's own named
  survivorship-bias exposure for any run that does not explicitly opt
  into the two new flags. The account owner explicitly chose this
  trade-off (limited connection over full default-behavior change).
- A backtest using the point-in-time override will very likely include
  tickers this project has never ingested real price data for (the
  override does not check `--db-path`'s own contents) -- such symbols
  simply produce zero bars for the run, the same pre-existing, already-
  handled "missing symbol" behavior this script and
  `ingest_real_market_data.py` (ADR-0175, P1-1) already have; this ADR
  does not add any new handling for that case.
- `fja05680/sp500`'s own known limitations (single-maintainer,
  ticker-keyed not corporate-identity-keyed, left-censored pre-1996
  start dates) apply here exactly as already documented in
  `sp500_index_constituent_history.py`'s own module docstring -- this
  fix inherits, not resolves, those caveats.

## Tests

`tests/scripts/test_select_point_in_time_universe.py` (8 tests): real
membership on a historical date, a ticker excluded outside every real
interval, a ticker with two disjoint real intervals (the AAL-shaped
leave-and-rejoin case) included in both, current members for a recent
date, CLI output formatting, FATAL-not-silent-empty-success on no
constituents found.

`tests/strategy_research/test_run_long_horizon_validation_wiring.py`'s
new `TestPointInTimeUniverseOptIn` class (7 tests, source-text/AST-
based -- this script is still never imported/executed by the automated
suite, real-catalog read, per its own docstring): both new flags
default to `None`, giving only one of the pair is rejected,
`security_ids` is only overridden inside the opt-in branch, `universe`
itself is never reassigned (exactly one `universe =` in the whole
script), the report carries both new fields, and `experiment_id`'s hash
input includes `point_in_time_universe_as_of`.

Full suite re-run (this session): 3469 -> 3483 passed.

## Status of Implementation at Time of This ADR

Code and tests complete. This is the second of three P1 findings from
the independent audit report being fixed in the order the account
owner specified ("순서대로 고쳐"); P1-1 (empty provider response
reported as SUCCESS, ADR-0175) is done; P1-3 (cycle-level cumulative
risk exposure not enforced in `paper_runner.py`) is next.
