"""Phase 23 strategy research framework.

See docs/decisions/ADR-0029-strategy-research-framework.md and
docs/research/STRATEGY-RESEARCH-REPORT.md.

Every strategy in this package implements the existing, unmodified
`backtest.strategy.Strategy` Protocol (Phase 2) -- this package adds no
new portfolio accounting, journal, or risk engine. It plugs into the
existing `backtest.engine.BacktestEngine` exactly like
`backtest.strategy.BuyAndHoldStrategy`/`SimpleMomentumStrategy` already
do.

None of these strategies read a process environment variable, call a
network or broker API, read wall-clock time, or use the `random`
module -- every signal is a deterministic function of `(as_of_time,
data, portfolio)` (instruction section 19/20). Enforced by a static
source scan, `tests/strategy_research/test_security_boundary.py`.
"""
