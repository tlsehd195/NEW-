"""ResearchLog: the multiple-testing transparency record instruction
section 26 requires -- number of candidates tried, parameter
combinations, selection procedure, final selection, and every rejected
candidate, all kept (never pruned to just "the winner").
"""

from __future__ import annotations

from dataclasses import dataclass, field

from strategy_research.classification import CandidateClassification, CandidateEvaluation


@dataclass
class ResearchLog:
    selection_procedure: str

    def __post_init__(self) -> None:
        self._entries: list[CandidateEvaluation] = []

    def record(self, evaluation: CandidateEvaluation) -> None:
        """Appends one evaluation. Never overwrites or removes a prior
        entry -- calling this twice for the "same" strategy (e.g. after
        adjusting parameters) produces two log entries, both visible in
        `all_entries()`, so a change made after seeing a result is never
        silently invisible (instruction section 24's
        no-peeking-then-retrying rule is made auditable here, even
        though this class cannot itself prevent the peeking)."""
        self._entries.append(evaluation)

    def all_entries(self) -> tuple[CandidateEvaluation, ...]:
        return tuple(self._entries)

    def by_classification(self, classification: CandidateClassification) -> tuple[CandidateEvaluation, ...]:
        return tuple(e for e in self._entries if e.classification == classification)

    @property
    def candidate_count(self) -> int:
        return len(self._entries)

    def parameter_combination_count(self) -> int:
        """Distinct (strategy_name, parameters) pairs actually tried --
        a rough proxy for how much multiple-testing exposure this
        research session accumulated, reported honestly rather than
        omitted (instruction section 26)."""
        seen = {(e.strategy_name, tuple(sorted(e.parameters.items()))) for e in self._entries}
        return len(seen)

    def summary(self) -> dict:
        return {
            "selection_procedure": self.selection_procedure,
            "candidate_count": self.candidate_count,
            "parameter_combination_count": self.parameter_combination_count(),
            "rejected": len(self.by_classification(CandidateClassification.REJECTED)),
            "inconclusive": len(self.by_classification(CandidateClassification.INCONCLUSIVE)),
            "promising_candidate": len(self.by_classification(CandidateClassification.PROMISING_CANDIDATE)),
            "strategies": [
                {
                    "strategy_name": e.strategy_name,
                    "strategy_version": e.strategy_version,
                    "classification": e.classification.value,
                    "rejection_reason": e.rejection_reason,
                }
                for e in self._entries
            ],
        }
