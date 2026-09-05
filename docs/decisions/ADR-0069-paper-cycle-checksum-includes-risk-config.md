# ADR-0069: `run_paper_trading_cycle.py`'s `content_checksum` now includes `risk_config`

**Status:** Accepted
**Session:** 36 (continued)

## Context

The user ran `scripts/run_paper_trading_cycle.py` twice against the real
data ingested this session (RESEARCH_UNIVERSE, 2023-06-01 to 2023-08-01):
once with no risk limits, once with `--max-sector-weight 0.25
--max-order-notional 50000`. The two runs produced materially different
results (85 vs. 74 orders submitted, 28 vs. 45 filled, $8,979 vs. $17,419
final cash, different `final_positions`) -- yet both reports carried the
identical `content_checksum`.

The cause: the checksum payload in `main()` hashed only `universe`,
`security_ids`, `start`, `end`, and `initial_capital` -- `risk_config`
(the four `--max-*` flags) was never included, even though the script's
own `risk_config` field one line below in the same report proves it is a
real, run-determining input. This is the exact reproducibility gap
Phase 30/31 already found and fixed for `ingest_real_market_data.py`'s
manifest (`ACTUAL_DATA_START`/`missing_symbols`/`providers_used`, etc.)
-- a content_checksum's whole purpose is to let two runs be told apart
when their content differs, and here it silently could not.

## Decision

`risk_config` (all four `--max-*` values) is added to the checksum
payload. No other behavior changes -- `risk_config` was already computed
and already present in the report; this only makes the checksum actually
depend on it, matching `compute_data_version`'s own stated contract
("any real content change must produce a different [version]").

`db_path`/`paper_store` are deliberately NOT added -- they identify
*where* a run's inputs/outputs live, not *what* was requested, the same
distinction `ingest_real_market_data.py`'s own checksum (symbols/start/
end/per-symbol bar counts, no `db_path`) already draws.

## Tests

New regression test in `tests/orchestration/test_run_paper_trading_cycle_cli.py`
(`test_different_risk_config_produces_a_different_checksum`): two runs,
identical universe/window/capital, differing only in `--max-sector-weight`/
`--max-order-notional`, now produce different checksums. Full suite:
2315 passed (up from 2314).
