"""Cumulative trial ledger for Deflated Sharpe (ADR on test-window exhaustion).

`compute_dsr_for_all_candidates` deflates against the candidates of ONE
run. Harvey-Liu-Zhu (2016) / Bailey et al. (2014): the right N is every
candidate ever tried on this data. The ledger is derived from the
committed `full-validation-*.json` reports (no new state to drift): any
candidate name that appeared in a prior report's
`pbo_dsr_result.deflated_sharpe_by_candidate` and is absent from the
current run is counted as an extra trial.

Prior trials' Sharpes are not stored, so they enter as zero-Sharpe trials
(same convention as `zero_sharpe_trials`, ADR-0220). This is informational:
it never replaces the per-run DSR used by the evidence classifier.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from strategy_research.pbo_dsr import DsrResult, compute_dsr_for_all_candidates

DEFAULT_REPORTS_DIR = Path("docs/research/reports")


def load_prior_candidate_names(reports_dir: Path = DEFAULT_REPORTS_DIR) -> frozenset[str]:
    names: set[str] = set()
    for path in sorted(reports_dir.glob("full-validation-*.json")):
        try:
            report = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        pbo_dsr = report.get("pbo_dsr_result") or {}
        names.update((pbo_dsr.get("deflated_sharpe_by_candidate") or {}))
    return frozenset(names)


def compute_cumulative_dsr(
    fold_returns_by_candidate: Mapping[str, Sequence[float]],
    reports_dir: Path = DEFAULT_REPORTS_DIR,
) -> dict[str, DsrResult]:
    prior = load_prior_candidate_names(reports_dir) - set(fold_returns_by_candidate)
    return compute_dsr_for_all_candidates(fold_returns_by_candidate, zero_sharpe_trials=len(prior))
