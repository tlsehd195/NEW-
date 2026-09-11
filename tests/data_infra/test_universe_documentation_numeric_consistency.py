"""Category: Documentation/Code numeric-consistency regression (Session 37).

An external third-party review of commit `1435afb` found that
`docs/PROJECT_STATUS.md` and `src/data_infra/universe.py`'s own
docstrings/comments had been silently carrying a stale "16-symbol
PILOT_UNIVERSE" / "40-symbol"/"64-symbol" figure since before Stage 3
was added -- the real counts (`tests/data_infra/test_universe.py::
TestPilotUniversePreserved` already asserts the PILOT symbol *set*
itself has always been 15, not 16) never actually matched the prose
describing them. This file guards against that specific class of
regression: the actual `UniverseDefinition.symbols` counts, cross-
checked against both the code comments describing them and the
`docs/PROJECT_STATUS.md` prose that cites them, so a future edit that
reintroduces a stale count (in either direction) fails a test rather
than only being caught by another manual review."""

from __future__ import annotations

from pathlib import Path

from data_infra.universe import (
    PILOT_UNIVERSE_V1,
    RESEARCH_UNIVERSE_STAGE2,
    RESEARCH_UNIVERSE_STAGE3,
    RESEARCH_UNIVERSE_STAGE4,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PROJECT_STATUS = (_REPO_ROOT / "docs" / "PROJECT_STATUS.md").read_text(encoding="utf-8")
_UNIVERSE_SOURCE = (_REPO_ROOT / "src" / "data_infra" / "universe.py").read_text(encoding="utf-8")


class TestActualUniverseCounts:
    """The ground truth every other assertion in this file is checked
    against -- if a future universe change legitimately changes these
    counts, THIS class is meant to fail first, as a signal that every
    prose reference below needs a matching update, not silent drift."""

    def test_pilot_is_15(self) -> None:
        assert len(PILOT_UNIVERSE_V1.symbols) == 15

    def test_stage2_is_39(self) -> None:
        assert len(RESEARCH_UNIVERSE_STAGE2.symbols) == 39

    def test_stage3_is_63(self) -> None:
        assert len(RESEARCH_UNIVERSE_STAGE3.symbols) == 63

    def test_stage4_is_87(self) -> None:
        assert len(RESEARCH_UNIVERSE_STAGE4.symbols) == 87

    def test_stage3_adds_exactly_24_new_symbols_over_stage2(self) -> None:
        new = set(RESEARCH_UNIVERSE_STAGE3.symbol_ids) - set(RESEARCH_UNIVERSE_STAGE2.symbol_ids)
        assert len(new) == 24

    def test_stage4_adds_exactly_24_new_symbols_over_stage3(self) -> None:
        new = set(RESEARCH_UNIVERSE_STAGE4.symbol_ids) - set(RESEARCH_UNIVERSE_STAGE3.symbol_ids)
        assert len(new) == 24


class TestUniverseSourceCommentsMatchActualCounts:
    def test_no_stale_16_symbol_pilot_wording_remains(self) -> None:
        assert "16-symbol" not in _UNIVERSE_SOURCE
        assert "16 symbols" not in _UNIVERSE_SOURCE

    def test_pilot_docstring_states_the_real_15_symbol_count(self) -> None:
        assert "15-symbol" in _UNIVERSE_SOURCE
        assert "15 symbols" in _UNIVERSE_SOURCE


class TestProjectStatusMatchesActualCounts:
    """Guards specifically against the exact stale substrings the
    external review flagged -- not a general prose-correctness check
    (PROJECT_STATUS.md is a free-form running log; this only pins the
    numbers that were factually wrong)."""

    def test_no_stale_40_to_64_stage3_expansion_wording_remains(self) -> None:
        assert "40→64종목" not in _PROJECT_STATUS
        assert "이제 64종목" not in _PROJECT_STATUS
        assert "PILOT 16 + Stage2 24" not in _PROJECT_STATUS
        assert "real Stage 3(64종목)" not in _PROJECT_STATUS

    def test_correct_39_to_63_stage3_expansion_wording_is_present(self) -> None:
        assert "39→63종목" in _PROJECT_STATUS
        assert "PILOT 15 + Stage2 24" in _PROJECT_STATUS
        assert "이제 63종목" in _PROJECT_STATUS

    def test_no_additional_stale_40_or_16_symbol_prose_beyond_the_two_known_phase22_mentions(self) -> None:
        # ADR-0115: the external review's own critique of this test file
        # was that it only pins the exact strings ADR-0112 fixed, so any
        # OTHER stale "40종목"/"16종목" sentence (same class of error,
        # just not one of the originally-cited locations) goes
        # undetected. This counts total occurrences instead of matching
        # specific sentences, so a newly-introduced stale mention (in
        # either direction) fails this test rather than only being
        # caught by another manual review. The only two legitimate
        # "16종목" mentions left in the document both name Phase 22's
        # own, textually distinct 16-ticker US long-term universe
        # (AAPL/MSFT/.../SPY -- genuinely 16 real symbols, not
        # PILOT_UNIVERSE_V1/RESEARCH_UNIVERSE_STAGE2) -- "40종목" has no
        # legitimate referent anywhere in this document at all.
        import re

        assert len(re.findall(r"40종목", _PROJECT_STATUS)) == 0
        assert len(re.findall(r"16종목", _PROJECT_STATUS)) == 2

    def test_stage3_24_symbol_breakdown_sums_to_24_not_25(self) -> None:
        # The external review's own finding: 4 (Real Estate) + 4
        # (Materials) + 3 (Utilities) + "나머지 N" must sum to 24 --
        # the document previously said N=14 (summing to 25). Pin the
        # corrected breakdown explicitly rather than re-deriving it from
        # prose, since the prose itself is what regresses.
        assert "PLD/AMT/EQIX/SPG [4]" in _PROJECT_STATUS
        assert "LIN/APD/ECL/NEM [4]" in _PROJECT_STATUS
        assert "DUK/SO/D [3]" in _PROJECT_STATUS
        assert "나머지 13종목" in _PROJECT_STATUS
        assert "4+4+3+13=24" in _PROJECT_STATUS
