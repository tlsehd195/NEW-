"""orchestration: the composition layer Phase 15's own spec explicitly
deferred ("A real, running Trading Engine loop... this phase builds
the simulated broker and its orchestration primitives; wiring them
into an always-on scheduled process is a later phase's concern",
docs/specifications/PHASE-15-paper-trading.md section 1.1).

A new top-level package specifically because `broker.paper.*` (and
`broker.live.*`) structurally forbid importing `data_infra.repository`/
`backtest.asof` (`tests/broker/paper/test_paper_boundary.py`) -- Regime/
Prediction need an `AsOfDataView`, so the module that ties Regime,
Prediction, Decision, Sizing, and the Risk Engine together with a
Paper/Live session must live one layer above both, not inside either.
"""
