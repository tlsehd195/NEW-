"""Position Sizing + Portfolio Risk Engine (Phase 8).

Sits between Decision Agent (Phase 7) and Order Creation (a later phase,
not built here):

    DecisionOutput -> PositionSizer -> PortfolioRiskEngine -> RiskCheckedPosition

`PositionSizer` turns a BUY/SELL/HOLD/EXIT/NO_TRADE decision into a
deterministic, risk-aware `target_weight`/`target_quantity` proposal.
`PortfolioRiskEngine` independently re-checks that proposal against
portfolio-level hard limits (single position, gross/net exposure,
concentration, drawdown, portfolio volatility, cash minimum, turnover,
liquidity) and is the final authority: it can REDUCE or REJECT whatever
PositionSizer proposed. Neither module creates an order, a broker call,
or an execution price -- Order Creation/Validation/Broker remain out of
scope for Phase 8 (docs/specifications/PHASE-8-position-sizing-and-risk.md
section 14).
"""
