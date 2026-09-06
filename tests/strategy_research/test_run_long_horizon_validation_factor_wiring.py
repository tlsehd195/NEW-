"""Real, executable tests for the ADR-0051 factory helpers and
candidate tables in `scripts/run_long_horizon_validation.py`
(`_price_factor_factory`/`_fundamentals_factor_factory`/
`_hybrid_factor_factory`/`_universe_factor_factory`,
`_PRICE_FACTOR_CANDIDATES`/`_FUNDAMENTALS_FACTOR_CANDIDATES`/
`_HYBRID_FACTOR_CANDIDATES`/`_UNIVERSE_FACTOR_CANDIDATES`).

Unlike `test_run_long_horizon_validation_wiring.py` (AST/source-text
only, deliberately never importing the module or calling `main()`),
this file DOES import the module -- mirroring the established pattern
`test_compute_fundamentals_ic_from_catalog_cli.py`/
`test_train_ml_model_from_catalog_cli.py` already use for other CLI
scripts (`importlib.util.spec_from_file_location`, never `main()`
itself). Importing the module has no side effects (no network/DB
access happens until `main()` runs); this file never calls `main()`,
so it stays within the same "no real catalog needed" discipline the
AST-only sibling file exists for.

**Why this file exists, specifically**: `main()`'s new candidate-wiring
loops build each strategy factory inside a `for name, hypothesis,
score_fn in ...:` loop -- exactly the shape of Python's classic
late-binding closure bug (a lambda that captures a LOOP VARIABLE by
reference ends up sharing the loop's FINAL value across every
iteration, not the value at the time the lambda was created). Source-
text/AST matching cannot distinguish a correct closure from a buggy
one -- both look identical as text. These tests call the real
`_*_factory` functions the way `main()`'s loops actually call them and
verify each produced strategy is bound to ITS OWN score_fn/version, not
all of them to the last one in the candidates list."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "run_long_horizon_validation.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("run_long_horizon_validation", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_score_fn_a(security_id, as_of_time, *args):
    return 1.0


def _fake_score_fn_b(security_id, as_of_time, *args):
    return 2.0


class TestPriceFactorFactoryNoLateBindingBug:
    def test_two_factories_built_in_a_loop_stay_bound_to_their_own_score_fn(self) -> None:
        module = _load_script()
        security_ids = ["AAA", "BBB"]
        candidates = [("cand_a", "hyp_a", _fake_score_fn_a), ("cand_b", "hyp_b", _fake_score_fn_b)]

        factories = []
        for name, hypothesis, score_fn in candidates:
            factories.append((name, module._price_factor_factory(security_ids, score_fn, f"{name}_v1")))

        strategies = [factory() for _name, factory in factories]
        assert [s.version for s in strategies] == ["cand_a_v1", "cand_b_v1"]
        assert strategies[0]._score_fn is _fake_score_fn_a
        assert strategies[1]._score_fn is _fake_score_fn_b


class TestFundamentalsFactorFactoryNoLateBindingBug:
    def test_two_factories_built_in_a_loop_stay_bound_to_their_own_score_fn(self) -> None:
        module = _load_script()
        security_ids = ["AAA", "BBB"]
        fundamentals_repository = object()
        candidates = [("cand_a", "hyp_a", _fake_score_fn_a), ("cand_b", "hyp_b", _fake_score_fn_b)]

        factories = []
        for name, hypothesis, score_fn in candidates:
            factories.append((
                name, module._fundamentals_factor_factory(security_ids, fundamentals_repository, score_fn, f"{name}_v1"),
            ))

        strategies = [factory() for _name, factory in factories]
        assert [s.version for s in strategies] == ["cand_a_v1", "cand_b_v1"]
        assert strategies[0]._score_fn is _fake_score_fn_a
        assert strategies[1]._score_fn is _fake_score_fn_b
        assert strategies[0]._fundamentals_repository is fundamentals_repository


class TestHybridFactorFactoryNoLateBindingBug:
    def test_two_factories_built_in_a_loop_stay_bound_to_their_own_score_fn_and_repositories(self) -> None:
        module = _load_script()
        security_ids = ["AAA", "BBB"]
        fundamentals_repository = object()
        price_repository = object()
        candidates = [("cand_a", "hyp_a", _fake_score_fn_a), ("cand_b", "hyp_b", _fake_score_fn_b)]

        factories = []
        for name, hypothesis, score_fn in candidates:
            factories.append((
                name,
                module._hybrid_factor_factory(security_ids, fundamentals_repository, price_repository, score_fn, f"{name}_v1"),
            ))

        strategies = [factory() for _name, factory in factories]
        assert [s.version for s in strategies] == ["cand_a_v1", "cand_b_v1"]
        assert strategies[0]._score_fn is _fake_score_fn_a
        assert strategies[1]._score_fn is _fake_score_fn_b
        assert strategies[0]._fundamentals_repository is fundamentals_repository
        assert strategies[0]._price_repository is price_repository


class TestUniverseFactorFactoryNoLateBindingBug:
    def test_two_factories_built_in_a_loop_stay_bound_to_their_own_score_fn(self) -> None:
        module = _load_script()
        security_ids = ["AAA", "BBB"]
        fundamentals_repository = object()
        price_repository = object()
        candidates = [("cand_a", "hyp_a", _fake_score_fn_a), ("cand_b", "hyp_b", _fake_score_fn_b)]

        factories = []
        for name, hypothesis, score_fn in candidates:
            factories.append((
                name,
                module._universe_factor_factory(security_ids, fundamentals_repository, price_repository, score_fn, f"{name}_v1"),
            ))

        strategies = [factory() for _name, factory in factories]
        assert [s.version for s in strategies] == ["cand_a_v1", "cand_b_v1"]
        assert strategies[0]._score_fn is _fake_score_fn_a
        assert strategies[1]._score_fn is _fake_score_fn_b


class TestCandidateTables:
    """The 6 module-level candidate tables together must reproduce
    exactly the 20 names in PROJECT_STATUS.md's raw-IC-screening table
    (ADR-0051), plus the 11 Session 36 additions wired in afterward
    (`idiosyncratic_volatility`, ADR-0053; `combined_factor`, ADR-0054;
    `sue`, ADR-0084; `insider_buying`, ADR-0086; `rs_rating`, found via
    the dragon1086/prism-insight comparison; `residual_momentum`,
    `rd_expenditure`, `return_seasonality` and `short_interest`, found
    via a GitHub/web search for borrowable strategies, paperswithbacktest/
    awesome-systematic-trading; `net_stock_issuance` and
    `net_operating_assets`, found via a further GitHub/web search
    -- bkelly-lab/ReplicationCrisis surfaced these themes, built from
    the original underlying papers since that repository's own exact
    formulas could not be verified from this sandbox; `operating_leverage`,
    `abnormal_investment` and `cash_holdings`, found by mining the JKP
    "Global Factor Data Documentation" PDF -- the first two from
    already-surfaced leads ("2번 진행해"), `cash_holdings` from a
    subsequent SYSTEMATIC pass through the document's entire ~150-factor
    cited-anomaly catalogue ("전부 확인하고 적용할만 한거 적용해") --
    all three single-paper-cited JKP constructions used directly,
    verified against the PDF itself; `bid_ask_spread`, Amihud & Mendelson
    1986 measured via the Corwin & Schultz 2012 estimator, found while
    reviewing OpenSourceAP/CrossSection's predictor catalogue -- the
    first factor needing the `PriceBar.adjusted_high`/`.adjusted_low`
    infrastructure added this same session, ADR-0103; `institutional_
    ownership_change`, Chen, Jegadeesh & Wermers 2000, the account
    owner's own idea this session ("기관들의 움직임을 추적할 순 없을까?") --
    sourced from a SIXTH, distinct DuckDB catalog, ADR-0104; `idiosyncratic_
    skewness`, Boyer, Mitton & Vorkink 2010, `downside_beta`, Ang, Chen &
    Xing 2006, and `share_turnover`, Datar, Naik & Radcliffe 1998, all
    found via WebSearch literature verification per the account owner's
    "일단 우리 전략을 최대한 늘리자" instruction, ADR-0105; `high_volume_
    return_premium`, Gervais, Kaniel & Mingelgrin 2001, `asset_turnover_
    change`, Fairfield & Yohn 2001 / Soliman 2008, and `industry_momentum`,
    Moskowitz & Grinblatt 1999 (the first factor needing sector data,
    `data_infra.universe.get_sector`), all found the same way per the
    account owner's further "가능한 많이 전략을 더 찾아봐" instruction,
    ADR-0106 -- all needing zero new data acquisition) -- 42 total -- no
    name collisions with each other, or with the 8 pre-existing
    candidates already in `strategy_specs` before ADR-0051."""

    _EXPECTED_NAMES = {
        "long_term_reversal", "short_term_reversal", "low_beta", "illiquidity",
        "fifty_two_week_high", "max_effect",
        "asset_growth", "piotroski", "sloan_accruals", "dividend_growth", "gross_profitability",
        "shareholder_yield", "earnings_yield", "book_to_market", "sales_yield",
        "cashflow_yield", "size", "altman_z",
        "quality_minus_junk", "value_composite",
        "idiosyncratic_volatility", "combined_factor", "sue", "insider_buying", "rs_rating",
        "residual_momentum", "rd_expenditure", "return_seasonality", "short_interest",
        "net_stock_issuance", "net_operating_assets",
        "operating_leverage", "abnormal_investment", "cash_holdings", "bid_ask_spread",
        "institutional_ownership_change",
        "idiosyncratic_skewness", "downside_beta", "share_turnover",
        "high_volume_return_premium", "asset_turnover_change", "industry_momentum",
    }
    _PRE_EXISTING_NAMES = {
        "buy_and_hold", "long_term_momentum", "trend_volatility", "risk_controlled_momentum",
        "leverage", "ml_ols", "ml_ridge", "rank_average_ensemble",
    }

    def _all_new_candidate_names(self, module):
        names = []
        for table in (
            module._PRICE_FACTOR_CANDIDATES, module._FUNDAMENTALS_FACTOR_CANDIDATES,
            module._HYBRID_FACTOR_CANDIDATES, module._UNIVERSE_FACTOR_CANDIDATES,
            module._INSIDER_FACTOR_CANDIDATES, module._SHORT_INTEREST_FACTOR_CANDIDATES,
            module._INSTITUTIONAL_FACTOR_CANDIDATES,
        ):
            names.extend(name for name, _hypothesis, _score_fn in table)
        return names

    def test_all_42_expected_names_present_exactly_once(self) -> None:
        module = _load_script()
        names = self._all_new_candidate_names(module)
        assert len(names) == len(set(names)), "duplicate candidate name across the 6 tables"
        assert set(names) == self._EXPECTED_NAMES

    def test_no_collision_with_pre_existing_candidate_names(self) -> None:
        module = _load_script()
        names = set(self._all_new_candidate_names(module))
        assert not (names & self._PRE_EXISTING_NAMES)

    def test_every_table_entry_score_fn_is_callable(self) -> None:
        module = _load_script()
        for table in (
            module._PRICE_FACTOR_CANDIDATES, module._FUNDAMENTALS_FACTOR_CANDIDATES,
            module._HYBRID_FACTOR_CANDIDATES, module._UNIVERSE_FACTOR_CANDIDATES,
            module._INSIDER_FACTOR_CANDIDATES, module._SHORT_INTEREST_FACTOR_CANDIDATES,
            module._INSTITUTIONAL_FACTOR_CANDIDATES,
        ):
            for name, hypothesis, score_fn in table:
                assert callable(score_fn), f"{name}'s score_fn is not callable"
                assert isinstance(hypothesis, str) and hypothesis
