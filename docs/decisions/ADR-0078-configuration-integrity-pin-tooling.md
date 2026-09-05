# ADR-0078: Operational tooling for `configuration_integrity_valid`'s pin

**Status:** Accepted
**Session:** 36 (continued)

## Context

ADR-0072/ADR-0074 built `compute_configuration_integrity_valid` and
wired it into `live_runner.run_cycle` as an opt-in derivation, but
deliberately left "where does an operator set the pinned hash" as the
one remaining un-designed half of item #7. `LIVE-TRADING-RUNBOOK.md`'s
existing "Configuration Validation" section had already anticipated
needing this ("Compute `LiveTradingConfig.configuration_version()` and
record it in the activation log") but never named how, in practice, an
operator would compute it consistently.

## Decision

`scripts/print_live_configuration_version.py` (new): takes the same
flags that would construct a real `LiveTradingConfig`, constructs one,
and prints both its full field dump (JSON) and its real
`configuration_version()` hash. No network call, no file I/O beyond
stdout -- an operator runs it after constructing or changing a real
Live config, and records BOTH the hash and the field dump in the
activation log `LIVE-TRADING-RUNBOOK.md` already designates for this.
That recorded hash becomes `run_cycle`'s `pinned_configuration_version`
going forward.

Using this exact script (rather than a hand-computed hash, or a
different tool) matters specifically because it calls the identical
`LiveTradingConfig.configuration_version()` method `run_cycle`'s own
`compute_configuration_integrity_valid` check will later compare
against -- any drift between "how the pin was computed" and "how the
check computes it" would silently defeat the whole point of pinning.

`LIVE-TRADING-RUNBOOK.md`'s "Configuration Validation" section now
names this script explicitly and adds a rotation step: a config change
means deliberately re-running the script and adding a NEW, append-only
activation-log entry -- never editing a previous one in place.

## Tests

`tests/broker/live/test_print_live_configuration_version_cli.py` (5
tests, run end to end via `main()`): default flags match a default
`LiveTradingConfig`; custom flags match the equivalent real config
constructed directly; a changed `--max-daily-loss` produces a different
hash (not a vacuous constant); the printed output includes the full
field dump, not just a bare hash. Full suite: 2361 passed (up from
2356).
