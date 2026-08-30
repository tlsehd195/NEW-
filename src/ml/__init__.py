"""ML Research Track (Track B) -- first concrete implementation.

See `docs/research/ML-RESEARCH-PROTOCOL.md` for the governance this
package is bound by (leakage prevention, TRAIN/VALIDATION/TEST
structure, TEST-1 lock, experiment governance, dependency policy) and
`docs/decisions/ADR-0043-ml-first-model.md` for what was actually built
and why.

This package answers ML-RESEARCH-PROTOCOL.md's stated goal exactly:
"does historically available information contain out-of-sample
predictive signal" -- NOT "find a model that maximizes backtest
return". The first model here is deliberately the simplest possible
one (ordinary least squares, no regularization search, no
hyperparameter tuning, pure Python, no numpy/scikit-learn per
ADR-0043) precisely because this codebase's own `strategy_research`
history (`risk_controlled_momentum`'s construction bug,
`leverage_score`'s promising-IC-that-failed-as-a-strategy result) has
repeatedly shown that added complexity can obscure or fabricate a
signal's real quality -- the same principle applied here to model
choice, not just portfolio construction.

Every score this package produces flows through the SAME point-in-time
machinery the rest of this codebase already uses and has already
proven (`backtest.asof.AsOfDataView` for price-derived features,
`storage.fundamentals_repository.DuckDBFundamentalsRepository`'s own
`available_time <= as_of_time` filtering for fundamentals-derived
ones) -- no new leakage-guard mechanism is invented here.
"""
