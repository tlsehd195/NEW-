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

from datetime import datetime, timedelta
from typing import Optional

from backtest.asof import AsOfDataView
from backtest.metrics import annualized_volatility, compute_returns

from strategy_research._dates import trim_to_lookback


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
