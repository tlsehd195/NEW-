"""Paper Trading -- a fully simulated `broker.protocol.BrokerAdapter`
implementation. PROJECT_MASTER_PLAN.md section 9.4:

    Trading Engine -> Broker Interface -> Paper Broker   (default)
    Trading Engine -> Broker Interface -> Toss Broker     (Live only)

`PaperBrokerAdapter` never calls `broker.toss.*`, never reads
`os.environ`/`os.getenv`, never opens a network connection, and never
mutates a real account -- it is a deterministic, restart-safe
simulation of order submission, partial fills, slippage, and
transaction cost over already-available market data, reusing Phase 2's
own execution-cost machinery (`backtest.costs.TransactionCostModel`/
`SlippageModel`) and portfolio accounting
(`backtest.portfolio.PortfolioAccounting`) rather than re-deriving
either from scratch.

See docs/specifications/PHASE-15-paper-trading.md.
"""
