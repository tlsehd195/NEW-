"""Live Trading -- the safety layer that lets the same trading pipeline
Phase 15 already proved in simulation run against a real broker
(`broker.toss.adapter.TossBrokerAdapter`, Phase 13).
PROJECT_MASTER_PLAN.md section 9.4:

    Trading Engine -> Broker Interface -> Paper Broker   (default)
    Trading Engine -> Broker Interface -> Toss Broker    (Live only,
                                                            explicit)

`broker.live.*` never decides *what* to trade -- every order it ever
sees is an already-built `broker.models.ValidatedOrder` from Phase 13's
own `build_validated_order`. It only decides *whether a submission may
proceed at all*: a multi-condition safety gate, a kill switch that only
a human can release, and reconciliation-before-resume semantics.
`live_trading_enabled` defaults `False` (`LiveTradingConfig`) and
nothing in this repository's own code, tests, or configuration ever
sets it `True` or constructs the human-sourced approval object the gate
also requires -- activating Live Trading for real remains a deliberate,
out-of-band human action.

See docs/specifications/PHASE-16-live-trading.md.
"""
