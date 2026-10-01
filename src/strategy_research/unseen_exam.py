"""Half-new exam on a locked window using never-evaluated names (ADR-0225).

A locked window's answer key is "how these names did then". Names that
were never evaluated over that window have not been seen, so a backtest
restricted to them is closer to a fresh exam, though the market's overall
path in that window is already known. This module decides which names are
unseen and whether a window's exam has already been taken.

Rules (ADR-0225):

- A name is SEEN for a window if it belongs to any named research universe
  (`data_infra.universe`), is the benchmark, or appears in `security_ids`
  of any report in `docs/research/reports/` whose evaluated range overlaps
  the window. Exam reports carry their own `security_ids`, so an exam's
  names become seen once its report is committed.
- One exam per locked window. A report carrying `unseen_names_exam` for a
  window blocks a second exam there.
- Only pre-registered finalists are examined, next to an equal-weight
  buy-and-hold of the same unseen names (the benchmark that matters,
  because the unseen names exclude today's large survivors). The
  buy-and-hold is compared gross, without costs (ADR-0228).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Optional

from data_infra.universe import (
    BENCHMARK_SYMBOL,
    PILOT_UNIVERSE_V1,
    RESEARCH_UNIVERSE_STAGE1,
    RESEARCH_UNIVERSE_STAGE2,
    RESEARCH_UNIVERSE_STAGE3,
    RESEARCH_UNIVERSE_STAGE4,
    RESEARCH_UNIVERSE_STAGE5,
)
from strategy_research.locked_windows import LOCKED_WINDOWS, LockedWindow

_NAMED_UNIVERSES = (
    PILOT_UNIVERSE_V1,
    RESEARCH_UNIVERSE_STAGE1,
    RESEARCH_UNIVERSE_STAGE2,
    RESEARCH_UNIVERSE_STAGE3,
    RESEARCH_UNIVERSE_STAGE4,
    RESEARCH_UNIVERSE_STAGE5,
)

EXAM_REPORT_KEY = "unseen_names_exam"


def locked_window_by_name(name: str) -> LockedWindow:
    for window in LOCKED_WINDOWS:
        if window.name == name:
            return window
    raise KeyError(f"no locked window named {name!r}; known: {[w.name for w in LOCKED_WINDOWS]}")


def _parse_time(value) -> Optional[datetime]:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _reports(reports_dir: Path) -> Iterable[tuple[Path, dict]]:
    for path in sorted(Path(reports_dir).glob("*.json")):
        try:
            report = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(report, dict):
            yield path, report


def _overlaps(report: dict, window: LockedWindow) -> bool:
    start, end = _parse_time(report.get("overall_start")), _parse_time(report.get("overall_end"))
    if start is None or end is None:
        return True  # no range recorded: assume it saw everything
    return start < window.end and end > window.start


def seen_symbols(
    window: LockedWindow, reports_dir: Path, renames: Optional[Mapping[str, str]] = None,
) -> frozenset[str]:
    """`renames` (old -> new ticker) marks a renamed company seen under its
    new ticker too, so a name evaluated as FB is not unseen as META."""
    seen: set[str] = {BENCHMARK_SYMBOL}
    for universe in _NAMED_UNIVERSES:
        seen.update(universe.symbol_ids)
    for _, report in _reports(reports_dir):
        if report.get("security_ids") and _overlaps(report, window):
            seen.update(report["security_ids"])
    for old, new in (renames or {}).items():
        if old in seen:
            seen.add(new)
    return frozenset(seen)


def exam_already_taken(window: LockedWindow, reports_dir: Path) -> Optional[Path]:
    for path, report in _reports(reports_dir):
        exam = report.get(EXAM_REPORT_KEY)
        if isinstance(exam, dict) and exam.get("window") == window.name:
            return path
    return None


def exam_verdict(candidate: dict, baseline: dict) -> str:
    """Pre-registered in ADR-0225: PASS only if the candidate beats the
    same-names equal-weight buy-and-hold on both CAGR and Sharpe.
    Anything else is FAIL. A PASS is a half-exam result, not a DSR-backed
    validation, and it must not be used to tune the candidate.

    `candidate` is the candidate's NET performance and `baseline` the
    buy-and-hold's GROSS performance (ADR-0228): with $1 per order and
    $10,000 spread over hundreds of names, the net buy-and-hold pays
    several percent in commissions an index fund would not."""
    if candidate["cagr"] > baseline["cagr"] and candidate["sharpe_ratio"] > baseline["sharpe_ratio"]:
        return "PASS"
    return "FAIL"


def verdict_against_buy_and_hold(candidate_run: dict, baseline_run: dict) -> str:
    """`*_run` hold `is_valid_performance`, `net` and `gross`. INVALID if
    either run failed the integrity checks, else `exam_verdict` on the
    candidate's net against the buy-and-hold's gross (ADR-0225/0228)."""
    if not (candidate_run["is_valid_performance"] and baseline_run["is_valid_performance"]):
        return "INVALID"
    return exam_verdict(candidate_run["net"], baseline_run["gross"])


def parse_candidate_list(text: str, known: Iterable[str]) -> frozenset[str]:
    """Comma-separated finalist names. Unknown names are an error, so a
    typo cannot silently drop a finalist from a once-only run."""
    names = frozenset(n.strip() for n in text.split(",") if n.strip())
    if not names:
        raise ValueError("empty candidate list")
    unknown = names - set(known)
    if unknown:
        raise ValueError(f"unknown candidates: {sorted(unknown)}")
    return names
