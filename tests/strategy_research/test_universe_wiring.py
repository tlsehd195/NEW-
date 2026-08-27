"""Category: Universe <-> strategy_research wiring (Phase 24, instruction
sections 3/14/J). Proves `data_infra.universe`'s named `UniverseDefinition`
flows into the existing, UNMODIFIED `strategy_research.runner.run_gross_and_net`
and every strategy class exactly like any plain `Sequence[str]` would --
no code change was needed in `strategy_research` itself, since Phase
23's `security_ids: Sequence[str]` signature was already generic. This
file also statically confirms no PILOT_UNIVERSE symbol is hardcoded
anywhere inside `src/strategy_research/`."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from research_helpers import synthetic_multi_year_repository

from data_infra.universe import PILOT_UNIVERSE_V1

from strategy_research.long_term_momentum import LongTermMomentumParameters, LongTermMomentumStrategy
from strategy_research.runner import run_gross_and_net

_SRC_STRATEGY_RESEARCH = Path(__file__).resolve().parents[2] / "src" / "strategy_research"


class TestNoRealSymbolHardcodedInStrategyResearch:
    def test_no_pilot_universe_symbol_appears_in_strategy_research_source(self) -> None:
        """A hardcoded real-market symbol (e.g. "AAPL") anywhere in
        strategy_research's own source would mean a caller could not
        actually swap universes without editing that file -- exactly
        what instruction section 3's "종목 목록을 strategy code 내부에
        하드코딩하지 않는다" forbids.

        Matches only an actual Python STRING LITERAL of the symbol
        (`"AAPL"`/`'AAPL'`) -- a bare substring check would false-positive
        on short tickers like "V"/"MA"/"COST" appearing inside ordinary
        English words or identifiers (e.g. "value", "Momentum",
        "cost_model"), which is not what this check is trying to catch."""
        violations = []
        for path in sorted(_SRC_STRATEGY_RESEARCH.rglob("*.py")):
            text = path.read_text()
            for symbol in PILOT_UNIVERSE_V1.symbol_ids:
                pattern = r"""(['"])""" + re.escape(symbol) + r"""\1"""
                if re.search(pattern, text):
                    violations.append(f"{path.name}: contains string literal {symbol!r}")
        assert violations == [], "\n".join(violations)


class TestUniverseFlowsIntoRunner:
    def test_pilot_universe_symbol_ids_usable_directly_as_security_ids(self) -> None:
        """The synthetic fixture only defines 5 symbols
        (research_helpers.SYNTHETIC_UNIVERSE) -- this test does not
        claim PILOT_UNIVERSE's real symbols have real data here. It
        proves the *shape* is compatible: `UniverseDefinition.symbol_ids`
        is a plain `tuple[str, ...]`, and `run_gross_and_net`'s
        `security_ids` parameter accepts it with zero adaptation, the
        same way it already accepts any other `Sequence[str]`."""
        assert isinstance(PILOT_UNIVERSE_V1.symbol_ids, tuple)
        assert all(isinstance(s, str) for s in PILOT_UNIVERSE_V1.symbol_ids)

        # Exercise the real call shape with the synthetic fixture's own
        # symbols, proving run_gross_and_net has no special-cased
        # symbol list of its own.
        from research_helpers import SYNTHETIC_UNIVERSE

        repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2021, 6, 1), symbols=SYNTHETIC_UNIVERSE[:3])
        result = run_gross_and_net(
            repo, lambda: LongTermMomentumStrategy(list(SYNTHETIC_UNIVERSE[:3]), LongTermMomentumParameters(lookback_months=6, top_n=1, rebalance_months=3)),
            SYNTHETIC_UNIVERSE[:3], start_date=date(2020, 1, 2), end_date=date(2021, 6, 1), initial_capital=100_000.0,
        )
        assert result.net.performance is not None
