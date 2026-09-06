"""Standalone rule-based factor score functions for Signal IC
diagnosis -- deliberately NOT full `Strategy` implementations (no
order generation, no rebalance-timing, no position sizing). Lets a
factor's raw predictive power be tested cheaply via
`signal_ic.compute_ic_series` before any full strategy is built around
it, matching the pipeline-stage separation (`DATA -> FEATURES ->
... -> SIGNAL -> ... -> PORTFOLIO CONSTRUCTION`) `docs/research/
ML-RESEARCH-PROTOCOL.md` section 11 already establishes for a future
ML signal. Reuses the exact same `trim_to_lookback`/
`annualized_volatility` building blocks the existing strategies use,
so a factor found to carry real IC here can graduate into a full
Strategy using primitives already proven correct, rather than new,
untested ones.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Optional, Sequence

from backtest.asof import AsOfDataView
from backtest.clock import BacktestClock
from backtest.metrics import annualized_volatility, compute_returns

from data_infra.universe import BENCHMARK_SYMBOL, get_sector

from strategy_research._dates import TRADING_DAYS_PER_MONTH, add_months, trim_to_lookback
from strategy_research.signal_ic import rank_average


def low_volatility_score(
    security_id: str, as_of_time: datetime, data: AsOfDataView, *, lookback_days: int = 126,
) -> Optional[float]:
    """HYPOTHESIS -- the "low-volatility anomaly" (e.g. Ang, Hodrick,
    Xing & Zhang 2006; Baker, Bradley & Wurgler 2011): securities with
    LOWER trailing realized volatility tend to have relatively BETTER
    risk-adjusted forward returns than a naive risk-return tradeoff
    would predict. A well-documented, independently pre-existing
    candidate -- not invented in reaction to the momentum score's
    near-zero IC finding (that finding is exactly why this is worth
    testing next, but the hypothesis itself predates it by decades).

    Score is the NEGATIVE of trailing annualized volatility, so a
    higher score means lower (hypothesized more attractive) volatility
    -- matches this module's and `_momentum_score`'s convention that a
    higher score ranks a security as more attractive.

    `lookback_days` is trimmed via `trim_to_lookback` from a
    calendar-day-padded fetch, the same discipline ADR-0038 already
    applied to every other lookback-windowed score in this package --
    built correctly the first time here, not as a later fix."""
    bars = trim_to_lookback(
        data.get_bars(security_id, as_of_time - timedelta(days=int(lookback_days * 1.6)), as_of_time),
        lookback_days,
    )
    if len(bars) < 2:
        return None
    closes = [b.adjusted_close or b.close for b in bars]
    returns = compute_returns(closes)
    if len(returns) < 2:
        return None
    vol = annualized_volatility(returns)
    return -vol


def long_term_reversal_score(
    security_id: str, as_of_time: datetime, data: AsOfDataView, *, lookback_months: int = 36,
) -> Optional[float]:
    """HYPOTHESIS -- long-term return reversal (De Bondt & Thaler 1985,
    "Does the Stock Market Overreact?," The Journal of Finance 40(3):
    793-805): stocks with the WORST returns over a long (multi-year)
    formation period ("losers") significantly OUTPERFORM stocks with
    the BEST returns over the same period ("winners") over the
    following years -- one of the founding papers of behavioral
    finance, attributed to investor overreaction to a long run of bad
    or good news. A genuinely different hypothesis from this project's
    already-tested `_momentum_score` (`long_term_momentum.py`/
    `risk_controlled_momentum.py`, real IC = -0.0078, Section G of
    `STRATEGY-VALIDATION-REPORT.md`), not a re-test of it under a new
    name: De Bondt & Thaler's own 3-5 YEAR formation window is far
    longer than this project's momentum lookback range (6-18 months,
    `LongTermMomentumParameters.lookback_months`), and the direction of
    the resulting score is the OPPOSITE sign relationship (past losers
    are hypothesized to be more attractive here, not less).

    Score is the NEGATIVE of the cumulative return over the trailing
    `lookback_months` (default 36, De Bondt & Thaler's own shorter
    formation window -- a documented simplification of their full
    36-60 month range, chosen since it needs less trailing history per
    security to produce a usable score), so a WORSE past return
    produces a HIGHER (more attractive) score -- matches this module's
    convention. Reuses the identical `trim_to_lookback`/`get_bars`
    machinery `low_volatility_score`/`_momentum_score` already use, no
    new data or infrastructure needed."""
    lookback_days = lookback_months * TRADING_DAYS_PER_MONTH
    bars = trim_to_lookback(
        data.get_bars(security_id, as_of_time - timedelta(days=int(lookback_days * 1.6)), as_of_time),
        lookback_days,
    )
    if len(bars) < 2:
        return None
    closes = [b.adjusted_close or b.close for b in bars]
    if closes[0] is None or closes[0] == 0:
        return None
    cumulative_return = closes[-1] / closes[0] - 1.0
    return -cumulative_return


def short_term_reversal_score(
    security_id: str, as_of_time: datetime, data: AsOfDataView, *, lookback_months: int = 1,
) -> Optional[float]:
    """HYPOTHESIS -- short-term return reversal (Jegadeesh 1990,
    "Evidence of Predictable Behavior of Security Returns," The Journal
    of Finance 45(3): 881-898): individual stock returns show
    significant NEGATIVE serial correlation at the one-month horizon --
    a stock with a bad past month tends to have a relatively good next
    month, and vice versa. This is exactly why academic momentum
    studies (including this project's own `_momentum_score`) skip the
    most recent month when forming a momentum signal -- this factor
    tests the skipped month's own effect directly, on its own, rather
    than as a gap in another factor's construction.

    HONEST CAVEAT, not previously needed for this module's other
    factors: short-term reversal is the one anomaly in the literature
    most associated with market microstructure noise (bid-ask bounce)
    in individual stock returns rather than a genuine economic
    mispricing signal, particularly at a 1-month/daily-close-only data
    resolution like this project's (no intraday, no bid/ask spread
    data). Built anyway, exactly as hypothesized in the literature and
    fixed before any result is seen (RULE 0.8), but a null or even
    negative real IC result here would be less surprising than for this
    module's other factors, and should not be read as evidence against
    the broader reversal literature the way `_momentum_score`'s own
    null result was read as a real finding about medium-term momentum
    specifically.

    Score is the NEGATIVE of the cumulative return over the trailing
    `lookback_months` (default 1), same construction as
    `long_term_reversal_score`, just a much shorter window. Needs zero
    new data or infrastructure."""
    lookback_days = lookback_months * TRADING_DAYS_PER_MONTH
    bars = trim_to_lookback(
        data.get_bars(security_id, as_of_time - timedelta(days=int(lookback_days * 1.6)), as_of_time),
        lookback_days,
    )
    if len(bars) < 2:
        return None
    closes = [b.adjusted_close or b.close for b in bars]
    if closes[0] is None or closes[0] == 0:
        return None
    cumulative_return = closes[-1] / closes[0] - 1.0
    return -cumulative_return


def low_beta_score(
    security_id: str, as_of_time: datetime, data: AsOfDataView, *, lookback_days: int = 252,
) -> Optional[float]:
    """HYPOTHESIS -- "Betting Against Beta" (Frazzini & Pedersen 2014,
    Journal of Financial Economics 111(1): 1-25): securities with LOWER
    market beta earn higher risk-adjusted returns than a naive CAPM
    would predict (leverage-constrained investors bid up high-beta
    assets for the embedded leverage, depressing their risk-adjusted
    return) -- one of the most cited and highest-Sharpe (0.78,
    1926-2012 US sample per the original paper) anomalies in the
    low-risk factor family. A genuinely different construct from
    `low_volatility_score` already in this module: that factor is
    NEGATIVE TOTAL trailing volatility (a security's own return
    variability in isolation); this one is NEGATIVE market BETA
    (covariance with a market benchmark, divided by the benchmark's own
    variance) -- a low-total-vol stock can still have a high beta (if
    nearly all its variance is systematic), and vice versa, so the two
    scores can and do disagree on individual securities.

    Beta is estimated as `Cov(security_returns, benchmark_returns) /
    Var(benchmark_returns)` over the trailing `lookback_days` (default
    252, ~1 trading year), using `data_infra.universe.BENCHMARK_SYMBOL`
    ("SPY", already ingested per ADR-0029's S&P 500 benchmark decision
    -- needs zero new data) as the market proxy, with security and
    benchmark closes paired by calendar date (not by list position) so
    a day either series is missing does not silently misalign the two
    return series. A DELIBERATE SIMPLIFICATION of Frazzini & Pedersen's
    own estimator, flagged honestly the same way `low_volatility_score`
    flags its own simplification versus Ang et al: the original paper
    uses a 1-year daily volatility estimate blended with a 5-year daily
    correlation estimate (to reduce the correlation estimate's
    small-sample noise) and then shrinks the resulting beta toward the
    cross-sectional mean -- this implementation uses one uniform
    1-year window and no shrinkage, a standard textbook beta estimator
    rather than the paper's own noise-reduction refinements.

    Score is the NEGATIVE of estimated beta, so a LOWER (more
    defensive) beta produces a HIGHER (more attractive) score, matching
    this module's convention. Needs at least 20 paired daily
    observations to guard against a near-meaningless beta estimate from
    a handful of overlapping trading days (e.g. a recently-listed
    security or a benchmark data gap); returns `None` below that, the
    same missing-data honesty this module's fundamentals-based factors
    already apply."""
    padded_days = int(lookback_days * 1.6)
    security_bars = trim_to_lookback(
        data.get_bars(security_id, as_of_time - timedelta(days=padded_days), as_of_time), lookback_days,
    )
    benchmark_bars = trim_to_lookback(
        data.get_bars(BENCHMARK_SYMBOL, as_of_time - timedelta(days=padded_days), as_of_time), lookback_days,
    )
    if len(security_bars) < 2 or len(benchmark_bars) < 2:
        return None
    security_closes = {b.timestamp.date(): (b.adjusted_close or b.close) for b in security_bars}
    benchmark_closes = {b.timestamp.date(): (b.adjusted_close or b.close) for b in benchmark_bars}
    common_dates = sorted(set(security_closes) & set(benchmark_closes))
    if len(common_dates) < 21:
        return None
    security_returns = compute_returns([security_closes[d] for d in common_dates])
    benchmark_returns = compute_returns([benchmark_closes[d] for d in common_dates])
    if len(security_returns) < 20 or len(security_returns) != len(benchmark_returns):
        return None
    security_mean = sum(security_returns) / len(security_returns)
    benchmark_mean = sum(benchmark_returns) / len(benchmark_returns)
    covariance = sum(
        (s - security_mean) * (b - benchmark_mean) for s, b in zip(security_returns, benchmark_returns)
    ) / (len(security_returns) - 1)
    benchmark_variance = sum((b - benchmark_mean) ** 2 for b in benchmark_returns) / (len(benchmark_returns) - 1)
    if benchmark_variance == 0:
        return None
    beta = covariance / benchmark_variance
    return -beta


def idiosyncratic_volatility_score(
    security_id: str, as_of_time: datetime, data: AsOfDataView, *, lookback_days: int = 21,
) -> Optional[float]:
    """HYPOTHESIS -- the idiosyncratic volatility anomaly (Ang, Hodrick,
    Xing & Zhang 2006, "The Cross-Section of Volatility and Expected
    Returns," The Journal of Finance 61(1): 259-299): stocks with
    HIGHER idiosyncratic (stock-specific, non-market) return volatility
    earn LOWER subsequent returns -- one of the most-cited puzzles in
    the low-risk factor family (the original paper's own "IVOL puzzle"
    is that this contradicts a naive CAPM prediction that only
    systematic risk should be priced). Session 36 (post-mortem on
    `size`/`altman_z`'s real results, see `docs/research/
    STRATEGY-VALIDATION-REPORT.md`'s "Phase 33 Addendum") searched
    current literature specifically for a candidate genuinely distinct
    from everything already tested in this module, before looking at
    any new result (RULE 0.8) -- this is that candidate.

    **A genuinely different construct from every other low-risk factor
    already in this module**, not a re-parameterization of one:
    `low_volatility_score` is TOTAL trailing volatility (a security's
    own return variability in isolation, systematic + idiosyncratic
    combined); `low_beta_score` is systematic co-movement with a
    benchmark (covariance-based, says nothing about how much of a
    security's OWN variance is left over after removing that
    co-movement). Idiosyncratic volatility is what remains of a
    security's return variance AFTER regressing out its co-movement
    with the market -- the residual, stock-specific component -- so a
    security can have low total volatility yet high idiosyncratic
    volatility (if nearly all its variance is non-systematic), or high
    beta yet low idiosyncratic volatility (if it moves almost
    perfectly with the market), and this score can disagree with both
    existing scores on any individual security.

    **Construction, a deliberate simplification of the original paper's
    own estimator, flagged the same way `low_beta_score` flags its
    own**: the original paper fits daily excess returns against the
    Fama-French 3-factor model (market, SMB, HML) over the trailing
    ONE MONTH and takes the standard deviation of the regression
    residuals; this implementation regresses against the market
    (`BENCHMARK_SYMBOL`, "SPY") alone via simple OLS (the same
    `Cov/Var` beta estimator `low_beta_score` already uses, plus the
    OLS intercept), matching the original paper's own trailing ONE
    MONTH window (`lookback_days=21` default) rather than a longer,
    more-stable-but-less-faithful-to-the-paper window. No SMB/HML
    control is applied -- this project's universe (63 large-cap
    securities only) has no independently-constructed SMB/HML series
    to regress against, and building one is out of scope for a single
    factor's screening pass. Score is the NEGATIVE of the residual
    standard deviation (higher score = lower idiosyncratic vol = more
    attractive, matching this module's convention and the paper's own
    "high IVOL -> low returns" finding).

    Needs at least 15 paired daily observations (a defensible floor for
    a ~1-month window that can have a few missing days, lower than
    `low_beta_score`'s 20-observation floor for its full-year window)
    with non-zero benchmark return variance; `None` below that, the
    same missing-data honesty this module's other factors already
    apply."""
    padded_days = int(lookback_days * 1.6)
    security_bars = trim_to_lookback(
        data.get_bars(security_id, as_of_time - timedelta(days=padded_days), as_of_time), lookback_days,
    )
    benchmark_bars = trim_to_lookback(
        data.get_bars(BENCHMARK_SYMBOL, as_of_time - timedelta(days=padded_days), as_of_time), lookback_days,
    )
    if len(security_bars) < 2 or len(benchmark_bars) < 2:
        return None
    security_closes = {b.timestamp.date(): (b.adjusted_close or b.close) for b in security_bars}
    benchmark_closes = {b.timestamp.date(): (b.adjusted_close or b.close) for b in benchmark_bars}
    common_dates = sorted(set(security_closes) & set(benchmark_closes))
    if len(common_dates) < 16:
        return None
    security_returns = compute_returns([security_closes[d] for d in common_dates])
    benchmark_returns = compute_returns([benchmark_closes[d] for d in common_dates])
    if len(security_returns) < 15 or len(security_returns) != len(benchmark_returns):
        return None
    security_mean = sum(security_returns) / len(security_returns)
    benchmark_mean = sum(benchmark_returns) / len(benchmark_returns)
    covariance = sum(
        (s - security_mean) * (b - benchmark_mean) for s, b in zip(security_returns, benchmark_returns)
    ) / (len(security_returns) - 1)
    benchmark_variance = sum((b - benchmark_mean) ** 2 for b in benchmark_returns) / (len(benchmark_returns) - 1)
    if benchmark_variance == 0:
        return None
    beta = covariance / benchmark_variance
    alpha = security_mean - beta * benchmark_mean
    residuals = [s - alpha - beta * b for s, b in zip(security_returns, benchmark_returns)]
    residual_mean = sum(residuals) / len(residuals)
    residual_variance = sum((r - residual_mean) ** 2 for r in residuals) / (len(residuals) - 1)
    return -(residual_variance ** 0.5)


def illiquidity_score(
    security_id: str, as_of_time: datetime, data: AsOfDataView, *, lookback_days: int = 252,
) -> Optional[float]:
    """HYPOTHESIS -- Amihud (2002)'s illiquidity premium ("Illiquidity
    and Stock Returns: Cross-Section and Time-Series Effects," Journal
    of Financial Markets 5(1): 31-56): investors demand a return
    premium for holding harder-to-trade (more illiquid) stocks, so
    HIGHER illiquidity is hypothesized to predict HIGHER subsequent
    returns -- one of the most-cited liquidity-based anomalies in
    empirical asset pricing, and (per the correction this decision adds
    to ADR-0047) arguably a SEVENTH independent factor family alongside
    momentum/value/quality/low-risk/size that project's earlier "5-6
    families" framing omitted: this module had zero factors using
    trading VOLUME at all before this one.

    IMPORTANT SIGN NOTE, the one place in this module where a
    "bad"-sounding word does NOT get negated: unlike `leverage_score`/
    `asset_growth_score` (where the module negates a quantity investors
    consider undesirable), illiquidity itself is hypothesized to be
    POSITIVELY related to expected return (compensation for a real
    cost/risk of holding the stock), so a HIGHER illiquidity score
    means a MORE, not less, attractive candidate here -- still matches
    this module's "higher score = more attractive" convention, just
    with the paper's own sign already pointing the right way.

    ILLIQ is the Amihud measure: the average, over the trailing
    `lookback_days` (default 252, ~1 trading year, matching the
    paper's own annual-averaging convention), of the daily ratio
    `|return| / dollar_volume`, where `dollar_volume = close * volume`
    for that day. Dollar volume deliberately uses raw `close` (never
    `adjusted_close`), the same reasoning `_latest_price` documents for
    market-cap calculations: a back-adjusted price does not represent
    the actual dollar amount that traded on that historical day. The
    `|return|` itself uses `adjusted_close or close`, this module's
    usual convention for a RETURN calculation (splits/dividends must be
    reflected there). Needs zero new real ingestion: `volume` is
    already a required field on every ingested `PriceBar`, just never
    previously used by any factor in this module. Requires at least 20
    valid daily observations (a defensible floor for a meaningful
    average, not itself from the paper, which uses a full year) with
    positive dollar volume; `None` below that."""
    bars = trim_to_lookback(
        data.get_bars(security_id, as_of_time - timedelta(days=int(lookback_days * 1.6)), as_of_time),
        lookback_days,
    )
    if len(bars) < 2:
        return None
    closes = [b.adjusted_close or b.close for b in bars]
    returns = compute_returns(closes)
    ratios = []
    for bar, r in zip(bars[1:], returns):
        dollar_volume = (bar.close or 0.0) * (bar.volume or 0.0)
        if dollar_volume <= 0:
            continue
        ratios.append(abs(r) / dollar_volume)
    if len(ratios) < 20:
        return None
    return sum(ratios) / len(ratios)


def fifty_two_week_high_score(
    security_id: str, as_of_time: datetime, data: AsOfDataView, *, lookback_days: int = 252,
) -> Optional[float]:
    """HYPOTHESIS -- the "52-week high" anomaly (George & Hwang 2004,
    "The 52-Week High and Momentum Investing," The Journal of Finance
    59(5): 2145-2176): a stock's CURRENT PRICE relative to its own
    trailing 52-week HIGH predicts returns better than, and largely
    subsumes, standard past-return momentum -- the paper's own finding
    is that proximity to the 52-week high is the more fundamental
    driver, with cumulative past return itself carrying little
    additional information once the 52-week-high ratio is known.
    Distinct in MECHANISM, not just parameterization, from this
    project's already-tested `_momentum_score` (real IC = -0.0078,
    Section G of `STRATEGY-VALIDATION-REPORT.md`): George & Hwang's own
    explanation is investor anchoring to a specific, salient reference
    price (the 52-week high), a different psychological mechanism than
    momentum's under-reaction-to-information story -- not a re-test of
    the same already-null hypothesis under a new name, the same
    distinction this project's own `long_term_reversal_score`/
    `short_term_reversal_score` already established for a different
    momentum-adjacent construction.

    Score is `close / trailing_52_week_high` (never negated): CLOSER to
    the 52-week high (ratio closer to 1) is hypothesized to be more
    attractive, matching this module's convention directly since the
    paper's own sign already points the right way -- the same "no
    negation needed" situation as `illiquidity_score`. Uses raw `close`
    (never `adjusted_close`) for both the current price and the
    trailing high: comparing a security's own actual traded prices to
    its own actual traded high needs the same (raw) price convention on
    both sides, not one raw and one back-adjusted, the same reasoning
    `_latest_price` documents. Needs zero new real ingestion -- price
    data only."""
    padded_days = int(lookback_days * 1.6)
    bars = trim_to_lookback(
        data.get_bars(security_id, as_of_time - timedelta(days=padded_days), as_of_time), lookback_days,
    )
    if len(bars) < 2:
        return None
    current_close = bars[-1].close
    if current_close is None or current_close <= 0:
        return None
    highs = [b.close for b in bars if b.close is not None and b.close > 0]
    if not highs:
        return None
    trailing_high = max(highs)
    if trailing_high <= 0:
        return None
    return current_close / trailing_high


def max_effect_score(
    security_id: str, as_of_time: datetime, data: AsOfDataView, *, lookback_days: int = 21,
) -> Optional[float]:
    """HYPOTHESIS -- the "MAX effect" (Bali, Cakici & Whitelaw 2011,
    "Maxing Out: Stocks as Lotteries and the Cross-Section of Expected
    Returns," Journal of Financial Economics 99(2): 427-446): stocks
    with a HIGHER maximum single-day return over the trailing month
    earn LOWER subsequent returns -- interpreted as poorly-diversified,
    lottery-seeking investors overpaying for a small chance of a large
    (lottery-like) payoff. A single-extreme-observation effect distinct
    from both of this module's other low-risk factors:
    `low_volatility_score` (average dispersion over the whole window)
    and `low_beta_score` (systematic co-movement with a benchmark) -- a
    stock can have low average volatility and low beta yet still have
    had one single extreme up-day that drives MAX, and vice versa. The
    original paper reports the effect survives controls for size,
    book-to-market, momentum, short-term reversal, liquidity, and
    skewness, so it is not simply a repackaging of factors already in
    this module either.

    Score is the NEGATIVE of the maximum daily return over the trailing
    `lookback_days` (default 21, ~1 trading month, matching the
    paper's own monthly MAX construction), so a LOWER maximum single-
    day return (hypothesized more attractive, per the paper's finding)
    produces a HIGHER score -- matches this module's convention (see
    `leverage_score`). Uses `adjusted_close or close`, this module's
    usual convention for a return-based calculation. Needs zero new
    real ingestion -- price data only."""
    padded_days = int(lookback_days * 1.6)
    bars = trim_to_lookback(
        data.get_bars(security_id, as_of_time - timedelta(days=padded_days), as_of_time), lookback_days,
    )
    if len(bars) < 2:
        return None
    closes = [b.adjusted_close or b.close for b in bars]
    returns = compute_returns(closes)
    if len(returns) < 2:
        return None
    return -max(returns)


def idiosyncratic_skewness_score(
    security_id: str, as_of_time: datetime, data: AsOfDataView, *, lookback_days: int = 21,
) -> Optional[float]:
    """HYPOTHESIS -- Boyer, Mitton & Vorkink (2010, "Expected
    Idiosyncratic Skewness," The Review of Financial Studies 23(1):
    169-202): stocks with HIGHER expected idiosyncratic (stock-specific,
    non-market) return skewness earn LOWER subsequent returns -- the
    original paper's own headline result is a 1.00%/month Fama-French
    alpha spread between its low- and high-expected-skewness quintiles.
    Interpreted the same way the MAX effect (`max_effect_score`) already
    in this module is: investors with a preference for lottery-like,
    right-skewed payoffs overpay for positive skewness, depressing its
    subsequent return. Verified via WebSearch (paper's own abstract and
    citing summaries) rather than reconstructed from memory alone,
    per this module's established citation-verification discipline.

    **Distinct from `max_effect_score`, not a re-parameterization**: MAX
    is a single-extreme-observation statistic (the one largest daily
    return in the window); skewness is a shape-of-the-whole-distribution
    statistic (the THIRD standardized moment of every return in the
    window) -- a distribution can have one large up-day yet still be
    left-skewed overall (many small down-days dominating the shape), and
    vice versa, so the two can and do disagree on individual securities.
    Also distinct from `idiosyncratic_volatility_score` (the SECOND
    moment of the same market-model residuals): a security's residuals
    can have low dispersion yet a strongly skewed shape, or high
    dispersion yet a symmetric shape.

    **Construction, a deliberate simplification of the original paper's
    own estimator, flagged the same way `idiosyncratic_volatility_score`
    flags its own**: the original paper fits a cross-sectional model of
    EXPECTED future skewness from several predictive characteristics
    (lagged idiosyncratic skewness, volume, size, book-to-market, and
    others); this implementation instead uses REALIZED trailing
    idiosyncratic skewness directly (this module's existing convention,
    also used by `max_effect_score`'s own realized-not-expected MAX and
    `idiosyncratic_volatility_score`'s own realized-not-expected IVOL --
    a REALIZED statistic as a proxy for the paper's own EXPECTED one).
    Reuses `idiosyncratic_volatility_score`'s own market-model residual
    construction (regress trailing daily returns on `BENCHMARK_SYMBOL`
    via simple OLS, matching its 21-day/~1-month default window) and
    takes the third standardized moment (population skewness) of the
    residuals instead of their standard deviation.

    Score is the NEGATIVE of the residual skewness (higher score = lower
    idiosyncratic skewness = more attractive, matching this module's
    convention and the paper's own "high skewness -> low returns"
    finding). Needs at least 15 paired daily observations (matching
    `idiosyncratic_volatility_score`'s own floor) and a non-zero
    residual standard deviation (skewness is undefined at zero
    variance); `None` below that."""
    padded_days = int(lookback_days * 1.6)
    security_bars = trim_to_lookback(
        data.get_bars(security_id, as_of_time - timedelta(days=padded_days), as_of_time), lookback_days,
    )
    benchmark_bars = trim_to_lookback(
        data.get_bars(BENCHMARK_SYMBOL, as_of_time - timedelta(days=padded_days), as_of_time), lookback_days,
    )
    if len(security_bars) < 2 or len(benchmark_bars) < 2:
        return None
    security_closes = {b.timestamp.date(): (b.adjusted_close or b.close) for b in security_bars}
    benchmark_closes = {b.timestamp.date(): (b.adjusted_close or b.close) for b in benchmark_bars}
    common_dates = sorted(set(security_closes) & set(benchmark_closes))
    if len(common_dates) < 16:
        return None
    security_returns = compute_returns([security_closes[d] for d in common_dates])
    benchmark_returns = compute_returns([benchmark_closes[d] for d in common_dates])
    if len(security_returns) < 15 or len(security_returns) != len(benchmark_returns):
        return None
    security_mean = sum(security_returns) / len(security_returns)
    benchmark_mean = sum(benchmark_returns) / len(benchmark_returns)
    covariance = sum(
        (s - security_mean) * (b - benchmark_mean) for s, b in zip(security_returns, benchmark_returns)
    ) / (len(security_returns) - 1)
    benchmark_variance = sum((b - benchmark_mean) ** 2 for b in benchmark_returns) / (len(benchmark_returns) - 1)
    if benchmark_variance == 0:
        return None
    beta = covariance / benchmark_variance
    alpha = security_mean - beta * benchmark_mean
    residuals = [s - alpha - beta * b for s, b in zip(security_returns, benchmark_returns)]
    n = len(residuals)
    residual_mean = sum(residuals) / n
    residual_variance = sum((r - residual_mean) ** 2 for r in residuals) / n
    residual_std = residual_variance ** 0.5
    if residual_std == 0:
        return None
    residual_skewness = (sum((r - residual_mean) ** 3 for r in residuals) / n) / (residual_std ** 3)
    return -residual_skewness


def downside_beta_score(
    security_id: str, as_of_time: datetime, data: AsOfDataView, *, lookback_days: int = 252,
) -> Optional[float]:
    """HYPOTHESIS -- Ang, Chen & Xing (2006, "Downside Risk," The
    Review of Financial Studies 19(4): 1191-1239): stocks whose returns
    covary MORE STRONGLY with the market specifically DURING market
    declines (a higher "downside beta") earn HIGHER subsequent returns
    -- a roughly 6%/year downside-risk premium in the original paper's
    own US sample, which the authors show survives controls for
    regular market beta, coskewness, liquidity risk, size, book-to-
    market, and momentum. Verified via WebSearch (paper's own abstract
    and citing summaries) rather than reconstructed from memory alone.

    **Distinct from `low_beta_score`, not a re-parameterization**:
    `low_beta_score` estimates ONE beta over the WHOLE window (up-days
    and down-days pooled together); this factor estimates beta
    CONDITIONAL ON the benchmark being in a down period only -- a
    security can have a low unconditional (pooled) beta yet still
    covary strongly with the market specifically on its worst days (a
    "crash-prone" security the pooled estimate would not flag), and
    vice versa, so the two scores can and do disagree on individual
    securities. Per the original paper's own convention, "downside" is
    defined relative to the benchmark's OWN trailing mean return over
    the same window (`benchmark_return < benchmark_mean`), not relative
    to zero.

    **Construction, a deliberate simplification of the original paper's
    own estimator, flagged the same way `low_beta_score` flags its
    own**: the original paper computes beta over a downside-conditioned
    joint distribution using a 5-year/60-month rolling window and
    several averaging refinements across sub-periods; this
    implementation instead reuses `low_beta_score`'s own single-window
    `Cov/Var` OLS estimator directly, applied only to the subset of
    paired trading days where the benchmark return is below its own
    trailing mean over the same `lookback_days` window (default 252,
    ~1 trading year, matching `low_beta_score`'s own default).

    Score is the RAW (NOT negated) downside beta -- unlike
    `low_beta_score`, where a LOWER beta is hypothesized more
    attractive, here a HIGHER downside beta is the paper's own
    hypothesized direction, the same "no negation needed" situation
    `illiquidity_score`/`fifty_two_week_high_score` already document.
    Needs at least 20 DOWNSIDE-day paired observations (matching
    `low_beta_score`'s own full-window floor, applied here to the
    smaller downside-only subset) and non-zero downside benchmark
    variance; `None` below that."""
    padded_days = int(lookback_days * 1.6)
    security_bars = trim_to_lookback(
        data.get_bars(security_id, as_of_time - timedelta(days=padded_days), as_of_time), lookback_days,
    )
    benchmark_bars = trim_to_lookback(
        data.get_bars(BENCHMARK_SYMBOL, as_of_time - timedelta(days=padded_days), as_of_time), lookback_days,
    )
    if len(security_bars) < 2 or len(benchmark_bars) < 2:
        return None
    security_closes = {b.timestamp.date(): (b.adjusted_close or b.close) for b in security_bars}
    benchmark_closes = {b.timestamp.date(): (b.adjusted_close or b.close) for b in benchmark_bars}
    common_dates = sorted(set(security_closes) & set(benchmark_closes))
    if len(common_dates) < 21:
        return None
    security_returns = compute_returns([security_closes[d] for d in common_dates])
    benchmark_returns = compute_returns([benchmark_closes[d] for d in common_dates])
    if len(security_returns) < 20 or len(security_returns) != len(benchmark_returns):
        return None
    benchmark_mean = sum(benchmark_returns) / len(benchmark_returns)
    downside_pairs = [
        (s, b) for s, b in zip(security_returns, benchmark_returns) if b < benchmark_mean
    ]
    if len(downside_pairs) < 20:
        return None
    downside_security = [p[0] for p in downside_pairs]
    downside_benchmark = [p[1] for p in downside_pairs]
    ds_mean = sum(downside_security) / len(downside_security)
    db_mean = sum(downside_benchmark) / len(downside_benchmark)
    covariance = sum(
        (s - ds_mean) * (b - db_mean) for s, b in zip(downside_security, downside_benchmark)
    ) / (len(downside_pairs) - 1)
    downside_variance = sum((b - db_mean) ** 2 for b in downside_benchmark) / (len(downside_pairs) - 1)
    if downside_variance == 0:
        return None
    return covariance / downside_variance


def coskewness_score(
    security_id: str, as_of_time: datetime, data: AsOfDataView, *, lookback_days: int = 252,
) -> Optional[float]:
    """HYPOTHESIS -- Harvey & Siddique (2000, "Conditional Skewness in
    Asset Pricing Tests," The Journal of Finance 55(3): 1263-1295): one
    of the most-cited papers in the asset-pricing literature (an
    explicit "S-tier" request from the account owner, "논문쪽에서 S급이라
    판단되는 것들로", after this session had already mined a long tail of
    single-paper anomalies). Investors with non-increasing absolute risk
    aversion prefer POSITIVE skewness and are averse to NEGATIVE
    skewness; a stock whose returns covary NEGATIVELY with the
    market's own squared excess return (negative coskewness -- it makes
    the investor's overall portfolio distribution more left-skewed, a
    less desirable shape) is hypothesized to earn a HIGHER subsequent
    return as compensation, while positive coskewness (the stock
    improves portfolio skewness) commands a valuation premium and thus a
    LOWER subsequent return. The original paper's own long-short
    coskewness factor earned 3.60%/year in its sample. Formula verified
    against a primary source (the paper's own author's institutional
    page, people.duke.edu/~charvey) rather than reconstructed from
    memory alone, per this module's established citation-verification
    discipline (the same standard already applied to the Corwin-Schultz
    estimator this session).

    **A genuinely different construct from every other co-movement or
    shape statistic already in this module**: `low_beta_score`/
    `downside_beta_score` are LINEAR co-movement with the market (first
    moment, Cov/Var); `idiosyncratic_skewness_score` is the SHAPE of a
    security's own residual distribution in isolation (no market
    co-movement information at all); this factor is co-movement between
    a security's own returns and the market's SQUARED excess return --
    a third-moment cross term distinct from all of the above. A security
    can have a defensive (low) beta yet still have strongly negative
    coskewness (crashes hard specifically alongside big market moves in
    either direction), or vice versa, so this score can and does
    disagree with every other risk factor here on an individual
    security.

    Per the verified formula: `CSK_i = E[e_i * e_m^2] / sqrt(Var(e_i) *
    Var(e_m))`, where `e_i`/`e_m` are the security's and the benchmark's
    own demeaned excess returns over the trailing window (population,
    not sample, moments, matching the primary source's own `1/T`
    normalization exactly). **A deliberate simplification of the
    original paper's own estimator, flagged the same way `low_beta_score`/
    `downside_beta_score` flag theirs**: the original paper uses MONTHLY
    returns over a rolling multi-year window; this implementation uses
    DAILY returns over the trailing `lookback_days` (default 252, ~1
    trading year), the same daily-proxy-for-a-longer-horizon-measure
    simplification `low_beta_score`/`downside_beta_score` already make
    for their own market-co-movement estimators, needing zero new data.

    Score is the NEGATIVE of `CSK_i` (higher score = more negative
    coskewness = more attractive, matching this module's convention and
    the paper's own "negative coskewness earns a higher return"
    finding). Needs at least 20 paired daily observations (matching
    `low_beta_score`'s own floor) and non-zero variance in both series;
    `None` below that."""
    padded_days = int(lookback_days * 1.6)
    security_bars = trim_to_lookback(
        data.get_bars(security_id, as_of_time - timedelta(days=padded_days), as_of_time), lookback_days,
    )
    benchmark_bars = trim_to_lookback(
        data.get_bars(BENCHMARK_SYMBOL, as_of_time - timedelta(days=padded_days), as_of_time), lookback_days,
    )
    if len(security_bars) < 2 or len(benchmark_bars) < 2:
        return None
    security_closes = {b.timestamp.date(): (b.adjusted_close or b.close) for b in security_bars}
    benchmark_closes = {b.timestamp.date(): (b.adjusted_close or b.close) for b in benchmark_bars}
    common_dates = sorted(set(security_closes) & set(benchmark_closes))
    if len(common_dates) < 21:
        return None
    security_returns = compute_returns([security_closes[d] for d in common_dates])
    benchmark_returns = compute_returns([benchmark_closes[d] for d in common_dates])
    if len(security_returns) < 20 or len(security_returns) != len(benchmark_returns):
        return None
    n = len(security_returns)
    security_mean = sum(security_returns) / n
    benchmark_mean = sum(benchmark_returns) / n
    security_demeaned = [s - security_mean for s in security_returns]
    benchmark_demeaned = [b - benchmark_mean for b in benchmark_returns]
    numerator = sum(ei * (em ** 2) for ei, em in zip(security_demeaned, benchmark_demeaned)) / n
    security_variance = sum(ei ** 2 for ei in security_demeaned) / n
    benchmark_variance = sum(em ** 2 for em in benchmark_demeaned) / n
    denominator = (security_variance * benchmark_variance) ** 0.5
    if denominator == 0:
        return None
    coskewness = numerator / denominator
    return -coskewness


def high_volume_return_premium_score(
    security_id: str, as_of_time: datetime, data: AsOfDataView, *, recent_days: int = 5, baseline_days: int = 50,
) -> Optional[float]:
    """HYPOTHESIS -- Gervais, Kaniel & Mingelgrin (2001, "The High-
    Volume Return Premium," The Journal of Finance 56(3): 877-919):
    stocks with UNUSUALLY HIGH trading volume over a recent short window
    (relative to their own normal trading activity) tend to APPRECIATE
    over the following month -- the authors' own explanation is that a
    volume shock raises a stock's visibility, drawing in new buyers and
    temporarily lifting demand and price. Verified via WebSearch (the
    paper's own citation and finding) rather than reconstructed from
    memory alone.

    **Distinct from every other volume/liquidity factor already in this
    module**: `illiquidity_score` (Amihud 2002) and `bid_ask_spread_score`
    (Corwin & Schultz 2012) are both about price IMPACT/COST of trading;
    `share_turnover_score` (Datar, Naik & Radcliffe 1998) is the LEVEL
    of turnover relative to shares outstanding, averaged over a full
    year. This factor is about a RECENT CHANGE in a security's OWN
    volume relative to its OWN normal baseline -- a security can have
    low illiquidity, low turnover, and yet still show an unusual recent
    volume spike (or vice versa), so all four can and do disagree on an
    individual security.

    Construction: `average_volume(recent_days) / average_volume(baseline_days
    immediately before that) - 1` -- the paper's own "abnormal volume"
    concept, here a simple ratio-to-prior-baseline rather than the
    paper's own more elaborate standardized-unexpected-volume regression
    model (a deliberate simplification, flagged the same way `low_beta_score`
    flags its own). Defaults (`recent_days=5`, `baseline_days=50`) match
    the paper's own "daily/weekly volume shock, ~monthly baseline"
    characterization. Score is RAW (not negated) -- higher abnormal
    volume is the paper's own hypothesized more-attractive direction,
    the same "no negation needed" situation `illiquidity_score` already
    documents. Needs zero new real ingestion -- `volume` is already a
    required `PriceBar` field. `None` unless both windows are fully
    populated with valid (non-negative) volume and the baseline average
    is positive."""
    total_days = recent_days + baseline_days
    padded_days = int(total_days * 1.6)
    bars = trim_to_lookback(
        data.get_bars(security_id, as_of_time - timedelta(days=padded_days), as_of_time), total_days,
    )
    if len(bars) < total_days:
        return None
    baseline_bars, recent_bars = bars[:-recent_days], bars[-recent_days:]
    baseline_volumes = [b.volume for b in baseline_bars if b.volume is not None and b.volume >= 0]
    recent_volumes = [b.volume for b in recent_bars if b.volume is not None and b.volume >= 0]
    if len(baseline_volumes) < baseline_days or len(recent_volumes) < recent_days:
        return None
    baseline_avg = sum(baseline_volumes) / len(baseline_volumes)
    if baseline_avg <= 0:
        return None
    recent_avg = sum(recent_volumes) / len(recent_volumes)
    return recent_avg / baseline_avg - 1.0


def _fy_records(repository, security_id: str, concept: str, as_of_time: datetime) -> list:
    """Every annual (`fiscal_period == "FY"`) `FundamentalRecord` for
    `(security_id, concept)` already knowable `as_of_time`, oldest
    first. Restricted to `"FY"` rather than using `repository.
    latest_known_value` directly (which does not distinguish fiscal
    periods): `NetIncomeLoss` is reported at both quarterly and annual
    granularity under the same XBRL tag, and mixing a single quarter's
    net income against a full fiscal year's `StockholdersEquity` would
    understate ROE by roughly 4x with no warning -- an honest but
    genuinely mismatched-period bug this restriction avoids entirely, at
    the cost of these scores only updating once per fiscal year rather
    than every quarter. `Assets`/`Liabilities`/`StockholdersEquity`
    (instant/balance-sheet concepts) are also reported at each period's
    end including `"FY"`, so this same filter anchors both sides of a
    ratio (or, for `asset_growth_score`, both years of a YoY comparison)
    on the same fiscal year-end date."""
    records = [r for r in repository.get_fundamentals(security_id, concept, as_of_time) if r.fiscal_period == "FY"]
    records.sort(key=lambda r: (r.period_end, r.available_time))
    return records


def _latest_fiscal_year_value(repository, security_id: str, concept: str, as_of_time: datetime):
    """The most recent of `_fy_records`, or `None` if there is none yet."""
    records = _fy_records(repository, security_id, concept, as_of_time)
    if not records:
        return None
    return records[-1]


def _quarterly_records(repository, security_id: str, concept: str, as_of_time: datetime) -> list:
    """Every quarterly (`fiscal_period` in `{"Q1", "Q2", "Q3", "Q4"}`)
    `FundamentalRecord` for `(security_id, concept)` already knowable
    `as_of_time`, one per distinct `period_end` (the latest-filed value
    when a period was later restated), oldest first. `sue_score` (the
    first score in this module to need quarter-level rather than
    fiscal-year-level data) indexes this list by position to find "4
    quarters ago" -- a duplicate or restated entry sharing a
    `period_end` with an earlier filing would shift that indexing if
    both were kept, exactly the mismatched-period risk `_fy_records`'s
    own docstring already describes for a different reason; deduping to
    one canonical value per `period_end` (the one with the latest
    `available_time`, i.e. the most recently filed) avoids it here the
    same way."""
    by_period_end: dict = {}
    for record in repository.get_fundamentals(security_id, concept, as_of_time):
        if record.fiscal_period not in ("Q1", "Q2", "Q3", "Q4"):
            continue
        existing = by_period_end.get(record.period_end)
        if existing is None or record.available_time > existing.available_time:
            by_period_end[record.period_end] = record
    return [by_period_end[period_end] for period_end in sorted(by_period_end)]


def _fy_ratio(
    repository: object, security_id: str, as_of_time: datetime, numerator_concept: str, denominator_concept: str,
) -> Optional[float]:
    """Shared plumbing for every ratio-shaped fundamentals factor below
    -- both figures restricted to the same fiscal year-end via
    `_latest_fiscal_year_value` (so numerator and denominator are always
    period-matched), `None` (never a fabricated ratio) when either
    figure is missing or the denominator is zero/negative. A
    zero/negative denominator is rejected uniformly across every caller
    below (equity, assets, revenue) since none of `roe_score`/
    `roa_score`/`net_margin_score`/`leverage_score` can produce a
    financially meaningful ratio against a non-positive base -- a
    company with negative equity or revenue makes the ratio
    uninterpretable as the "quality" signal it is meant to be, not
    merely differently signed."""
    numerator = _latest_fiscal_year_value(repository, security_id, numerator_concept, as_of_time)
    denominator = _latest_fiscal_year_value(repository, security_id, denominator_concept, as_of_time)
    if numerator is None or denominator is None:
        return None
    if denominator.value <= 0:
        return None
    return numerator.value / denominator.value


def roe_score(security_id: str, as_of_time: datetime, repository: object) -> Optional[float]:
    """HYPOTHESIS -- Return on Equity (net income / stockholders'
    equity) as a "quality" factor: companies that generate more profit
    per dollar of shareholder capital are hypothesized to have better
    forward returns than a naive earnings-level comparison would
    suggest. A well-documented, independently pre-existing candidate
    (quality-factor literature, e.g. Novy-Marx 2013's profitability
    factor is closely related) -- chosen as this project's first
    fundamentals-based signal specifically because it needs no new
    data beyond what `ADR-0042`'s ingestion already collected
    (`NetIncomeLoss`, `StockholdersEquity`), unlike a price-based value
    factor (P/E, P/B), which would additionally need shares-outstanding
    data not yet ingested.

    `repository` is duck-typed to `storage.fundamentals_repository.
    DuckDBFundamentalsRepository`'s shape (`get_fundamentals`) --
    not imported by type here, matching `strategy_research.signal_ic.
    compute_fundamentals_ic_series`'s identical choice to keep this
    package free of a new dependency on `storage.*`."""
    return _fy_ratio(repository, security_id, as_of_time, "NetIncomeLoss", "StockholdersEquity")


def roa_score(security_id: str, as_of_time: datetime, repository: object) -> Optional[float]:
    """HYPOTHESIS -- Return on Assets (net income / total assets), a
    profitability factor distinct from `roe_score`: ROE can be inflated
    by leverage alone (two companies with identical operating
    profitability but different debt loads have different ROE, since
    equity -- assets minus liabilities -- shrinks as leverage rises),
    while ROA is unlevered and measures how efficiently a company's
    total asset base (however financed) generates profit. Added
    alongside `roe_score` specifically to give the fundamentals domain
    a second, independently-motivated try after ROE's own null real
    result (`docs/research/STRATEGY-VALIDATION-REPORT.md` Section G),
    since one factor from a new data domain was too small a sample to
    conclude much from on its own."""
    return _fy_ratio(repository, security_id, as_of_time, "NetIncomeLoss", "Assets")


def net_margin_score(security_id: str, as_of_time: datetime, repository: object) -> Optional[float]:
    """HYPOTHESIS -- Net profit margin (net income / revenue): a pure
    profitability-per-dollar-of-sales factor, related to but distinct
    from ROE/ROA (neither assets nor equity enter it at all -- a
    capital-light, high-margin business and a capital-intensive,
    high-margin business score identically here, unlike ROA). Part of
    the same quality-factor family (e.g. gross-profitability research
    such as Novy-Marx 2013 uses a closely related profit-over-sales-or-
    assets construction)."""
    return _fy_ratio(repository, security_id, as_of_time, "NetIncomeLoss", "Revenues")


def gross_profitability_score(security_id: str, as_of_time: datetime, repository: object) -> Optional[float]:
    """HYPOTHESIS -- Novy-Marx (2013)'s gross profitability premium
    ("The Other Side of Value: The Gross Profitability Premium," The
    Journal of Financial Economics 108(1): 1-28): gross profit scaled
    by total assets, `(Revenues - CostOfGoodsAndServicesSold) / Assets`,
    predicts the cross-section of returns with roughly the same power
    as book-to-market -- companies with HIGHER gross profitability
    relative to their asset base are hypothesized to have relatively
    better forward returns. This project's `net_margin_score`'s own
    docstring already flagged this as "a closely related profit-over-
    sales-or-assets construction" without ever building the paper's
    OWN specific factor -- the citation audit (ADR-0047) correctly
    verified that existing hedge ("closely related," never claiming
    net_margin/ROE ARE Novy-Marx's factor) as honest, but a later
    re-check of the canonical anomaly list by name (the same lesson
    ADR-0043 Decisions 13-14 already applied to size/reversal/low-beta)
    found this project had still never built gross profitability
    itself, only factors related to it.

    Distinct from `net_margin_score` (profit/REVENUE) and `roa_score`
    (net income/assets): gross profit (revenue minus cost of goods
    sold, BEFORE operating expenses, R&D, interest, and taxes) scaled
    by assets is deliberately a less-processed, less accounting-
    discretion-prone profitability measure than net income -- Novy-
    Marx's own stated motivation is that "the further down the income
    statement one goes, ... the less related [it] is to true economic
    profitability," having been diluted by accounting distortions along
    the way. Needs zero new real ingestion: `Revenues` and
    `CostOfGoodsAndServicesSold` are both already ingested for
    `piotroski_f_score`'s gross-margin criterion, `Assets` for
    `roa_score`/`leverage_score`."""
    revenue_record = _latest_fiscal_year_value(repository, security_id, "Revenues", as_of_time)
    cogs_record = _latest_fiscal_year_value(repository, security_id, "CostOfGoodsAndServicesSold", as_of_time)
    assets_record = _latest_fiscal_year_value(repository, security_id, "Assets", as_of_time)
    if revenue_record is None or cogs_record is None or assets_record is None:
        return None
    if assets_record.value <= 0:
        return None
    gross_profit = revenue_record.value - cogs_record.value
    return gross_profit / assets_record.value


def leverage_score(security_id: str, as_of_time: datetime, repository: object) -> Optional[float]:
    """HYPOTHESIS -- the "low-leverage" anomaly: companies with LESS
    debt relative to equity are hypothesized to have relatively better
    risk-adjusted forward returns, part of the same broader "quality/
    safety" factor family the low-volatility anomaly belongs to (e.g.
    "low leverage" is one of the explicit pillars of Asness, Frazzini &
    Pedersen 2013's quality-minus-junk "safety" component).

    Score is the NEGATIVE of `Liabilities / StockholdersEquity`, so a
    higher score means LOWER (hypothesized more attractive) leverage --
    matches this module's convention (see `low_volatility_score`) that
    a higher score always ranks a security as more attractive."""
    ratio = _fy_ratio(repository, security_id, as_of_time, "Liabilities", "StockholdersEquity")
    if ratio is None:
        return None
    return -ratio


def asset_growth_score(security_id: str, as_of_time: datetime, repository: object) -> Optional[float]:
    """HYPOTHESIS -- the "asset growth anomaly" (Cooper, Gulen & Schill
    2008, "The Asset Growth Effect in Stock Returns," Journal of
    Finance): companies whose total assets grew fastest over the prior
    fiscal year tend to have LOWER subsequent returns than slower-
    growing peers, hypothesized to reflect investor over-extrapolation
    of past growth rather than a risk-based explanation -- and reported
    to hold even within large-cap stocks specifically, not just small
    caps, over a 40-year US sample.

    Distinct in kind from every other factor in this module: `roe_score`/
    `roa_score`/`net_margin_score`/`leverage_score` are all LEVELS at a
    single fiscal year-end, while this is a CHANGE across two consecutive
    fiscal years -- the first factor this project has built that needs
    more than one period's data. Needs no new data beyond what ADR-0042's
    ingestion already collects (`Assets`, one of the 5 default XBRL
    concepts, already ingested for `roa_score`/`leverage_score`) --
    chosen as this round's first candidate specifically because it is
    the only one of several externally-researched candidates testable
    with zero new real ingestion.

    Score is the NEGATIVE of `(current FY Assets / prior FY Assets) - 1`,
    so a higher score means LOWER (hypothesized more attractive) asset
    growth -- matches this module's convention (see `low_volatility_
    score`/`leverage_score`) that a higher score always ranks a security
    as more attractive. `None` (never a fabricated growth rate) unless
    at least two distinct fiscal years' `Assets` are both already known
    as of `as_of_time`, or the prior year's value is non-positive."""
    records = _fy_records(repository, security_id, "Assets", as_of_time)
    if len(records) < 2:
        return None
    current, prior = records[-1], records[-2]
    if prior.value <= 0:
        return None
    growth = current.value / prior.value - 1.0
    return -growth


# The 8 concepts (beyond `NetCashProvidedByUsedInOperatingActivities`,
# which only ever needs the current fiscal year) `piotroski_f_score`
# needs BOTH the current and prior fiscal year's value for.
_PIOTROSKI_TWO_YEAR_CONCEPTS = (
    "NetIncomeLoss", "Assets", "LongTermDebtNoncurrent", "AssetsCurrent",
    "LiabilitiesCurrent", "CommonStockSharesOutstanding", "Revenues",
    "CostOfGoodsAndServicesSold",
)


def piotroski_f_score(security_id: str, as_of_time: datetime, repository: object) -> Optional[float]:
    """HYPOTHESIS -- the Piotroski F-Score (Piotroski 2000, "Value
    Investing: The Use of Historical Financial Statement Information to
    Separate Winners from Losers," Journal of Accounting Research): a
    0-9 composite of nine binary year-over-year QUALITY-IMPROVEMENT
    signals (profitability, leverage/liquidity, operating efficiency),
    each worth 1 point if the company improved on that dimension versus
    the prior fiscal year. Firms scoring 8-9 outperformed low scorers
    (0-1) by a wide, independently-replicated margin in the original
    1976-1996 sample and again in a 2004-2024 out-of-sample re-test --
    the strongest, most-replicated candidate from this project's
    12-strategy literature search (ADR-0043 Decision 8), built second
    (after `asset_growth_score`) specifically because it needs new real
    data this project did not previously ingest.

    Distinct from `asset_growth_score` too: this is a COMPOSITE of nine
    signals, several of them themselves year-over-year changes -- not a
    single ratio or a single change. Needs 6 XBRL concepts beyond the 5
    ADR-0042 already ingests (`NetCashProvidedByUsedInOperatingActivities`,
    `LongTermDebtNoncurrent`, `AssetsCurrent`, `LiabilitiesCurrent`,
    `CommonStockSharesOutstanding`, `CostOfGoodsAndServicesSold`) -- a
    real new ingestion round in the user's own environment is required
    before this can be computed against real data (see
    `ingest_fundamentals_data.py`'s now-extended `_DEFAULT_CONCEPTS`).

    The nine signals (1 point each, higher score = more attractive,
    matching this module's convention):
    1. ROA (NetIncomeLoss/Assets) > 0
    2. Operating cash flow > 0
    3. ROA improved versus the prior fiscal year
    4. Operating cash flow > net income (accrual/earnings-quality check
       -- cash generation exceeds reported accounting profit)
    5. Long-term-debt-to-assets ratio decreased (less leverage)
    6. Current ratio (current assets / current liabilities) improved
    7. Shares outstanding did not increase (no dilutive new issuance)
    8. Gross margin ((Revenues - COGS) / Revenues) improved
    9. Asset turnover (Revenues / Assets) improved

    **Deliberately all-or-nothing, matching this module's existing
    honesty discipline (`_fy_ratio`'s missing-value handling)**: `None`
    (never a partial or fabricated score) unless every one of the 9
    concept-years above is actually known as of `as_of_time`. **A real,
    foreseeable coverage gap, stated here rather than discovered
    silently**: financial-sector filers (banks, insurers, broker-
    dealers) typically use an unclassified balance sheet under US GAAP
    and do not report `AssetsCurrent`/`LiabilitiesCurrent` at all --
    this score will likely return `None` for every financial-sector
    security in this project's universe (e.g. `JPM`/`GS`/`MS`/`WFC`/
    `AXP`/`BAC`), not a bug, an accurate reflection of what a bank's
    real filings actually report."""
    two_year: dict[str, tuple[float, float]] = {}
    for concept in _PIOTROSKI_TWO_YEAR_CONCEPTS:
        records = _fy_records(repository, security_id, concept, as_of_time)
        if len(records) < 2:
            return None
        two_year[concept] = (records[-2].value, records[-1].value)

    cfo_record = _latest_fiscal_year_value(
        repository, security_id, "NetCashProvidedByUsedInOperatingActivities", as_of_time,
    )
    if cfo_record is None:
        return None
    cfo = cfo_record.value

    prior_ni, current_ni = two_year["NetIncomeLoss"]
    prior_assets, current_assets = two_year["Assets"]
    prior_ltd, current_ltd = two_year["LongTermDebtNoncurrent"]
    prior_ca, current_ca = two_year["AssetsCurrent"]
    prior_cl, current_cl = two_year["LiabilitiesCurrent"]
    prior_shares, current_shares = two_year["CommonStockSharesOutstanding"]
    prior_rev, current_rev = two_year["Revenues"]
    prior_cogs, current_cogs = two_year["CostOfGoodsAndServicesSold"]

    # Every ratio below needs a positive denominator to be financially
    # meaningful -- same rejection discipline as `_fy_ratio`.
    if current_assets <= 0 or prior_assets <= 0:
        return None
    if current_cl <= 0 or prior_cl <= 0:
        return None
    if current_rev <= 0 or prior_rev <= 0:
        return None

    current_roa = current_ni / current_assets
    prior_roa = prior_ni / prior_assets
    current_leverage = current_ltd / current_assets
    prior_leverage = prior_ltd / prior_assets
    current_current_ratio = current_ca / current_cl
    prior_current_ratio = prior_ca / prior_cl
    current_gross_margin = (current_rev - current_cogs) / current_rev
    prior_gross_margin = (prior_rev - prior_cogs) / prior_rev
    current_asset_turnover = current_rev / current_assets
    prior_asset_turnover = prior_rev / prior_assets

    score = 0
    score += 1 if current_roa > 0 else 0
    score += 1 if cfo > 0 else 0
    score += 1 if current_roa > prior_roa else 0
    score += 1 if cfo > current_ni else 0
    score += 1 if current_leverage < prior_leverage else 0
    score += 1 if current_current_ratio > prior_current_ratio else 0
    score += 1 if current_shares <= prior_shares else 0
    score += 1 if current_gross_margin > prior_gross_margin else 0
    score += 1 if current_asset_turnover > prior_asset_turnover else 0
    return float(score)


def _latest_price(price_repository, security_id: str, as_of_time: datetime, *, lookback_days: int = 10) -> Optional[float]:
    """The most recent RAW (unadjusted) `close` at or before `as_of_time`,
    read directly from `price_repository.get_bars` with `as_of_time` as
    its own look-ahead guard (Phase 1 spec section 15) -- deliberately
    `close`, never `adjusted_close`: `adjusted_close` is back-adjusted
    for corporate actions that occur AFTER a bar's date, using a
    provider-dependent, mutable "adjust from present" convention (spec
    section 5.2), and is explicitly NOT the price that actually traded
    on that historical date. A market-cap calculation needs the actual
    contemporaneous traded price times the actual contemporaneous share
    count -- mixing a back-adjusted price with a raw share count would
    silently produce a wrong market cap with no error, which is exactly
    the kind of mistake this module's other factors avoid by using
    `adjusted_close or close` (correct for a RETURN calculation, wrong
    for this one)."""
    bars = price_repository.get_bars(
        security_id, as_of_time - timedelta(days=lookback_days), as_of_time, as_of_time=as_of_time,
    )
    if not bars:
        return None
    price = bars[-1].close
    if price is None or price <= 0:
        return None
    return price


def _fy_flow_or_zero(repository: object, security_id: str, concept: str, as_of_time: datetime) -> float:
    """`_latest_fiscal_year_value`, but a genuinely absent concept reads
    as `0.0` rather than `None` -- unlike every other missing-data case
    in this module. These three cash-flow line items
    (`shareholder_yield_score`'s numerator) are only ever tagged by a
    filer WHEN that activity actually happened, the standard SEC
    EDGAR/XBRL convention: a company that paid no dividends this fiscal
    year does not file a `PaymentsOfDividends` fact worth `$0`, it
    simply omits the tag entirely. Reading that omission as "no cash
    was returned this way" is the financially correct interpretation,
    not a fabrication in the sense this module otherwise guards against
    -- that guard is about inventing a value for data that IS meant to
    always exist but happens to be unknown (e.g. `roe_score` returning
    `None` rather than guessing at a missing `NetIncomeLoss`, which
    every filer reports every year)."""
    record = _latest_fiscal_year_value(repository, security_id, concept, as_of_time)
    return record.value if record is not None else 0.0


def shareholder_yield_score(
    security_id: str, as_of_time: datetime, fundamentals_repository: object, price_repository: object,
) -> Optional[float]:
    """HYPOTHESIS -- Shareholder Yield (O'Shaughnessy, "What Works on
    Wall Street"; related academic support: Boudoukh, Michaely,
    Richardson & Roberts 2007, "On the Importance of Measuring Payout
    Yield: Forecasting Stock Returns"): total cash RETURNED to
    shareholders (dividends paid, plus NET share buybacks -- buybacks
    minus new issuance) as a fraction of market capitalization,
    hypothesized to predict forward returns better than dividend yield
    alone, since dividend yield alone misclassifies a heavy-buyback,
    low-dividend firm as a low-payout firm -- buybacks have been the
    dominant payout channel for many large US firms since the 1980s-90s.

    The first factor in this module that needs price data at all
    (`price_repository`, for market capitalization) -- distinct in kind
    from every other fundamentals score here (`roe_score` through
    `piotroski_f_score`), all of which are ratios or changes entirely
    within the fundamentals repository. `signal_ic.compute_fundamentals_
    ic_series`'s `FundamentalsScoreFn` only ever passes `score_fn` the
    fundamentals repository, so this factor is wired through the new,
    separate `signal_ic.compute_hybrid_ic_series` instead (see that
    function's own docstring for why a new function rather than
    widening the existing one).

    Numerator = dividends paid + buybacks paid - proceeds from new share
    issuance, each the latest known fiscal year's `PaymentsOfDividends`/
    `PaymentsForRepurchaseOfCommonStock`/
    `ProceedsFromIssuanceOfCommonStock` -- each read as `0.0`, not
    `None`, when the concept is simply absent (see `_fy_flow_or_zero`'s
    own docstring for why that is the financially correct reading here,
    unlike every other missing-data case in this module). Denominator =
    market capitalization = latest known raw `close` price
    (`_latest_price`; deliberately never `adjusted_close` -- see that
    helper's docstring) times the latest known fiscal-year-end
    `CommonStockSharesOutstanding`. `None` (never a fabricated yield) if
    either the price or the share count is unknown, or market cap is
    non-positive.

    **A real, foreseeable limitation, stated here rather than discovered
    silently**: `CommonStockSharesOutstanding` only updates once per
    fiscal year in this project's data (the same `_fy_records`/`"FY"`-
    only restriction every other factor in this module uses), so the
    share count used can be up to ~1 year stale relative to `as_of_time`
    -- the same limitation `piotroski_f_score`'s leverage/liquidity
    ratios already carry, not new to this factor. Needs 3 new XBRL
    concepts beyond what `piotroski_f_score` already ingests
    (`PaymentsOfDividends`, `PaymentsForRepurchaseOfCommonStock`,
    `ProceedsFromIssuanceOfCommonStock`) -- a real new ingestion round
    in the user's own environment is required before this can be
    computed against real data (see `ingest_fundamentals_data.py`'s
    now-extended `_DEFAULT_CONCEPTS`)."""
    shares_record = _latest_fiscal_year_value(
        fundamentals_repository, security_id, "CommonStockSharesOutstanding", as_of_time,
    )
    if shares_record is None or shares_record.value <= 0:
        return None
    price = _latest_price(price_repository, security_id, as_of_time)
    if price is None:
        return None
    market_cap = price * shares_record.value
    if market_cap <= 0:
        return None

    dividends = _fy_flow_or_zero(fundamentals_repository, security_id, "PaymentsOfDividends", as_of_time)
    buybacks = _fy_flow_or_zero(
        fundamentals_repository, security_id, "PaymentsForRepurchaseOfCommonStock", as_of_time,
    )
    issuance = _fy_flow_or_zero(
        fundamentals_repository, security_id, "ProceedsFromIssuanceOfCommonStock", as_of_time,
    )

    return (dividends + buybacks - issuance) / market_cap


def sloan_accruals_score(security_id: str, as_of_time: datetime, repository: object) -> Optional[float]:
    """HYPOTHESIS -- the Sloan (1996) accruals anomaly ("Do Stock Prices
    Fully Reflect Information in Accruals and Cash Flows About Future
    Earnings?", The Accounting Review): companies whose earnings are
    made up more of ACCRUALS (the non-cash portion of net income) and
    less of actual operating CASH FLOW tend to have LOWER subsequent
    returns, hypothesized because investors overweight the persistence
    of accruals relative to cash flows (accruals reverse; cash flows
    are more persistent), and correct only once that overweighting
    becomes visible in later earnings. Independently replicated
    repeatedly, including internationally (Australia, Canada, UK) and
    as one of only two anomalies (alongside momentum) whose magnitude
    the Fama-French five-factor model does NOT shrink in the broad
    2020 "Replicating Anomalies" 447-factor study -- one of this
    project's stronger-replicated remaining candidates.

    Uses the Hribar & Collins (2002) cash-flow-statement definition
    (`NetIncomeLoss - CFO`, scaled by average total assets) rather than
    Sloan's original balance-sheet definition (change in non-cash
    working capital minus depreciation): the cash-flow version is less
    prone to measurement error from one-time events (M&A, discontinued
    operations) and, more concretely for this project, needs only
    concepts already ingested for `roa_score`/`piotroski_f_score`
    (`NetIncomeLoss`, `NetCashProvidedByUsedInOperatingActivities`,
    `Assets`) -- zero new real ingestion required, same as
    `asset_growth_score`.

    Score is the NEGATIVE of the accruals ratio, so a higher score
    means LOWER (hypothesized more attractive) accruals -- matches this
    module's convention (see `leverage_score`/`asset_growth_score`)
    that a higher score always ranks a security as more attractive.
    `None` (never a fabricated ratio) unless `NetIncomeLoss` and CFO are
    both known for the latest fiscal year and at least two distinct
    fiscal years' `Assets` are known, or average assets is
    non-positive."""
    ni_record = _latest_fiscal_year_value(repository, security_id, "NetIncomeLoss", as_of_time)
    cfo_record = _latest_fiscal_year_value(
        repository, security_id, "NetCashProvidedByUsedInOperatingActivities", as_of_time,
    )
    if ni_record is None or cfo_record is None:
        return None
    asset_records = _fy_records(repository, security_id, "Assets", as_of_time)
    if len(asset_records) < 2:
        return None
    avg_assets = (asset_records[-2].value + asset_records[-1].value) / 2.0
    if avg_assets <= 0:
        return None
    accruals = (ni_record.value - cfo_record.value) / avg_assets
    return -accruals


def dividend_growth_score(security_id: str, as_of_time: datetime, repository: object) -> Optional[float]:
    """HYPOTHESIS -- a dividend growth factor: companies growing their
    dividend payouts fastest year-over-year are hypothesized to have
    relatively better forward returns, read as a quality/confidence
    signal (a company raising its payout is implicitly signaling
    management's confidence in sustained future earnings) distinct from
    a static dividend-YIELD level. Academic evidence on dividend GROWTH
    predictability specifically (as opposed to aggregate market return
    predictability from the dividend-price ratio, a separate and more
    contested literature) is comparatively consistent across the US,
    UK, Canada, Germany, France and Japan, and high-dividend-growth
    stocks show a documented monotonic relation with higher risk-
    adjusted mean returns even after three/four-factor model
    adjustment.

    Structurally the same shape as `asset_growth_score` (a single
    year-over-year change, reusing `_fy_records`), but on
    `PaymentsOfDividends` instead of `Assets`, and NOT negated -- growth
    is hypothesized POSITIVELY related here, the opposite sign
    relationship from asset growth. Needs zero new real ingestion:
    `PaymentsOfDividends` is already one of `shareholder_yield_score`'s
    3 XBRL concepts (ADR-0043 Decision 10).

    **A real, foreseeable coverage gap, stated here rather than found
    silently later**: a company with no dividend paid in the prior
    fiscal year (either a non-payer, or one that just initiated a
    dividend) has no computable growth RATE from a zero base -- `None`
    in that case, same discipline as `asset_growth_score`'s
    non-positive-prior-value guard. This means the score is structurally
    only ever defined for companies that were ALREADY paying a dividend
    in the prior fiscal year, not a bug, an accurate reflection of what
    a growth rate from zero means."""
    records = _fy_records(repository, security_id, "PaymentsOfDividends", as_of_time)
    if len(records) < 2:
        return None
    prior, current = records[-2].value, records[-1].value
    if prior <= 0:
        return None
    return current / prior - 1.0


def earnings_yield_score(
    security_id: str, as_of_time: datetime, fundamentals_repository: object, price_repository: object,
) -> Optional[float]:
    """HYPOTHESIS -- earnings yield (Basu 1977, "Investment Performance
    of Common Stocks in Relation to Their Price-Earnings Ratios: A Test
    of the Efficient Market Hypothesis," The Journal of Finance): the
    original, most-replicated value anomaly -- companies with a LOWER
    price relative to earnings (equivalently, a HIGHER earnings-to-price
    ratio) tend to have relatively better forward returns. The value leg
    of ADR-0043 Decision 8's "Value+Momentum combination" candidate,
    built standalone rather than as the literal published combination --
    see the module-level note below this function for why.

    The first genuine PRICE-based valuation ratio this project has
    tested: every earlier fundamentals factor here (`roe_score` through
    `sloan_accruals_score`) is a ratio or change entirely within
    financial-statement figures, never comparing a fundamental to the
    market's OWN pricing of the company the way a P/E-style ratio does.
    Needs price data (market capitalization), so -- like
    `shareholder_yield_score` -- is wired through `signal_ic.
    compute_hybrid_ic_series` rather than `compute_fundamentals_ic_series`.

    Score = `NetIncomeLoss / market_cap` (market cap computed exactly as
    `shareholder_yield_score` does: latest known RAW `close`, never
    `adjusted_close`, times latest known fiscal-year-end
    `CommonStockSharesOutstanding` -- see `_latest_price`'s own
    docstring for why raw, not adjusted). `None` (never a fabricated
    yield) if net income, price, or share count is unknown, or market
    cap is non-positive. Needs zero new real ingestion: `NetIncomeLoss`
    and `CommonStockSharesOutstanding` are already ingested for
    `roe_score`/`piotroski_f_score`, and the price catalog already
    exists for `shareholder_yield_score`.

    **Fama & French (1992) found book-to-market has more discriminatory
    power than earnings yield for separating value from growth stocks in
    their specific sample, and the two are correlated but distinct value
    proxies** -- stated here rather than left implicit, since this
    project has no book-value-per-share data ingested and cannot test a
    book-to-market variant without a new XBRL concept
    (`StockholdersEquity` is already ingested for `roe_score`, so a
    future `book_to_market_score` would actually need zero new data too
    -- a natural next candidate, not built this round)."""
    ni_record = _latest_fiscal_year_value(fundamentals_repository, security_id, "NetIncomeLoss", as_of_time)
    if ni_record is None:
        return None
    shares_record = _latest_fiscal_year_value(
        fundamentals_repository, security_id, "CommonStockSharesOutstanding", as_of_time,
    )
    if shares_record is None or shares_record.value <= 0:
        return None
    price = _latest_price(price_repository, security_id, as_of_time)
    if price is None:
        return None
    market_cap = price * shares_record.value
    if market_cap <= 0:
        return None
    return ni_record.value / market_cap


# Session 36 -- the "momentum" half of Decision 8's "Value+Momentum
# combination" candidate is deliberately NOT built here: this project
# already has a real, observed IC result for the exact shared
# `_momentum_score` used by `long_term_momentum`/
# `risk_controlled_momentum` (`docs/research/STRATEGY-VALIDATION-REPORT.md`
# Section G's evidence table -- mean_ic = -0.0078, read as "null"), so
# building a fresh standalone momentum factor now would re-test an
# already-null signal under a cosmetically different name, exactly what
# `compute_signal_ic_from_catalog.py`'s own module docstring says this
# project avoids doing. `earnings_yield_score` above is therefore built
# and tested alone, not as the literal equal-weight rank-combination
# Asness, Moskowitz & Pedersen (2013) publish -- that combination step
# would also need new cross-sectional architecture this project does
# not have (every `ScoreFn`/`FundamentalsScoreFn`/`HybridScoreFn` scores
# ONE security at a time with no visibility into the rest of the
# universe at that moment, so a rank-average-across-the-universe
# combining step cannot be expressed as an ordinary score_fn without a
# new IC-series layer analogous to `compute_hybrid_ic_series`). Revisit
# only if `earnings_yield_score`'s own real IC result is promising
# enough to justify that additional architecture.


def book_to_market_score(
    security_id: str, as_of_time: datetime, fundamentals_repository: object, price_repository: object,
) -> Optional[float]:
    """HYPOTHESIS -- book-to-market (Fama & French 1992, "The
    Cross-Section of Expected Stock Returns," The Journal of Finance;
    the anomaly itself traces to Rosenberg, Reid & Lanstein 1985): the
    single most canonical value factor in the academic literature and
    the basis of the Fama-French three-factor model's HML factor --
    companies with a HIGHER book value of equity relative to market
    value tend to have relatively better forward returns. Fama & French
    (1992) themselves found book-to-market has more discriminatory
    power than earnings yield for separating value from growth stocks
    in their sample -- `earnings_yield_score`'s own docstring already
    flagged this as the natural next candidate, needing zero new data.

    Score = `StockholdersEquity / market_cap`, computed identically to
    `earnings_yield_score` (same market-cap denominator, same
    `_latest_price`/raw-close discipline), substituting
    `StockholdersEquity` for `NetIncomeLoss` in the numerator. A
    negative book value (rare but real) produces a negative score under
    this module's higher-is-better convention -- directionally correct
    (a negative-book-value company is not a "cheap value" situation),
    so unlike `_fy_ratio`'s denominator guard, no extra guard is needed
    on the numerator's sign here. One of the 5 (of the original 6) legs
    of `value_composite_score` below (ADR-0043 Decision 12) -- also
    independently testable on its own via `compute_hybrid_ic_series`.
    Needs zero new real ingestion: `StockholdersEquity` is one of the 5
    original ADR-0042 concepts."""
    equity_record = _latest_fiscal_year_value(fundamentals_repository, security_id, "StockholdersEquity", as_of_time)
    if equity_record is None:
        return None
    shares_record = _latest_fiscal_year_value(
        fundamentals_repository, security_id, "CommonStockSharesOutstanding", as_of_time,
    )
    if shares_record is None or shares_record.value <= 0:
        return None
    price = _latest_price(price_repository, security_id, as_of_time)
    if price is None:
        return None
    market_cap = price * shares_record.value
    if market_cap <= 0:
        return None
    return equity_record.value / market_cap


def sales_yield_score(
    security_id: str, as_of_time: datetime, fundamentals_repository: object, price_repository: object,
) -> Optional[float]:
    """HYPOTHESIS -- price-to-sales inverted to a "yield" (O'Shaughnessy,
    "What Works on Wall Street"; independently examined by Senchack &
    Martin 1987, "The Relative Performance of the PSR and PER Investment
    Strategies," Financial Analysts Journal): revenue relative to market
    cap as a value proxy, argued to be more stable than earnings-based
    ratios since revenue is far less prone to accounting manipulation or
    one-time items than net income.

    Score = `Revenues / market_cap`, same construction as
    `earnings_yield_score`/`book_to_market_score`. Unlike book value,
    revenue non-positive is rejected (`None`) rather than left to
    produce a directionally-meaningful negative score -- a
    non-positive-revenue "value" ratio is not interpretable the way a
    negative book value still is. One of the 5 legs of
    `value_composite_score` below. Needs zero new real ingestion:
    `Revenues` is one of the 5 original ADR-0042 concepts."""
    revenue_record = _latest_fiscal_year_value(fundamentals_repository, security_id, "Revenues", as_of_time)
    if revenue_record is None or revenue_record.value <= 0:
        return None
    shares_record = _latest_fiscal_year_value(
        fundamentals_repository, security_id, "CommonStockSharesOutstanding", as_of_time,
    )
    if shares_record is None or shares_record.value <= 0:
        return None
    price = _latest_price(price_repository, security_id, as_of_time)
    if price is None:
        return None
    market_cap = price * shares_record.value
    if market_cap <= 0:
        return None
    return revenue_record.value / market_cap


def cashflow_yield_score(
    security_id: str, as_of_time: datetime, fundamentals_repository: object, price_repository: object,
) -> Optional[float]:
    """HYPOTHESIS -- price-to-cash-flow inverted to a "yield"
    (O'Shaughnessy, "What Works on Wall Street"): operating cash flow
    relative to market cap, argued to be a value proxy less distorted
    by accrual-based earnings management than an earnings-yield ratio
    -- the same accrual-quality concern `sloan_accruals_score` tests
    directly, here applied to a valuation ratio instead of a
    stock-selection signal in its own right.

    Score = `CFO / market_cap`. A negative CFO (real for early-stage or
    cash-burning companies) produces a negative score, directionally
    correct under this module's convention -- no extra guard needed
    beyond the missing-data checks. One of the 5 legs of
    `value_composite_score` below. Needs zero new real ingestion:
    `NetCashProvidedByUsedInOperatingActivities` is already ingested
    for `piotroski_f_score`/`sloan_accruals_score`."""
    cfo_record = _latest_fiscal_year_value(
        fundamentals_repository, security_id, "NetCashProvidedByUsedInOperatingActivities", as_of_time,
    )
    if cfo_record is None:
        return None
    shares_record = _latest_fiscal_year_value(
        fundamentals_repository, security_id, "CommonStockSharesOutstanding", as_of_time,
    )
    if shares_record is None or shares_record.value <= 0:
        return None
    price = _latest_price(price_repository, security_id, as_of_time)
    if price is None:
        return None
    market_cap = price * shares_record.value
    if market_cap <= 0:
        return None
    return cfo_record.value / market_cap


def share_turnover_score(
    security_id: str, as_of_time: datetime, fundamentals_repository: object, price_repository: object,
    *, lookback_days: int = 252,
) -> Optional[float]:
    """HYPOTHESIS -- Datar, Naik & Radcliffe (1998, "Liquidity and
    Stock Returns: An Alternative Test," Journal of Financial Markets
    1(2): 203-219): stock returns are a DECREASING function of share
    turnover (shares traded as a fraction of shares outstanding) --
    an alternative test of Amihud & Mendelson (1986)'s liquidity-premium
    hypothesis (the same paper `bid_ask_spread_score` already cites for
    its own bid-ask-spread-based liquidity measure) using a volume-based
    proxy instead. The original paper's own finding: the high average
    return of LOW-turnover stocks represents a liquidity premium --
    illiquid (low-turnover, hard to trade quickly) stocks earn higher
    subsequent returns, so HIGH turnover predicts LOWER returns.
    Verified via WebSearch (paper's own construction and finding, "stock
    returns are a decreasing function of the turnover rates") rather
    than reconstructed from memory alone.

    **Distinct from `illiquidity_score` and `bid_ask_spread_score`, a
    THIRD independent liquidity proxy, not a re-parameterization of
    either**: `illiquidity_score` (Amihud 2002) is price-impact-based
    (how much a given DOLLAR of trading moves the price); this factor is
    volume-based (how much of the OUTSTANDING SHARE COUNT trades, with
    no reference to price impact at all); `bid_ask_spread_score` (Corwin
    & Schultz 2012, measuring Amihud & Mendelson 1986) is a high-low-
    range-based transaction-cost proxy referencing neither dollar volume
    nor share count. A stock can have low dollar-volume price impact
    (low Amihud ILLIQ) yet a low fraction of its own huge share count
    turning over (low turnover, still "illiquid" by this measure), and
    vice versa, so the three can and do disagree on individual
    securities.

    Turnover for one trading day is `volume / shares_outstanding` (the
    paper's own TR definition); this implementation averages that ratio
    over the trailing `lookback_days` (default 252, ~1 trading year,
    matching `illiquidity_score`'s own annual-averaging convention
    rather than the paper's own within-year sub-period refinements) using
    the single latest known `CommonStockSharesOutstanding` fiscal-year
    value as of `as_of_time` (already ingested for `size_score`/
    `book_to_market_score`, needing ZERO new data) as a constant
    denominator across the window -- a deliberate simplification, since
    shares outstanding do change intra-year (buybacks/issuance) but this
    project has no daily shares-outstanding series, only annual XBRL
    filings, the same granularity constraint every other market-cap-
    based factor in this module already accepts.

    Score is the NEGATIVE of average daily turnover, so a LOWER turnover
    (hypothesized more attractive, per the paper's own finding) produces
    a HIGHER score -- matches this module's convention. `None` unless
    `CommonStockSharesOutstanding` is known and positive, and at least
    20 valid daily volume observations exist (matching
    `illiquidity_score`'s own floor)."""
    shares_record = _latest_fiscal_year_value(
        fundamentals_repository, security_id, "CommonStockSharesOutstanding", as_of_time,
    )
    if shares_record is None or shares_record.value <= 0:
        return None
    bars = trim_to_lookback(
        price_repository.get_bars(
            security_id, as_of_time - timedelta(days=int(lookback_days * 1.6)), as_of_time, as_of_time=as_of_time,
        ),
        lookback_days,
    )
    turnovers = [b.volume / shares_record.value for b in bars if b.volume is not None and b.volume >= 0]
    if len(turnovers) < 20:
        return None
    return -(sum(turnovers) / len(turnovers))


def size_score(
    security_id: str, as_of_time: datetime, fundamentals_repository: object, price_repository: object,
) -> Optional[float]:
    """HYPOTHESIS -- the "size effect" (Banz 1981, "The Relationship
    Between Return and Market Value of Common Stocks," Journal of
    Financial Economics 9(1): 3-18): smaller companies (by market
    capitalization) have historically earned higher risk-adjusted
    returns than larger ones. One of the oldest and most famous
    documented anomalies in asset pricing -- predates, and is the direct
    ancestor of, the Fama-French three-factor model's SMB ("small minus
    big") factor. Distinct in kind from every other factor in this
    module: this is the one candidate from the classic small-cap-
    premium/SMB literature this project had never built, despite
    already having the exact market-cap-computation machinery this
    needs (identical to `book_to_market_score`/`sales_yield_score`/
    `cashflow_yield_score`, just without a fundamentals-ratio numerator).

    Score is the NEGATIVE of `market_cap` (`_latest_price *
    CommonStockSharesOutstanding`, same raw-close discipline as every
    other market-cap-based score in this module -- see `_latest_price`),
    so a higher score means a SMALLER (hypothesized more attractive)
    company, matching this module's convention that a higher score
    always ranks a security as more attractive. Since IC is computed via
    Spearman rank correlation (`signal_ic.spearman_ic`), using raw
    `market_cap` rather than `log(market_cap)` (the more common
    transform in academic regressions, used there to tame market cap's
    heavy right skew for OLS) makes no difference to the resulting IC --
    any monotonic transform preserves rank order identically. Needs zero
    new real ingestion: `CommonStockSharesOutstanding` is already
    ingested for every other market-cap-based score this session."""
    shares_record = _latest_fiscal_year_value(
        fundamentals_repository, security_id, "CommonStockSharesOutstanding", as_of_time,
    )
    if shares_record is None or shares_record.value <= 0:
        return None
    price = _latest_price(price_repository, security_id, as_of_time)
    if price is None:
        return None
    market_cap = price * shares_record.value
    if market_cap <= 0:
        return None
    return -market_cap


def altman_z_score(
    security_id: str, as_of_time: datetime, fundamentals_repository: object, price_repository: object,
) -> Optional[float]:
    """HYPOTHESIS -- Altman (1968) Z-Score ("Financial Ratios,
    Discriminant Analysis and the Prediction of Corporate Bankruptcy,"
    The Journal of Finance 23(4): 589-609), applied as a cross-
    sectional stock-selection signal rather than its original
    bankruptcy-classification purpose: Dichev (1998, "Is the Risk of
    Bankruptcy a Systematic Risk?," The Journal of Finance 53(3):
    1131-1147) and Campbell, Hilscher & Szilagyi (2008, "In Search of
    Distress Risk," The Journal of Finance 63(6): 2899-2939) both found
    financially DISTRESSED firms earn systematically LOWER, not higher,
    subsequent returns -- the "distress risk anomaly," a genuine puzzle
    since standard risk-return theory predicts riskier firms should
    earn MORE, not less. Companies with a HIGHER Z-score (financially
    healthier, lower bankruptcy risk) are hypothesized to have
    relatively better forward returns, matching the same "safety
    premium" intuition as `low_volatility_score`/`low_beta_score`/
    `leverage_score` but via a specific, historically famous five-ratio
    discriminant formula -- arguably the single most widely used
    financial-distress formula in both academia and practice, in
    continuous use since 1968 -- not a rank-average composite or a
    single ratio, so genuinely different construction from every other
    quality-family factor already in this module, not a relabeling of
    one.

    Z = 1.2*X1 + 1.4*X2 + 3.3*X3 + 0.6*X4 + 1.0*X5, the ORIGINAL
    (public-manufacturer) formula: X1 = (AssetsCurrent -
    LiabilitiesCurrent)/Assets (working capital/assets), X2 =
    RetainedEarningsAccumulatedDeficit/Assets, X3 = EBIT/Assets, X4 =
    market value of equity/Liabilities, X5 = Revenues/Assets. EBIT is
    proxied by the standard us-gaap `OperatingIncomeLoss` concept
    (income before interest and taxes) -- a common, explicitly-flagged
    simplification rather than reconstructing EBIT from `NetIncomeLoss`
    plus separately-tagged interest and tax add-backs, which are
    inconsistently tagged across filers and would introduce more
    missing-data cases than the single, well-standardized
    `OperatingIncomeLoss` tag. Market value of equity computed
    identically to every other market-cap-based score in this module
    (`_latest_price` raw-close discipline). Needs 2 new real ingestion
    concepts beyond what earlier scores use:
    `RetainedEarningsAccumulatedDeficit`, `OperatingIncomeLoss` -- both
    cheap (SEC EDGAR returns a company's entire company-facts JSON per
    request regardless of which concepts are requested, so extending
    `_DEFAULT_CONCEPTS` costs zero additional real requests, the same
    reasoning already established for every earlier concept
    addition)."""
    assets_record = _latest_fiscal_year_value(fundamentals_repository, security_id, "Assets", as_of_time)
    if assets_record is None or assets_record.value <= 0:
        return None
    current_assets_record = _latest_fiscal_year_value(
        fundamentals_repository, security_id, "AssetsCurrent", as_of_time,
    )
    current_liabilities_record = _latest_fiscal_year_value(
        fundamentals_repository, security_id, "LiabilitiesCurrent", as_of_time,
    )
    retained_earnings_record = _latest_fiscal_year_value(
        fundamentals_repository, security_id, "RetainedEarningsAccumulatedDeficit", as_of_time,
    )
    ebit_record = _latest_fiscal_year_value(fundamentals_repository, security_id, "OperatingIncomeLoss", as_of_time)
    liabilities_record = _latest_fiscal_year_value(fundamentals_repository, security_id, "Liabilities", as_of_time)
    revenue_record = _latest_fiscal_year_value(fundamentals_repository, security_id, "Revenues", as_of_time)
    if (
        current_assets_record is None or current_liabilities_record is None
        or retained_earnings_record is None or ebit_record is None
        or liabilities_record is None or revenue_record is None
    ):
        return None
    if liabilities_record.value <= 0:
        return None
    shares_record = _latest_fiscal_year_value(
        fundamentals_repository, security_id, "CommonStockSharesOutstanding", as_of_time,
    )
    if shares_record is None or shares_record.value <= 0:
        return None
    price = _latest_price(price_repository, security_id, as_of_time)
    if price is None:
        return None
    market_value_equity = price * shares_record.value
    if market_value_equity <= 0:
        return None
    assets = assets_record.value
    x1 = (current_assets_record.value - current_liabilities_record.value) / assets
    x2 = retained_earnings_record.value / assets
    x3 = ebit_record.value / assets
    x4 = market_value_equity / liabilities_record.value
    x5 = revenue_record.value / assets
    return 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4 + 1.0 * x5


def _quality_component_values(
    security_ids: Sequence[str], as_of_time: datetime, repository: object,
) -> dict:
    """(profitability, safety, quality) raw values for every security
    that has ALL THREE already-tested building blocks
    (`roe_score`/`leverage_score`/`sloan_accruals_score`) available at
    `as_of_time`. Shared helper for `quality_minus_junk_score`."""
    values = {}
    for sid in security_ids:
        profitability = roe_score(sid, as_of_time, repository)
        safety = leverage_score(sid, as_of_time, repository)
        quality = sloan_accruals_score(sid, as_of_time, repository)
        if profitability is None or safety is None or quality is None:
            continue
        values[sid] = (profitability, safety, quality)
    return values


def quality_minus_junk_score(
    security_ids: Sequence[str], as_of_time: datetime, fundamentals_repository: object, price_repository: object,
) -> dict:
    """HYPOTHESIS -- Quality Minus Junk (Asness, Frazzini & Pedersen
    2013/2019, "Quality Minus Junk," Review of Accounting Studies):
    high-"quality" stocks (safe, profitable, high-quality earnings)
    outperform "junk" stocks -- one of the most widely-cited quality
    factor papers, part of the same broader quality/safety literature
    `leverage_score`/`low_volatility_score` already belong to.

    **The real reason ADR-0043 Decision 8 deferred this as "too
    complex," now understood precisely and unblocked**: the published
    methodology z-scores each of roughly 20 underlying sub-metrics
    across the investable universe at every rebalance date, then
    averages into 3 pillars (Profitability/Growth/Safety) and finally
    into one composite. That cross-sectional step cannot be expressed
    by a per-security `ScoreFn`/`FundamentalsScoreFn`/`HybridScoreFn`
    (each sees exactly one security_id at a time) -- it needs the new
    `signal_ic.compute_universe_ic_series`/`UniverseScoreFn` shape
    (ADR-0043 Decision 12), built specifically to unblock this
    candidate and `value_composite_score` below.

    **A deliberate, documented simplification of the published
    methodology, not the literal ~20-submetric version**: 3 components
    only, one metric each, reusing this project's own already-built and
    already-tested functions rather than new ones -- Profitability
    (`roe_score`), Safety (`leverage_score`, already negated so higher
    is safer), and earnings Quality (`sloan_accruals_score`, already
    negated so higher is lower-accrual/higher-quality). The Growth
    pillar (5-year trailing profitability growth in the original paper)
    is omitted entirely -- this project's fundamentals history is not
    yet deep enough to compute a reliable 5-year trend. Each of the 3
    raw values is rank-averaged (`signal_ic.rank_average`, the same
    tie-robust ranking `spearman_ic` itself already uses) across every
    security that has ALL THREE available at `as_of_time`, then the 3
    per-security ranks are averaged into the final score.
    `price_repository` is accepted but unused -- kept only so this
    function's signature matches `value_composite_score`'s exactly,
    letting `compute_universe_ic_series` call either interchangeably.

    A security missing ANY of the 3 components is excluded from that
    date's entire cross-section (never given a partial score) -- the
    same all-or-nothing discipline `piotroski_f_score` established for
    a per-security composite, extended here to a universe-level one.
    Returns `{}` (never a fabricated ranking) if fewer than 2 securities
    have all 3 components on a given date, matching
    `rank_average`/`spearman_ic`'s own minimum-2-item requirement."""
    component_values = _quality_component_values(security_ids, as_of_time, fundamentals_repository)
    if len(component_values) < 2:
        return {}
    ids = list(component_values)
    profitability_ranks = rank_average([component_values[sid][0] for sid in ids])
    safety_ranks = rank_average([component_values[sid][1] for sid in ids])
    quality_ranks = rank_average([component_values[sid][2] for sid in ids])
    return {
        sid: (profitability_ranks[i] + safety_ranks[i] + quality_ranks[i]) / 3.0
        for i, sid in enumerate(ids)
    }


def _value_component_values(
    security_ids: Sequence[str], as_of_time: datetime, fundamentals_repository: object, price_repository: object,
) -> dict:
    """5-tuple of raw value-leg scores for every security that has ALL
    FIVE available at `as_of_time`. Shared helper for
    `value_composite_score`."""
    values = {}
    for sid in security_ids:
        e_yield = earnings_yield_score(sid, as_of_time, fundamentals_repository, price_repository)
        b_to_m = book_to_market_score(sid, as_of_time, fundamentals_repository, price_repository)
        s_yield = sales_yield_score(sid, as_of_time, fundamentals_repository, price_repository)
        cf_yield = cashflow_yield_score(sid, as_of_time, fundamentals_repository, price_repository)
        sh_yield = shareholder_yield_score(sid, as_of_time, fundamentals_repository, price_repository)
        if any(v is None for v in (e_yield, b_to_m, s_yield, cf_yield, sh_yield)):
            continue
        values[sid] = (e_yield, b_to_m, s_yield, cf_yield, sh_yield)
    return values


def value_composite_score(
    security_ids: Sequence[str], as_of_time: datetime, fundamentals_repository: object, price_repository: object,
) -> dict:
    """HYPOTHESIS -- O'Shaughnessy's "Value Composite" (What Works on
    Wall Street): combining several independent value ratios into one
    composite outperforms any single value ratio alone, since each
    individual ratio (P/E, P/B, P/S, P/CF, EV/EBITDA, shareholder
    yield) can be distorted by a company-specific accounting or
    capital-structure quirk that a multi-metric average washes out.

    **Deliberately 5 of the original 6 legs, and deliberately NOT
    "Trending" (no momentum overlay) -- both limitations stated here
    rather than discovered silently**:
    1. EV/EBITDA needs enterprise value (market cap + total debt -
       cash) and EBITDA (needs depreciation & amortization) -- this
       project has never ingested a cash concept, short-term debt, or
       any D&A concept. A genuine MISSING-DATA blocker, not a
       complexity one, unlike ADR-0043 Decision 8's original "too
       complex" framing for this whole candidate -- 5 of 6 legs turned
       out to be entirely buildable with data already ingested for
       earlier candidates; only this one leg is a real data gap.
    2. The "Trending" momentum overlay is deliberately not rebuilt, for
       the identical reason ADR-0043 Decision 11 gave for not
       rebuilding a fresh momentum leg for "Value+Momentum": this
       project already has a real, observed null IC result for the
       shared momentum score used elsewhere (mean_ic = -0.0078,
       `docs/research/STRATEGY-VALIDATION-REPORT.md` Section G) --
       layering an already-null signal onto this composite would
       confound testing the value composite's own merits cleanly.

    The 5 legs -- `earnings_yield_score`, `book_to_market_score`,
    `sales_yield_score`, `cashflow_yield_score`, `shareholder_yield_score`
    -- are each independently a candidate in their own right, combined
    here via the same cross-sectional rank-averaging
    `quality_minus_junk_score` uses (see that function's own docstring
    for why rank-averaging via `signal_ic.compute_universe_ic_series`
    rather than z-scoring inside an ordinary per-security score_fn).
    All-or-nothing on missing data: a security is excluded from a
    date's entire cross-section if ANY of the 5 legs is `None`. Returns
    `{}` if fewer than 2 securities have all 5."""
    component_values = _value_component_values(security_ids, as_of_time, fundamentals_repository, price_repository)
    if len(component_values) < 2:
        return {}
    ids = list(component_values)
    leg_ranks = [rank_average([component_values[sid][leg] for sid in ids]) for leg in range(5)]
    return {
        sid: sum(leg_ranks[leg][i] for leg in range(5)) / 5.0
        for i, sid in enumerate(ids)
    }


_COMBINED_FACTOR_LEG_COUNT = 9


def _combined_factor_component_values(
    security_ids: Sequence[str], as_of_time: datetime, fundamentals_repository: object, price_repository: object,
) -> dict:
    """9-tuple of raw component scores for every security that has ALL
    NINE available at `as_of_time`. Shared helper for
    `combined_factor_score`.

    The 9 legs are exactly the 9 (of 20 Session 36 raw-IC-screened
    candidates) whose raw IC sign matched the direction their own
    literature predicts (`docs/research/STRATEGY-VALIDATION-REPORT.md`'s
    "Phase 33 Addendum", section B's table) -- `short_term_reversal`,
    `illiquidity`, `piotroski`, `dividend_growth`, `sloan_accruals`,
    `size`, `altman_z`, `shareholder_yield`, `quality_minus_junk`
    (already itself a 3-leg composite). Two of the 9 (`short_term_
    reversal_score`/`illiquidity_score`) are price-only `ScoreFn`s
    (need an `AsOfDataView`, not the raw `price_repository` this
    function receives -- see `signal_ic.compute_ic_series`'s identical
    construction) -- a fresh single-checkpoint `AsOfDataView` is built
    here for exactly that purpose, the same pattern
    `compute_ic_series`/`compute_universe_ic_series` already establish.
    `quality_minus_junk_score` is itself a `UniverseScoreFn` (computes
    every security's score in one call, not per-security) -- called
    once up front rather than inside the per-security loop below."""
    data_view = AsOfDataView(price_repository, BacktestClock(checkpoints=(as_of_time,)))
    quality_minus_junk_by_id = quality_minus_junk_score(security_ids, as_of_time, fundamentals_repository, price_repository)
    values = {}
    for sid in security_ids:
        if sid not in quality_minus_junk_by_id:
            continue
        components = (
            short_term_reversal_score(sid, as_of_time, data_view),
            illiquidity_score(sid, as_of_time, data_view),
            piotroski_f_score(sid, as_of_time, fundamentals_repository),
            dividend_growth_score(sid, as_of_time, fundamentals_repository),
            sloan_accruals_score(sid, as_of_time, fundamentals_repository),
            size_score(sid, as_of_time, fundamentals_repository, price_repository),
            altman_z_score(sid, as_of_time, fundamentals_repository, price_repository),
            shareholder_yield_score(sid, as_of_time, fundamentals_repository, price_repository),
            quality_minus_junk_by_id[sid],
        )
        if any(v is None for v in components):
            continue
        values[sid] = components
    return values


def combined_factor_score(
    security_ids: Sequence[str], as_of_time: datetime, fundamentals_repository: object, price_repository: object,
) -> dict:
    """HYPOTHESIS -- combining several independently-motivated, weak
    signals reduces noise even when none is individually strong enough
    to trade alone (the same nonparametric rank-averaging logic
    `strategy_research.ensemble_strategy.RankAverageEnsembleStrategy`
    already applied to 2 factors, `ADR-0043` Decision 5, extended here
    to 9). Averaging independent noisy signals lowers variance without
    requiring any of them to individually clear a significance bar --
    a genuinely different question from "does any single one of these
    9 factors work alone" (already answered, mostly no, by Session 36's
    real walk-forward results).

    **Which 9, and why, stated precisely (this is the SAME selection
    rule `ADR-0043` Decision 5 already established for
    `RankAverageEnsembleStrategy`'s leverage+net_margin pair, applied
    consistently at larger scale, not a new practice invented for this
    function)**: every one of the 20 Session 36 raw-IC-screened
    candidates whose raw IC SIGN matched the direction its own
    literature predicts (`STRATEGY-VALIDATION-REPORT.md`'s "Phase 33
    Addendum" section B) -- a binary, symmetric, pre-stated rule
    (direction-agreement only), never a selection by IC MAGNITUDE or
    by which candidate "looked most promising." Combining a
    wrong-signed factor into an average can only dilute a real signal,
    never strengthen it -- the same reasoning `ensemble_strategy.py`'s
    own docstring already gives for excluding null factors from its
    own, smaller combination.

    Construction mirrors `quality_minus_junk_score`/`value_composite_score`
    exactly: each of the 9 raw component scores is cross-sectionally
    rank-averaged independently, then the 9 per-security ranks are
    averaged into one final score. All-or-nothing on missing data, the
    same discipline as `value_composite_score` -- a security missing
    ANY of the 9 (a real possibility: `piotroski_f_score` alone already
    frequently returns `None` for banks/brokers) is excluded from that
    date's entire cross-section rather than scored on a partial subset.
    Returns `{}` if fewer than 2 securities have all 9 (matching
    `rank_average`'s own minimum-2-item requirement)."""
    component_values = _combined_factor_component_values(security_ids, as_of_time, fundamentals_repository, price_repository)
    if len(component_values) < 2:
        return {}
    ids = list(component_values)
    leg_ranks = [
        rank_average([component_values[sid][leg] for sid in ids])
        for leg in range(_COMBINED_FACTOR_LEG_COUNT)
    ]
    return {
        sid: sum(leg_ranks[leg][i] for leg in range(_COMBINED_FACTOR_LEG_COUNT)) / _COMBINED_FACTOR_LEG_COUNT
        for i, sid in enumerate(ids)
    }


def industry_momentum_score(
    security_ids: Sequence[str], as_of_time: datetime, fundamentals_repository: object, price_repository: object,
    *, lookback_days: int = 126,
) -> dict:
    """HYPOTHESIS -- Moskowitz & Grinblatt (1999, "Do Industries
    Explain Momentum?" The Journal of Finance 54(4): 1249-1290): the
    past return of a security's OWN INDUSTRY GROUP (an equal-weighted
    average of every other same-industry security's own trailing
    return) predicts that security's future return, in the SAME
    direction ordinary individual momentum predicts -- the original
    paper's own central finding is that this industry-level component
    explains much of individual-stock momentum's own profitability, and
    that industry momentum survives controls the individual-stock
    version does not. Verified via WebSearch (the paper's own citation
    and finding) rather than reconstructed from memory alone.

    **A genuinely different construct from this module's own
    `long_term_reversal_score`/`short_term_reversal_score`/
    `residual_momentum_score`**: every one of those is an individual
    security's OWN past return (or a residual of it); this factor is
    the AVERAGE past return of every OTHER security sharing the same
    industry -- two securities in the same industry always receive the
    IDENTICAL score here regardless of their own individual returns, so
    this factor can and does disagree with an individual security's own
    momentum on any given date.

    Sector classification comes from `data_infra.universe.get_sector`
    (SEC EDGAR SIC classification text, ADR-0058, real provider-sourced
    data for confirmed symbols only, `None` for any symbol never
    actually resolved this session) -- a security with no confirmed
    sector, or whose sector has fewer than 2 total members among
    `security_ids` with a computable trailing return, is excluded from
    the returned dict entirely (never a fabricated industry group of
    one). Trailing return uses `adjusted_close or close` over
    `lookback_days` (default 126, ~6 months, the same intermediate-
    horizon window `long_term_reversal_score` already uses).

    **A DELIBERATE SIMPLIFICATION of the original paper's own
    construction, flagged the same way `low_beta_score`/
    `idiosyncratic_volatility_score` flag theirs**: the original paper
    value-weights each industry portfolio and excludes the security
    itself from its own industry's average; this implementation
    equal-weights and includes every same-industry security (including
    the one being scored) in its own industry's average -- a minor
    simplification this project's (comparatively small) universe makes
    acceptable, not a look-ahead violation (every included return is
    already fully realized as of `as_of_time`).

    Score is RAW (not negated) -- higher industry momentum is this
    paper's own hypothesized more-attractive direction. `UniverseScoreFn`-
    shaped (`compute_universe_ic_series`), like `quality_minus_junk_score`/
    `value_composite_score`/`combined_factor_score` -- `fundamentals_
    repository` is accepted but unused (this factor is price+sector
    only), matching that shared call shape. Returns `{}` if fewer than 2
    securities end up with a computable score."""
    padded_days = int(lookback_days * 1.6)
    returns_by_id = {}
    for sid in security_ids:
        bars = trim_to_lookback(
            price_repository.get_bars(
                sid, as_of_time - timedelta(days=padded_days), as_of_time, as_of_time=as_of_time,
            ),
            lookback_days,
        )
        if len(bars) < 2:
            continue
        start_close = bars[0].adjusted_close or bars[0].close
        end_close = bars[-1].adjusted_close or bars[-1].close
        if start_close is None or start_close <= 0 or end_close is None:
            continue
        returns_by_id[sid] = end_close / start_close - 1.0

    sector_by_id = {sid: sector for sid in returns_by_id if (sector := get_sector(sid)) is not None}
    members_by_sector: dict = {}
    for sid, sector in sector_by_id.items():
        members_by_sector.setdefault(sector, []).append(sid)

    scores = {}
    for sid, sector in sector_by_id.items():
        members = members_by_sector[sector]
        if len(members) < 2:
            continue
        scores[sid] = sum(returns_by_id[m] for m in members) / len(members)
    return scores if len(scores) >= 2 else {}


def sue_score(security_id: str, as_of_time: datetime, repository: object) -> Optional[float]:
    """HYPOTHESIS -- Standardized Unexpected Earnings (Foster, Olsen &
    Shevlin 1984, "Earnings Releases, Anomalies, and the Behavior of
    Security Returns," The Accounting Review; the resulting
    underreaction is documented as post-earnings-announcement drift by
    Bernard & Thomas 1989, "Post-Earnings-Announcement Drift: Delayed
    Price Response or Risk Premium?," Journal of Accounting Research):
    a company whose most recently reported quarterly earnings surprised
    positively relative to its own seasonal pattern (the same quarter
    one year earlier) tends to keep drifting upward for several months
    afterward, since the market underreacts to the announcement itself
    rather than repricing it all at once. The first genuinely new
    literature category tested in this project since the Session 36
    Phase 33 20-candidate batch (`STRATEGY-VALIDATION-REPORT.md`) --
    every earlier fundamentals factor here is a point-in-time ratio or
    a single year-over-year change, never an earnings-SURPRISE measure.

    SUE = `(EPS_q - EPS_{q-4}) / stdev(the trailing 8 such YoY
    differences)`, i.e. this quarter's year-over-year earnings change,
    standardized by how volatile that change has historically been for
    this specific company -- the original paper's own seasonal-random-
    walk definition of "expected earnings" (no analyst consensus
    estimate needed, unlike an I/B/E/S-consensus-based SUE variant this
    project has no data access to and does not claim to compute).

    Needs `EarningsPerShareDiluted` at QUARTERLY granularity
    (`_quarterly_records`, not `_fy_records` -- the first score in this
    module needing quarter-level rather than fiscal-year-level data).
    `None` (never a fabricated score, never a fabricated "expected
    earnings") if fewer than 12 quarters are known yet (8 trailing YoY
    diffs each need the value 4 quarters earlier, so the 8th diff needs
    history back to 12 quarters ago), or the trailing 8 diffs have zero
    variance (undefined z-score -- e.g. a company with perfectly flat
    YoY earnings for 2 straight years)."""
    records = _quarterly_records(repository, security_id, "EarningsPerShareDiluted", as_of_time)
    if len(records) < 12:
        return None
    values = [record.value for record in records]
    yoy_diffs = [values[i] - values[i - 4] for i in range(4, len(values))]
    trailing = yoy_diffs[-8:]
    if len(trailing) < 8:
        return None
    mean = sum(trailing) / len(trailing)
    variance = sum((diff - mean) ** 2 for diff in trailing) / (len(trailing) - 1)
    stdev = variance ** 0.5
    if stdev == 0:
        return None
    return trailing[-1] / stdev


_INSIDER_BUYING_LOOKBACK_MONTHS = 6


def insider_buying_score(security_id: str, as_of_time: datetime, repository: object) -> Optional[float]:
    """HYPOTHESIS -- (Lakonishok & Lee 2001, "Are Insider Trades
    Informative?," Review of Financial Studies; Seyhun 1986, "Insiders'
    profits, costs of trading, and market efficiency," Journal of
    Financial Economics): insiders (officers, directors, 10%+ owners)
    sometimes trade on private information about their own company's
    prospects, so a period of net insider BUYING on the open market --
    genuinely discretionary purchases, never option exercises, stock
    grants, or pre-scheduled Rule 10b5-1 transactions -- predicts higher
    subsequent returns than a period of net insider selling. This is the
    second data pipeline built this session (ADR-0086), after the SUE
    factor (ADR-0084): the project's first factor sourced from SEC
    Form 4 insider-transaction filings rather than XBRL fundamentals or
    price/volume history.

    **Why only transaction codes "P"/"S" and only `is_10b5_1_plan ==
    False`, decided BEFORE any real result was seen (RULE 0.8)**: this
    project's own real, directly-observed Form 4 sample this session
    (AAPL, accession 0001140361-26-035636) turned out to be a Rule
    10b5-1 pre-scheduled sale, not a genuinely discretionary trade --
    the literature basis above is specifically about discretionary
    trading conveying private information, which a pre-scheduled plan
    transaction structurally cannot (the trade was decided months
    earlier, unrelated to whatever the insider knows today). Every
    other transaction code (`A` grants, `M` option exercises, ...) is
    excluded for the same underlying reason: those are compensation
    mechanics an insider does not choose based on a view on future
    stock performance, not a discretionary market trade.

    NET_PURCHASE_RATIO = `(buy_shares - sell_shares) / (buy_shares +
    sell_shares)`, computed over the trailing
    `_INSIDER_BUYING_LOOKBACK_MONTHS` (6) calendar months of
    `transaction_date` -- a share-count-weighted ratio in `[-1, 1]`,
    following Lakonishok & Lee (2001)'s own preference for a ratio over
    a raw transaction count (an insider who buys 10x as much dollar
    value in one purchase should weigh more than ten insiders each
    buying 1 share). 6 months is this project's own fixed choice, not
    copied from one paper's exact window -- both Lakonishok & Lee and
    Seyhun examine multi-month insider-trading windows with varying
    specifications (3/6/12-month cuts appear across the literature); 6
    months is a mid-range, commonly used compromise, fixed here before
    any IC result exists, per RULE 0.8.

    `None` (never a fabricated ratio) if no qualifying (Code P or S,
    non-10b5-1) transaction exists in the trailing window at all -- "no
    insider trading activity observed" is a genuinely different,
    non-fabricatable state from "insiders are exactly balanced," which
    itself legitimately returns `0.0`."""
    window_start = add_months(as_of_time, -_INSIDER_BUYING_LOOKBACK_MONTHS)
    transactions = repository.get_insider_transactions(security_id, as_of_time, start=window_start, end=as_of_time)
    buy_shares = sum(t.shares for t in transactions if t.transaction_code == "P" and not t.is_10b5_1_plan)
    sell_shares = sum(t.shares for t in transactions if t.transaction_code == "S" and not t.is_10b5_1_plan)
    total = buy_shares + sell_shares
    if total == 0:
        return None
    return (buy_shares - sell_shares) / total


_RS_RATING_LOOKBACK_DAYS = 252


def rs_rating_score(security_id: str, as_of_time: datetime, data: AsOfDataView) -> Optional[float]:
    """HYPOTHESIS -- O'Neil/IBD Relative Strength Rating (William
    O'Neil, "How to Make Money in Stocks," CANSLIM methodology): a
    security's own trailing price performance, weighted toward its most
    recent quarter, predicts continued relative outperformance --
    momentum specifically constructed to emphasize recent strength over
    older strength, distinct from `long_term_reversal_score`'s
    equal-weighted `_momentum_score`. Found while auditing an external
    project (dragon1086/prism-insight, session comparison request) whose
    own `cores/rs_rating.py` independently implements the same
    published O'Neil formula -- the hypothesis and formula are IBD's,
    not that project's; this project's own implementation is built
    fresh against the public methodology, not copied.

    SCORE = `2*R63 + R126 + R189 + R252`, where `Rn = (latest_close -
    close_n_days_ago) / close_n_days_ago` -- four trailing returns over
    the last 1/2/3/4 quarters (63 trading days each), the most recent
    quarter weighted 2x, exactly IBD's own published construction.

    **Deliberately returns this raw weighted-return score, never IBD's
    own 1-99 cross-sectional percentile transform**, decided before any
    real result exists (RULE 0.8): `signal_ic.compute_ic_series`'s
    Spearman rank correlation and simple top-N portfolio sorting are
    BOTH invariant to any monotonic (rank-preserving) transformation of
    a score, so percentile-ranking changes nothing this project can
    measure -- it is IBD's own human-readability presentation choice,
    not new information. Adding it would also require restructuring
    this into a cross-sectional `UniverseScoreFn` (like
    `quality_minus_junk_score`), a real complexity cost for zero
    measurable benefit to either raw-IC screening or portfolio
    construction, so it is not done.

    Needs 252 trading days (~1 calendar year) of price history for all
    four component returns; returns `None` (never a fabricated score)
    for a name with less history, or if any of the four base prices is
    non-positive."""
    bars = trim_to_lookback(
        data.get_bars(security_id, as_of_time - timedelta(days=int(_RS_RATING_LOOKBACK_DAYS * 1.6)), as_of_time),
        _RS_RATING_LOOKBACK_DAYS,
    )
    if len(bars) < _RS_RATING_LOOKBACK_DAYS + 1:
        return None
    closes = [b.adjusted_close or b.close for b in bars]
    latest = closes[-1]

    def _trailing_return(n: int) -> Optional[float]:
        base = closes[-1 - n]
        if base <= 0:
            return None
        return (latest - base) / base

    r63, r126, r189, r252 = (_trailing_return(n) for n in (63, 126, 189, 252))
    if r63 is None or r126 is None or r189 is None or r252 is None:
        return None
    return 2.0 * r63 + r126 + r189 + r252


_RESIDUAL_MOMENTUM_ESTIMATION_DAYS = 252
_RESIDUAL_MOMENTUM_FORMATION_DAYS = 63
_RESIDUAL_MOMENTUM_MIN_ESTIMATION_OBSERVATIONS = 200
_RESIDUAL_MOMENTUM_MIN_FORMATION_OBSERVATIONS = 40


def residual_momentum_score(
    security_id: str, as_of_time: datetime, data: AsOfDataView,
    *, estimation_days: int = _RESIDUAL_MOMENTUM_ESTIMATION_DAYS, formation_days: int = _RESIDUAL_MOMENTUM_FORMATION_DAYS,
) -> Optional[float]:
    """HYPOTHESIS -- Residual Momentum (Blitz, Huij & Martens 2011,
    "Residual Momentum," Journal of Financial Economics 108(3): 506-521):
    momentum computed on a security's CAPM-RESIDUAL returns (the part of
    its return left over after removing co-movement with the market)
    outperforms and is more stable than momentum computed on raw total
    returns, because a large share of raw momentum's own well-documented
    "crash risk" comes from systematic (market-beta-driven) reversals
    rather than genuine stock-specific continuation. Found during the
    same GitHub/web search (Session 36 continued, `paperswithbacktest/
    awesome-systematic-trading`) that also surfaced `rd_expenditure_score`
    below -- both chosen and their construction fixed BEFORE seeing any
    result (RULE 0.8).

    **A genuinely different construct from every momentum-adjacent factor
    already in this module, not a re-parameterization of one**:
    `long_term_reversal_score`/this project's own `_momentum_score`
    (`long_term_momentum.py`) compute cumulative RAW price return, no
    market adjustment at all. `idiosyncratic_volatility_score` regresses
    out the market the same way this factor does, but keeps only the
    STANDARD DEVIATION of the residuals (a pure risk measure, sign and
    mean discarded); this factor keeps the residuals' own MEAN
    (standardized by their volatility), discarding nothing about their
    direction -- the two scores can and do disagree on which securities
    they favor, since a stock can have a strongly positive residual
    momentum while also being unusually volatile, or vice versa.

    **A real estimator subtlety, caught by reasoning about the math
    before any test was run against it (still RULE 0.8 -- this is not an
    empirical peek, it is a correctness fact about OLS itself)**: fitting
    alpha/beta by OLS on a sample and then computing residuals on THAT
    SAME sample always yields a residual MEAN of exactly zero, by
    construction (an intercept-including OLS regression's own residuals
    always sum to zero over its own estimation sample) -- so a first
    draft of this factor that estimated beta/alpha and computed
    "momentum" residuals over one identical window would have produced a
    score of ~0 for every security, always, regardless of any real
    signal. The literature's own answer (and this implementation's) is
    an OUT-OF-SAMPLE split: alpha/beta are estimated over an EARLIER,
    non-overlapping `estimation_days` window (default 252, ~12 months),
    then applied to compute residuals over the immediately FOLLOWING
    `formation_days` window (default 63, ~1 quarter -- the same "R63"
    unit `rs_rating_score` already uses, chosen for consistency with
    this module's existing vocabulary rather than the original paper's
    own 11-month formation window, which needs more paired history per
    security than this project's universe reliably offers). Score =
    `mean(formation-window residuals) / std(formation-window residuals)`,
    a t-statistic-like standardized average out-of-sample residual return
    -- this standardization-by-own-volatility step is the paper's own
    core mechanism for reducing momentum crash risk, not a cosmetic
    normalization, and is only meaningful here because the residuals it
    is computed over are genuinely out-of-sample.

    Needs at least `_RESIDUAL_MOMENTUM_MIN_ESTIMATION_OBSERVATIONS` (200
    of the nominal 252 estimation-window returns) and
    `_RESIDUAL_MOMENTUM_MIN_FORMATION_OBSERVATIONS` (40 of the nominal 63
    formation-window returns) of paired security/benchmark daily returns,
    both floors below their nominal window sizes to tolerate real data
    gaps (matching this module's existing practice), with non-zero
    benchmark return variance in the estimation window and non-zero
    residual volatility in the formation window; `None` (never a
    fabricated score) below any of those."""
    total_days = estimation_days + formation_days
    padded_days = int(total_days * 1.6)
    security_bars = trim_to_lookback(
        data.get_bars(security_id, as_of_time - timedelta(days=padded_days), as_of_time), total_days,
    )
    benchmark_bars = trim_to_lookback(
        data.get_bars(BENCHMARK_SYMBOL, as_of_time - timedelta(days=padded_days), as_of_time), total_days,
    )
    if len(security_bars) < 2 or len(benchmark_bars) < 2:
        return None
    security_closes = {b.timestamp.date(): (b.adjusted_close or b.close) for b in security_bars}
    benchmark_closes = {b.timestamp.date(): (b.adjusted_close or b.close) for b in benchmark_bars}
    common_dates = sorted(set(security_closes) & set(benchmark_closes))
    if len(common_dates) < 2:
        return None
    all_security_returns = compute_returns([security_closes[d] for d in common_dates])
    all_benchmark_returns = compute_returns([benchmark_closes[d] for d in common_dates])
    n = len(all_security_returns)
    if n != len(all_benchmark_returns) or n < _RESIDUAL_MOMENTUM_MIN_ESTIMATION_OBSERVATIONS + _RESIDUAL_MOMENTUM_MIN_FORMATION_OBSERVATIONS:
        return None

    # Non-overlapping, chronologically EARLIER estimation slice and
    # LATER formation slice -- the formation slice always ends at the
    # most recent paired return (closest to as_of_time).
    formation_count = min(formation_days, n - _RESIDUAL_MOMENTUM_MIN_ESTIMATION_OBSERVATIONS)
    estimation_security = all_security_returns[:-formation_count]
    estimation_benchmark = all_benchmark_returns[:-formation_count]
    formation_security = all_security_returns[-formation_count:]
    formation_benchmark = all_benchmark_returns[-formation_count:]
    if len(estimation_security) < _RESIDUAL_MOMENTUM_MIN_ESTIMATION_OBSERVATIONS or len(formation_security) < _RESIDUAL_MOMENTUM_MIN_FORMATION_OBSERVATIONS:
        return None

    estimation_security_mean = sum(estimation_security) / len(estimation_security)
    estimation_benchmark_mean = sum(estimation_benchmark) / len(estimation_benchmark)
    covariance = sum(
        (s - estimation_security_mean) * (b - estimation_benchmark_mean)
        for s, b in zip(estimation_security, estimation_benchmark)
    ) / (len(estimation_security) - 1)
    benchmark_variance = sum(
        (b - estimation_benchmark_mean) ** 2 for b in estimation_benchmark
    ) / (len(estimation_benchmark) - 1)
    if benchmark_variance == 0:
        return None
    beta = covariance / benchmark_variance
    alpha = estimation_security_mean - beta * estimation_benchmark_mean

    formation_residuals = [s - alpha - beta * b for s, b in zip(formation_security, formation_benchmark)]
    residual_mean = sum(formation_residuals) / len(formation_residuals)
    residual_variance = sum((r - residual_mean) ** 2 for r in formation_residuals) / (len(formation_residuals) - 1)
    residual_std = residual_variance ** 0.5
    if residual_std == 0:
        return None
    return residual_mean / residual_std


def rd_expenditure_score(
    security_id: str, as_of_time: datetime, fundamentals_repository: object, price_repository: object,
) -> Optional[float]:
    """HYPOTHESIS -- the R&D expenditure anomaly (Chan, Lakonishok &
    Sougiannis 2001, "The Stock Market Valuation of Research and
    Development Expenditures," The Journal of Finance 56(6): 2431-2456):
    firms with HIGHER research & development spending relative to market
    value earn higher subsequent returns, hypothesized because US GAAP
    requires R&D to be EXPENSED immediately (never capitalized as an
    asset, unlike physical capital investment), which understates the
    book value and near-term earnings of R&D-intensive firms relative to
    the future growth that spending is actually building -- the market
    is hypothesized to underappreciate this in the same expensed-not-
    capitalized sense `sloan_accruals_score`'s own accrual/cash-flow
    distinction concerns a different accounting choice. Found via the
    same GitHub/web search (Session 36 continued,
    `paperswithbacktest/awesome-systematic-trading`) that also surfaced
    `residual_momentum_score` above.

    Score = `ResearchAndDevelopmentExpense / market_cap` ("R&D-to-market",
    the standard scaling used across the later factor-zoo replication
    literature for this anomaly, e.g. Green, Hand & Zhang 2017's own
    "rd_mve" -- a documented alternative to Chan, Lakonishok & Sougiannis'
    own R&D-CAPITAL/market-value construction, which amortizes multiple
    years of past R&D spending into a stock rather than using the single
    latest fiscal year's flow. A single-year flow is used here for the
    identical reason `shareholder_yield_score`'s numerator uses single
    -year flows rather than amortized stocks: no new infrastructure is
    needed beyond what this module's other market-cap-scaled ratios
    already build). Same market-cap denominator construction as
    `sales_yield_score`/`book_to_market_score` (`_latest_price`, raw
    `close`, times latest fiscal-year-end `CommonStockSharesOutstanding`).

    **The numerator reads a genuinely absent `ResearchAndDevelopmentExpense`
    tag as `0.0`, not `None`, via `_fy_flow_or_zero`** -- the identical
    reasoning that helper's own docstring already gives for
    `shareholder_yield_score`'s dividend/buyback/issuance concepts: a
    company that did no R&D in a given fiscal year (true for many
    non-technology large-caps in this project's universe -- retailers,
    banks, utilities) does not file a `ResearchAndDevelopmentExpense`
    tag worth `$0`, it simply omits it, and reading that omission as "no
    R&D was spent" is the financially correct interpretation, not a
    fabrication. This means a genuine zero-R&D company gets a real score
    of exactly `0.0` here (the lowest possible under this module's
    higher-is-better convention), never a missing-data `None` -- an
    intended, not accidental, consequence of the hypothesis itself
    (zero R&D spending should rank least attractive under this factor).

    **Needs one new XBRL concept beyond what any existing factor in this
    module ingests**: `ResearchAndDevelopmentExpense`, added to
    `ingest_fundamentals_data.py`'s `_DEFAULT_CONCEPTS` -- the identical
    "zero additional real network requests" pattern `EarningsPerShareDiluted`
    already established for `sue_score` (ADR-0084): concepts are parsed
    from a company's existing SEC EDGAR `companyfacts` JSON response
    already being fetched for every other concept, not a separate request
    per concept. `None` (never a fabricated ratio) only when the share
    count or price is unknown, or market cap is non-positive -- the same
    missing-data guards `sales_yield_score`/`book_to_market_score`
    already apply."""
    shares_record = _latest_fiscal_year_value(
        fundamentals_repository, security_id, "CommonStockSharesOutstanding", as_of_time,
    )
    if shares_record is None or shares_record.value <= 0:
        return None
    price = _latest_price(price_repository, security_id, as_of_time)
    if price is None:
        return None
    market_cap = price * shares_record.value
    if market_cap <= 0:
        return None
    rd_expense = _fy_flow_or_zero(fundamentals_repository, security_id, "ResearchAndDevelopmentExpense", as_of_time)
    return rd_expense / market_cap


_RETURN_SEASONALITY_LOOKBACK_YEARS = 5
_RETURN_SEASONALITY_MIN_YEARS = 2


def return_seasonality_score(
    security_id: str, as_of_time: datetime, data: AsOfDataView,
    *, lookback_years: int = _RETURN_SEASONALITY_LOOKBACK_YEARS, min_years: int = _RETURN_SEASONALITY_MIN_YEARS,
) -> Optional[float]:
    """HYPOTHESIS -- Return Seasonality (Heston & Sadka 2008, "Seasonality
    in the Cross-Section of Stock Returns," Journal of Financial
    Economics 87(2): 418-445): a security's own historical tendency to
    over- or under-perform in a given CALENDAR MONTH, across multiple
    prior years, predicts its performance in that SAME calendar month
    going forward -- e.g. a stock that has historically done well every
    March tends to do relatively well again this March. Found via the
    same GitHub/web search that also surfaced `residual_momentum_score`/
    `rd_expenditure_score` (ADR-0098) -- `paperswithbacktest/awesome-
    systematic-trading`'s own `12-month-cycle-in-cross-section-of-stocks-
    returns.py` independently confirmed this as a real, separately
    replicated effect (that file's own "return exactly 12 months ago
    predicts this month" construction is the k=1 special case of the
    more general same-calendar-month averaging built here).

    **A genuinely different COMPUTATIONAL SHAPE from every other factor
    in this module, not a re-parameterization of one**: every other
    price-only factor here reads one CONTIGUOUS trailing window of
    trading days. This factor instead groups a security's own price
    history by CALENDAR MONTH across multiple, non-contiguous prior
    years and averages only the months sharing `as_of_time`'s own month
    number -- e.g. computed in March 2023, it looks at March 2022, March
    2021, ..., ignoring every other month in between. No other factor in
    this module has this shape.

    **Construction**: for each of the trailing `lookback_years` (default
    5 -- a documented simplification of Heston & Sadka's own much longer
    sample, chosen since this project's own real universe has far less
    trailing history available than their multi-decade sample, the same
    "adapt the academic window to what this project's data can actually
    support" reasoning `residual_momentum_score`'s own `formation_days`
    default already uses), find the calendar month with the SAME month
    number as `as_of_time`, `k` years back, and compute that historical
    month's own total return as `close_at_end_of_that_month /
    close_at_end_of_the_PRECEDING_month - 1` (the standard "monthly
    return" definition, anchored to month-END closes so a month with a
    partial trading-day gap at either end does not distort the ratio).
    Score = the simple average of however many of those `lookback_years`
    historical same-month returns are actually available (never
    fabricated for a missing year -- a year with no data for either the
    target month or its preceding month is skipped entirely, not
    treated as a zero return).

    Needs at least `min_years` (default 2) valid historical same-month
    observations; `None` (never a fabricated score) below that -- a
    materially higher floor, proportionally, than this module's
    contiguous-window factors, since a same-calendar-month average from
    only 1 prior year is barely more informative than that single
    month's own raw return, not yet a genuine "seasonality" signal."""
    padded_days = lookback_years * 366 + 40
    bars = data.get_bars(security_id, as_of_time - timedelta(days=padded_days), as_of_time)
    if not bars:
        return None
    closes_by_month: dict[tuple[int, int], list[tuple[date, float]]] = {}
    for bar in bars:
        bar_date = bar.timestamp.date()
        key = (bar_date.year, bar_date.month)
        closes_by_month.setdefault(key, []).append((bar_date, bar.adjusted_close or bar.close))
    for entries in closes_by_month.values():
        entries.sort(key=lambda pair: pair[0])

    target_month = as_of_time.month
    historical_returns: list[float] = []
    for years_back in range(1, lookback_years + 1):
        target_year = as_of_time.year - years_back
        preceding_month, preceding_year = (target_month - 1, target_year) if target_month > 1 else (12, target_year - 1)
        target_entries = closes_by_month.get((target_year, target_month))
        preceding_entries = closes_by_month.get((preceding_year, preceding_month))
        if not target_entries or not preceding_entries:
            continue
        baseline_price = preceding_entries[-1][1]
        end_price = target_entries[-1][1]
        if baseline_price is None or baseline_price <= 0 or end_price is None:
            continue
        historical_returns.append(end_price / baseline_price - 1.0)

    if len(historical_returns) < min_years:
        return None
    return sum(historical_returns) / len(historical_returns)


def short_interest_score(security_id: str, as_of_time: datetime, repository: object) -> Optional[float]:
    """HYPOTHESIS -- the Short Interest Anomaly (Asquith, Pathak & Ritter
    2005, "Short Interest, Institutional Ownership, and Stock Returns,"
    Journal of Financial Economics 78(2): 243-276; Boehmer, Jones &
    Zhang 2008, "Which Shorts Are Informed?," The Journal of Finance):
    heavily shorted stocks earn systematically LOWER subsequent returns,
    hypothesized because short sellers are, on average, more informed
    than the typical market participant -- a large or growing short
    position reflects a real, aggregated negative view worth taking
    seriously as a signal, not noise. Flagged as the lowest-priority of
    the four GitHub/web-search-derived candidates (ADR-0098's own
    STRATEGY-VALIDATION-REPORT addendum) specifically because it was the
    only one needing a genuinely NEW data source -- built now (ADR-0099)
    following the user's explicit "proceed with the candidates" ("후보들
    진행") instruction covering all remaining ones, not because the data
    -feasibility concern was resolved by seeing any result.

    **Data source, and the one real, stated limitation new to this
    factor**: `repository` is a `storage.short_interest_repository.
    DuckDBShortInterestRepository`, populated by `scripts.ingest_short_
    interest_data` from a LOCAL FILE the user produces from FINRA Rule
    4560 reporting -- not a live network fetch this project's own
    provider layer performs (see `data_infra.short_interest_models`'s
    own module docstring for why: this sandboxed session cannot reach
    `finra.org` to verify FINRA's real bulk-file format, the identical
    limitation `data_infra.providers.file_import.LocalFileDataProvider`
    already states for real market-data acquisition). `available_time`
    on every record is deliberately later than its own `settlement_date`
    by a conservative fixed lag (FINRA's own published "7 business days"
    public-dissemination schedule, rounded up to an 11-calendar-day
    upper bound) -- never the settlement date itself, the same
    look-ahead discipline `InsiderTransaction.available_time` already
    applies to Form 4 filing dates.

    **Construction, a deliberate engineering simplification chosen
    BEFORE any result exists (RULE 0.8)**: score is the NEGATIVE of the
    most recent available `days_to_cover` (short interest quantity
    divided by average daily trading volume, FINRA's own published
    field, not recomputed here) rather than short interest scaled by
    shares outstanding (Asquith, Pathak & Ritter's own primary
    construction) -- `days_to_cover` needs only this one dedicated
    repository (mirrors `insider_buying_score`'s own single-repository
    shape, reused through `compute_fundamentals_ic_series`'s
    `fundamentals_repository` slot exactly the way that factor's own
    docstring already describes), while a shares-outstanding-scaled
    ratio would need a SECOND repository (fundamentals, for
    `CommonStockSharesOutstanding`) and a new two-repository CLI wiring
    shape this module does not otherwise need. `None` (never a
    fabricated score) if no report exists yet with `available_time <=
    as_of_time`, or if that latest report's own `days_to_cover` is
    `None` (FINRA does not always publish it, e.g. for a name with zero
    recorded average daily volume that reporting period)."""
    latest = repository.get_latest_short_interest(security_id, as_of_time)
    if latest is None or latest.days_to_cover is None:
        return None
    return -latest.days_to_cover


def net_stock_issuance_score(security_id: str, as_of_time: datetime, repository: object) -> Optional[float]:
    """HYPOTHESIS -- the Net Stock Issuance anomaly (Pontiff & Woodgate
    2008, "Share Issuance and Cross-Sectional Returns," The Journal of
    Finance 63(2): 921-945; Fama & French 2008, "Dissecting Anomalies,"
    The Journal of Finance 63(4): 1653-1678): companies that issue new
    shares (diluting existing holders) earn systematically LOWER
    subsequent returns than companies that reduce shares outstanding
    (via buybacks), and this predictive power was found to be even
    stronger than size, book-to-market, or momentum individually in the
    post-1970 US sample. Found via a further GitHub/web search for
    borrowable strategies, continuing the same search thread as
    ADR-0098/ADR-0099, specifically triggered by the user's "다른 프로젝트
    더 찾아봐" follow-up: `bkelly-lab/ReplicationCrisis` (Jensen, Kelly &
    Pedersen 2023, Journal of Finance -- the single highest-quality
    academic source found this session) surfaces "net issuance"/"debt
    issuance" as one of its 13 factor themes, but its own exact
    construction lives in SAS scripts and a binary spreadsheet this
    session's blocked network access to `nber.org`/`jkpfactors.com`
    could not verify -- rather than guess THAT repository's exact
    formula, this factor is built instead from the original, independently
    well-documented Pontiff & Woodgate/Fama & French construction, which
    multiple accessible sources converge on identically.

    Per Fama & French (2008a)'s own definition (the standard operational
    form used across this literature): NET STOCK ISSUANCE = the change
    in LOG split-adjusted shares outstanding across the two most recent
    fiscal years, using `CommonStockSharesOutstanding` -- a concept
    already ingested for `shareholder_yield_score`/`book_to_market_score`
    (ADR-0043 Decision 10/12), needing ZERO new data. Structurally the
    same "single year-over-year change" shape `asset_growth_score`/
    `dividend_growth_score` already use, applied to a different concept.

    Score is the NEGATIVE of `ln(current FY shares / prior FY shares)`,
    so a security that REDUCED its share count (net buybacks exceeding
    any issuance) scores higher (more attractive) -- matches this
    module's convention. `None` (never a fabricated value) unless at
    least two distinct fiscal years' `CommonStockSharesOutstanding` are
    both already known as of `as_of_time`, or either value is
    non-positive."""
    records = _fy_records(repository, security_id, "CommonStockSharesOutstanding", as_of_time)
    if len(records) < 2:
        return None
    current, prior = records[-1], records[-2]
    if prior.value <= 0 or current.value <= 0:
        return None
    net_issuance = math.log(current.value / prior.value)
    return -net_issuance


def asset_turnover_change_score(security_id: str, as_of_time: datetime, repository: object) -> Optional[float]:
    """HYPOTHESIS -- Fairfield & Yohn (2001, "Using Asset Turnover and
    Profit Margin to Forecast Changes in Profitability," Review of
    Accounting Studies 6: 371-385) / Soliman (2008, "The Use of DuPont
    Analysis by Market Participants," The Accounting Review 83(3):
    823-853): a YEAR-OVER-YEAR INCREASE in asset turnover (Sales /
    Assets, the DuPont decomposition's efficiency leg) predicts
    subsequently HIGHER profitability, and Soliman finds the market only
    partially prices this in, leaving predictable subsequent abnormal
    stock returns in the same direction -- a fundamental-momentum /
    under-reaction story structurally similar to this module's own
    `sue_score` (Foster, Olsen & Shevlin 1984) and `sloan_accruals_score`
    (Sloan 1996), applied to a different DuPont-derived signal. Verified
    via WebSearch (both papers' own citations and the direction of the
    change-in-turnover-to-profitability relationship) rather than
    reconstructed from memory alone.

    Asset turnover for one fiscal year is `Revenues / Assets` -- both
    concepts already ingested (`Revenues` for `sales_yield_score`/
    `altman_z_score`, `Assets` throughout this module), needing ZERO new
    data. The change (delta-ATO) is `current FY ATO - prior FY ATO`
    (a simple difference, not a log-ratio, matching the literature's own
    "delta-ATO" operational definition for a ratio-of-ratios quantity
    rather than this module's more common log-change shape for a single
    level quantity like `net_stock_issuance_score`'s shares count).
    Requires BOTH concepts to share the identical `period_end` for a
    given fiscal year (never mixing one year's Revenues against a
    different year's Assets), the same period-matching discipline
    `_fy_ratio` already enforces for a single-year ratio.

    Score is the RAW delta-ATO (not negated) -- an INCREASING asset
    turnover is the papers' own hypothesized more-attractive direction.
    `None` (never a fabricated value) unless at least two distinct
    fiscal years have BOTH concepts known, period-matched, with a
    positive `Assets` value in each."""
    revenue_records = _fy_records(repository, security_id, "Revenues", as_of_time)
    asset_records = _fy_records(repository, security_id, "Assets", as_of_time)
    if len(revenue_records) < 2 or len(asset_records) < 2:
        return None
    assets_by_period = {r.period_end: r.value for r in asset_records}
    turnover_by_period = {}
    for r in revenue_records:
        assets_value = assets_by_period.get(r.period_end)
        if assets_value is None or assets_value <= 0:
            continue
        turnover_by_period[r.period_end] = r.value / assets_value
    if len(turnover_by_period) < 2:
        return None
    period_ends = sorted(turnover_by_period)
    prior_ato, current_ato = turnover_by_period[period_ends[-2]], turnover_by_period[period_ends[-1]]
    return current_ato - prior_ato


def net_operating_assets_score(security_id: str, as_of_time: datetime, repository: object) -> Optional[float]:
    """HYPOTHESIS -- the Net Operating Assets anomaly (Hirshleifer, Hou,
    Teoh & Zhang 2004, "Do Investors Overvalue Firms With Bloated
    Balance Sheets?," Journal of Accounting and Economics 38: 297-331):
    firms whose balance sheets have accumulated a large gap between
    operating income and free cash flow -- reflected in a high level of
    NET OPERATING ASSETS relative to total assets -- earn systematically
    LOWER subsequent returns, hypothesized because investors' limited
    attention overweights accounting operating performance relative to
    the (less salient) cash flow it is actually backed by. Found via a
    further GitHub/web search for borrowable strategies -- one of
    `bkelly-lab/ReplicationCrisis`'s 13 factor themes.

    **Construction verified against the account owner's own copy of
    Jensen, Kelly & Pedersen's "Global Factor Data Documentation" PDF**
    (supplied after this factor's first draft, corrected here before any
    real IC result exists for it -- a genuine RULE 0.8-compliant
    correction from better documentation, not empirical tuning): JKP's
    own `noa_at = NOA*_t / AT*_t`, where `NOA* = OA* - OL*`, `OA* = AT* -
    CHE - IVAO` (total assets minus cash minus other investments/
    advances) and `OL* = LT - DLC - DLTT` (total liabilities minus
    short-term debt minus long-term debt) -- both scaled by the SAME
    (contemporaneous, not lagged) fiscal year's Total Assets. This
    project's FIRST DRAFT of this factor (before the documentation was
    available) instead scaled by the PRIOR fiscal year's Assets,
    incorrectly recalling Hirshleifer et al.'s own convention as lagged
    -- fixed here to match the now-verified contemporaneous denominator.

    Substituting `AT* - LT == StockholdersEquity` (the balance-sheet
    identity) into JKP's own `OA* - OL*` expansion gives the
    algebraically equivalent `StockholdersEquity - CHE - IVAO + DLC +
    DLTT`, scaled by the SAME fiscal year's `Assets`. This project
    computes `(StockholdersEquity - Cash + LongTermDebtNoncurrent) /
    Assets` (same fiscal year for all three) -- two documented gaps
    versus JKP's own full construction, decided BEFORE any result exists
    (RULE 0.8): (1) `IVAO` (other investments/advances) is omitted --
    this project has no XBRL concept for it, and it is immaterial for
    most large-cap non-financial names, the same materiality argument
    `piotroski_f_score`/`leverage_score` already make for their own
    balance-sheet simplifications; (2) `DLC` (short-term interest-bearing
    debt) is omitted for the identical reason -- `leverage_score` already
    simplifies its own debt figure the same way, using total `Liabilities`
    rather than a full debt breakdown.

    **Needs one new XBRL concept beyond what any existing factor in this
    module ingests**: `CashAndCashEquivalentsAtCarryingValue`, added to
    `ingest_fundamentals_data.py`'s `_DEFAULT_CONCEPTS` -- the same
    "zero additional real network requests" pattern every prior concept
    addition here already established.

    Score is the NEGATIVE of the NOA ratio, so a LOWER (hypothesized
    more attractive) net-operating-assets level produces a HIGHER
    score, matching this module's convention. `None` (never a
    fabricated ratio) unless `StockholdersEquity`, `CashAndCashEquivalents
    AtCarryingValue`, and `Assets` are all known, or `Assets` is
    non-positive. `LongTermDebtNoncurrent` reads as `0.0` (never `None`)
    when absent -- the same `_fy_flow_or_zero`-style reasoning already
    applied to `shareholder_yield_score`'s own concepts: a company with
    no long-term debt tag simply has none, a real `$0`, not a data gap."""
    equity_record = _latest_fiscal_year_value(repository, security_id, "StockholdersEquity", as_of_time)
    cash_record = _latest_fiscal_year_value(repository, security_id, "CashAndCashEquivalentsAtCarryingValue", as_of_time)
    assets_record = _latest_fiscal_year_value(repository, security_id, "Assets", as_of_time)
    if equity_record is None or cash_record is None or assets_record is None:
        return None
    if assets_record.value <= 0:
        return None
    long_term_debt = _fy_flow_or_zero(repository, security_id, "LongTermDebtNoncurrent", as_of_time)
    noa = (equity_record.value - cash_record.value + long_term_debt) / assets_record.value
    return -noa


def operating_leverage_score(security_id: str, as_of_time: datetime, repository: object) -> Optional[float]:
    """HYPOTHESIS -- Novy-Marx (2011)'s Operating Leverage anomaly
    ("Operating Leverage," Review of Finance 15(1): 103-134): firms with
    HIGHER fixed-cost intensity (operating expenses large relative to
    total assets) bear more OPERATING risk -- their profits are more
    sensitive to revenue fluctuations -- and are hypothesized to command
    a HIGHER expected return as compensation. This is a POSITIVE risk-
    return relation, the OPPOSITE sign convention from every other
    "risk"-flavored factor already in this module (e.g. `leverage_score`,
    where MORE financial leverage LOWERS the score, since it there
    reflects lower quality rather than a priced risk premium). Novy-
    Marx's own central finding is that this operating-leverage premium is
    strongest when interacted with value, but the plain univariate
    relation he documents is unconditionally positive.

    Found by continuing this session's mining of the account owner's own
    copy of Jensen, Kelly & Pedersen's "Global Factor Data Documentation"
    PDF (the same source that corrected `net_operating_assets_score`'s
    denominator earlier this session) per the account owner's "2번
    진행해" instruction to keep searching that document's ~150-factor
    catalogue for further candidates. JKP's own `opex_at` is a direct,
    single-paper-cited (Novy-Marx 2011) construction -- unlike
    `net_stock_issuance_score`/`net_operating_assets_score`, it needs no
    original-paper workaround.

    JKP's own formula: `opex_at = OPEX*_t / AT*_t`, where `OPEX* = COGS +
    XSGA` is JKP's own STATED FALLBACK for when its preferred `XOPR`
    (total operating expense) tag is unavailable -- this project has
    never ingested `XOPR`, so this fallback form is used directly (the
    same "use JKP's own documented fallback, not its preferred tag" shape
    `net_operating_assets_score`'s own IVAO/DLC omissions already
    followed). Needs ONE new XBRL concept, `SellingGeneralAndAdministrat
    iveExpense` -- `CostOfGoodsAndServicesSold` and `Assets` are already
    ingested for `gross_profitability_score`/`roa_score`.

    Score is the RAW `opex_at` ratio (deliberately NOT negated, per the
    positive risk-return relation stated above). `None` (never a
    fabricated ratio) unless `CostOfGoodsAndServicesSold`,
    `SellingGeneralAndAdministrativeExpense` and `Assets` are all known,
    or `Assets` is non-positive."""
    cogs_record = _latest_fiscal_year_value(repository, security_id, "CostOfGoodsAndServicesSold", as_of_time)
    sga_record = _latest_fiscal_year_value(repository, security_id, "SellingGeneralAndAdministrativeExpense", as_of_time)
    assets_record = _latest_fiscal_year_value(repository, security_id, "Assets", as_of_time)
    if cogs_record is None or sga_record is None or assets_record is None:
        return None
    if assets_record.value <= 0:
        return None
    opex = cogs_record.value + sga_record.value
    return opex / assets_record.value


def abnormal_investment_score(security_id: str, as_of_time: datetime, repository: object) -> Optional[float]:
    """HYPOTHESIS -- Titman, Wei & Xie (2004)'s Abnormal Corporate
    Investment anomaly ("Capital Investments and Stock Returns," Journal
    of Financial and Quantitative Analysis 39(4): 677-700): firms whose
    capital expenditure has grown ABNORMALLY fast relative to their OWN
    recent (3-fiscal-year trailing) capex-to-sales history earn
    systematically LOWER subsequent returns, hypothesized to reflect
    empire-building / overinvestment that the market only gradually
    recognizes as value-destroying.

    Found by continuing this session's mining of the JKP "Global Factor
    Data Documentation" PDF per the account owner's "2번 진행해"
    instruction. JKP's own `capex_abn` is a direct, single-paper-cited
    (Titman, Wei & Xie 2004) construction, used here directly (verified
    against the PDF's exact formula) rather than needing an original-
    paper workaround.

    JKP's own formula: `capex_abn_t = CAPX_SALE_t / avg(CAPX_SALE_{t-12},
    CAPX_SALE_{t-24}, CAPX_SALE_{t-36}) - 1`, where `CAPX_SALE = CAPX /
    SALE*`, sampled MONTHLY. This project substitutes annual fiscal-year
    granularity for JKP's monthly sampling -- the same monthly-to-FY
    substitution this module already makes throughout (e.g.
    `residual_momentum_score`, `sue_score`) -- so `t-12/t-24/t-36`
    (months) become the 3 fiscal years immediately prior to the current
    one, and the current ratio is compared against their average. Needs
    ONE new XBRL concept, `PaymentsToAcquirePropertyPlantAndEquipment`
    (CAPX) -- `Revenues` (SALE*) is already ingested for
    `sales_yield_score`/`gross_profitability_score`.

    Score is the NEGATIVE of `capex_abn`, so a firm whose CURRENT
    capex/sales ratio is abnormally HIGH relative to its own trailing
    3-year average scores LOWER (matches this module's convention that a
    higher score always ranks a security as more attractive). `None`
    (never a fabricated ratio) unless at least 4 fiscal years with BOTH
    `PaymentsToAcquirePropertyPlantAndEquipment` and `Revenues` already
    known (matched by `period_end`) exist as of `as_of_time`, any of
    those 4 years' `Revenues` is non-positive, or the trailing 3-year
    average CAPX/SALE ratio is exactly zero."""
    capex_records = _fy_records(repository, security_id, "PaymentsToAcquirePropertyPlantAndEquipment", as_of_time)
    sales_records = _fy_records(repository, security_id, "Revenues", as_of_time)
    if len(capex_records) < 4 or len(sales_records) < 4:
        return None
    capex_by_period = {r.period_end: r.value for r in capex_records}
    sales_by_period = {r.period_end: r.value for r in sales_records}
    common_periods = sorted(set(capex_by_period) & set(sales_by_period))
    if len(common_periods) < 4:
        return None
    last_four_periods = common_periods[-4:]
    ratios = []
    for period in last_four_periods:
        sales = sales_by_period[period]
        if sales <= 0:
            return None
        ratios.append(capex_by_period[period] / sales)
    current_ratio = ratios[-1]
    trailing_average = sum(ratios[:-1]) / 3.0
    if trailing_average == 0:
        return None
    capex_abn = current_ratio / trailing_average - 1.0
    return -capex_abn


def cash_holdings_score(security_id: str, as_of_time: datetime, repository: object) -> Optional[float]:
    """HYPOTHESIS -- Palazzo (2012)'s cash holdings anomaly ("Cash
    Holdings, Risk, and Expected Returns," Journal of Financial
    Economics 104(1): 162-185): firms holding MORE cash relative to
    their assets earn systematically HIGHER subsequent returns.
    Palazzo's own explanation is risk-based, not mispricing: cash-rich
    firms are disproportionately firms with more valuable growth
    options, whose payoffs are more exposed to the same aggregate
    (cash-flow) shocks that drive market-wide returns, so cash holdings
    proxy for a priced risk exposure rather than for safety. This is a
    POSITIVE risk-return relation, the same "opposite sign convention
    from every other risk factor already in this module" situation
    `operating_leverage_score` already documents for its own paper.

    Found this session (per the account owner's explicit "전부 확인하고
    적용할만 한거 적용해" instruction) via a systematic pass through the
    ENTIRE JKP "Global Factor Data Documentation" PDF's own cited-anomaly
    catalogue (Table 9, ~150 factors across 13 clusters), not just the
    already-surfaced leads `operating_leverage_score`/
    `abnormal_investment_score` came from. Cross-verified two ways: (1)
    JKP's own "New Variables from HXZ" section gives the exact formula
    inline (`cash_at = CASH_t / AT*_t`); (2) Table 9's own "Low Leverage"
    cluster citation list, read in the SAME order as its matching
    abbreviation list two pages earlier, lines up `cash_at` with `Palazzo
    (2012)` -- independently confirmed against this document's own
    References section, which lists the identical paper
    ("Palazzo, B. (2012). Cash holdings, risk, and expected returns.
    Journal of Financial Economics, 104(1), 162-185"). Needs ZERO new
    data: `CashAndCashEquivalentsAtCarryingValue` (ingested for
    `net_operating_assets_score`) and `Assets` are both already fetched.

    Distinct from `net_operating_assets_score` (which treats cash as one
    subtracted component of a much larger balance-sheet mispricing
    ratio, Hirshleifer et al.'s different "bloated balance sheet"
    hypothesis) -- this is cash holdings taken on their own, as Palazzo's
    own distinct risk-based hypothesis.

    Score is the RAW `cash_at` ratio (deliberately NOT negated, per the
    positive risk-return relation above). `None` (never a fabricated
    ratio) unless `CashAndCashEquivalentsAtCarryingValue` and `Assets`
    are both known, or `Assets` is non-positive."""
    cash_record = _latest_fiscal_year_value(repository, security_id, "CashAndCashEquivalentsAtCarryingValue", as_of_time)
    assets_record = _latest_fiscal_year_value(repository, security_id, "Assets", as_of_time)
    if cash_record is None or assets_record is None:
        return None
    if assets_record.value <= 0:
        return None
    return cash_record.value / assets_record.value


def bid_ask_spread_score(
    security_id: str, as_of_time: datetime, data: AsOfDataView, *, lookback_days: int = 21,
) -> Optional[float]:
    """HYPOTHESIS -- Amihud & Mendelson (1986)'s bid-ask spread anomaly
    ("Asset Pricing and the Bid-Ask Spread," Journal of Financial
    Economics 17(2): 223-249): investors demand a return premium for
    holding stocks with a WIDER bid-ask spread (a real transaction cost
    of trading), so a HIGHER spread is hypothesized to predict HIGHER
    subsequent returns -- the same "IMPORTANT SIGN NOTE" situation
    `illiquidity_score`'s own docstring already documents for the
    (distinct) Amihud 2002 measure: illiquidity itself is the priced
    quantity here, not something to negate.

    This module has no real bid/ask quote data, so the spread itself is
    ESTIMATED from daily high/low prices via Corwin & Schultz (2012)'s
    ("A Simple Way to Estimate Bid-Ask Spreads from Daily High and Low
    Prices," The Journal of Finance 67(2): 719-760) closed-form
    estimator -- the same measurement-vs-anomaly citation split
    `OpenSourceAP/CrossSection` (Chen & Zimmermann 2021, Critical
    Finance Review)'s own `BidAskSpread.py` predictor uses (found while
    continuing the account owner's "1 2 실행" instruction: 1 = build the
    split-adjusted high/low infrastructure this estimator needs; 2 =
    keep reviewing that repository's own predictor catalogue for further
    candidates). The estimator's exact formula was verified two
    independent ways before being trusted (a third-party Python
    reimplementation's source, and an independent web summary of the
    same closed-form equations), per this session's now-established
    "never reconstruct a cited algorithm from memory alone" discipline.

    For each pair of consecutive trading days (bars `t-1`, `t`):
    `beta = ln(H_t/L_t)^2 + ln(H_{t-1}/L_{t-1})^2`, `gamma =
    ln(max(H_t,H_{t-1}) / min(L_t,L_{t-1}))^2`, `const = 3 - 2*sqrt(2)`,
    `alpha = (sqrt(2*beta) - sqrt(beta))/const - sqrt(gamma/const)`,
    daily spread `= max(0, 2*(e^alpha - 1)/(1 + e^alpha))` (negative
    estimates floored at zero, the estimator's own documented
    convention). This module's `lookback_days` (default 21, ~1 trading
    month) window of daily estimates is then averaged -- requiring at
    least 12 valid daily estimates, the same minimum-observations
    threshold `OpenSourceAP/CrossSection`'s own monthly aggregation
    documents.

    **Why this needs `adjusted_high`/`adjusted_low`, not raw `high`/
    `low`**: the `gamma` term above compares ONE day's high/low against
    the ADJACENT day's -- if an unadjusted stock split fell between
    those two days, the two days' raw prices sit on different scales
    entirely, producing a spurious, wildly wrong estimate purely from
    the split, not from any real spread or volatility. `close` has
    always had this same raw/adjusted split via `adjusted_close`, but no
    earlier factor in this module ever needed a cross-day comparison of
    price LEVELS (only of returns, for which `adjusted_close` already
    suffices) -- this is the first one that does, so `PriceBar.
    adjusted_high`/`.adjusted_low` were added this session specifically
    for it (see `data_infra.models.PriceBar`'s own docstring). `None`
    (never a fabricated estimate, never a mix of adjusted and raw price
    scales within the same computation) unless EVERY bar used has both
    fields populated -- currently only `TiingoDataProvider` supplies
    them (Tiingo's EOD response already carries `adjHigh`/`adjLow`
    alongside `adjClose`, zero new network requests); `StooqDataProvider`
    supplies raw prices only, so this factor is simply unavailable for
    Stooq-sourced securities, the same honest gap `adjusted_close`
    itself already has there.

    Score is the RAW average estimated spread (deliberately NOT
    negated, per the positive risk-return relation above)."""
    bars = trim_to_lookback(
        data.get_bars(security_id, as_of_time - timedelta(days=int((lookback_days + 10) * 1.6)), as_of_time),
        lookback_days + 1,
    )
    if len(bars) < 2:
        return None
    const = 3.0 - 2.0 * math.sqrt(2.0)
    daily_spreads = []
    for prev_bar, bar in zip(bars[:-1], bars[1:]):
        hi_prev, lo_prev = prev_bar.adjusted_high, prev_bar.adjusted_low
        hi, lo = bar.adjusted_high, bar.adjusted_low
        if hi_prev is None or lo_prev is None or hi is None or lo is None:
            continue
        if hi_prev <= 0 or lo_prev <= 0 or hi <= 0 or lo <= 0:
            continue
        beta = math.log(hi / lo) ** 2 + math.log(hi_prev / lo_prev) ** 2
        high_high = max(hi, hi_prev)
        low_low = min(lo, lo_prev)
        gamma = math.log(high_high / low_low) ** 2
        alpha = (math.sqrt(2 * beta) - math.sqrt(beta)) / const - math.sqrt(gamma / const)
        spread = 2.0 * (math.exp(alpha) - 1.0) / (1.0 + math.exp(alpha))
        daily_spreads.append(max(spread, 0.0))
    if len(daily_spreads) < 12:
        return None
    return sum(daily_spreads) / len(daily_spreads)


def institutional_ownership_change_score(security_id: str, as_of_time: datetime, repository: object) -> Optional[float]:
    """HYPOTHESIS -- Chen, Jegadeesh & Wermers (2000, "The Value of
    Active Mutual Fund Management: An Examination of the Stockholdings
    and Trades of Fund Managers," Journal of Financial and Quantitative
    Analysis 35(3): 343-368): stocks that institutional investors, in
    aggregate, INCREASE their holdings in over a period earn
    systematically HIGHER subsequent returns than stocks they decrease
    holdings in -- "smart money" institutional trading, in aggregate,
    contains real predictive information. Distinct from
    `insider_buying_score` (a single corporate insider's own personal
    Form 4 trades) and `short_interest_score` (aggregate SHORT
    positions, a bet institutions are wrong): this is aggregate LONG
    institutional ownership, disclosed quarterly via SEC Form 13F.

    **Origin**: the account owner's own idea this session -- noting that
    institutional investors, not individual retail traders, are widely
    believed to move most large-cap stock prices, and asking whether
    this project could track institutional positioning directly
    ("기관들의 움직임을 추적할 순 없을까?"). Researched via a GitHub/web
    search for real, open-source Form 13F parsers (`dgunning/edgartools`
    among them) to identify the standard field semantics, continuing
    this session's established practice of verifying a data format
    before building against it rather than guessing.

    **Data source, and the two real, stated limitations new to this
    factor**: `repository` is a `storage.institutional_holding_
    repository.DuckDBInstitutionalHoldingRepository`, populated by
    `scripts.ingest_institutional_holdings` from a LOCAL FILE the user
    produces from SEC Form 13F filings -- not a live network fetch this
    project's own provider layer performs. Two distinct reasons, both
    documented in full in `data_infra.institutional_holding_models`'s
    own module docstring: (1) this sandboxed session cannot reach
    `sec.gov` (`www.sec.gov` and `data.sec.gov` both confirmed blocked
    this session) to independently verify SEC's real Form 13F
    structured data set byte-for-byte; (2) even with access, that data
    set is keyed by CUSIP, an identifier this project's own
    `SecurityMaster` has never carried and has no verified mapping for
    -- a genuinely new kind of gap beyond the network-access limitation
    every other real-data provider integration this session has hit.
    `available_time` on every record is SEC Rule 13f-1's own hard 45-
    calendar-day filing deadline after each quarter's end (a real
    regulatory deadline, not an estimated dissemination schedule the way
    `short_interest_models.SHORT_INTEREST_DISSEMINATION_LAG_DAYS` is) --
    never the quarter-end date itself, the same look-ahead discipline
    `InsiderTransaction.available_time`/`ShortInterestRecord.
    available_time` already apply to their own filing dates.

    **Construction, decided BEFORE any result exists (RULE 0.8)**: the
    RAW log change in aggregate institutional shares held between the
    two most recent quarters with a known report,
    `ln(current_quarter_shares / prior_quarter_shares)` --
    structurally the same `_fy_records`-based year-over-year LOG change
    shape `net_stock_issuance_score` already uses (there, on total
    shares outstanding across fiscal years; here, on aggregate
    institutional shares held across 13F quarters), NOT negated, since
    the hypothesized relation is that MORE institutional buying predicts
    HIGHER returns (matches this module's convention that a higher
    score always ranks a security as more attractive). `None` (never a
    fabricated change) unless at least two distinct quarters' aggregate
    institutional holdings are both already known as of `as_of_time`, or
    the prior quarter's aggregate shares are non-positive."""
    history = repository.get_institutional_holding_history(security_id, as_of_time)
    if len(history) < 2:
        return None
    current, prior = history[-1], history[-2]
    if prior.institutional_shares <= 0 or current.institutional_shares <= 0:
        return None
    return math.log(current.institutional_shares / prior.institutional_shares)
