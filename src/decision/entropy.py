"""Normalized Shannon entropy over a discrete probability distribution.

Batch L (`EXTERNAL_REPO_APPLICABILITY_REPORT.md` priority-7, colibri's
"Brio" mode): quantifies how uncertain a set of probabilities is, on a
0..1 scale, so a decision gate can act on a measured confidence number
instead of eyeballing raw probabilities. An independent reimplementation
of colibri's own formula (`c/openai_server.py:4073-4081`, per the
report's own re-verification) -- not a copy of any colibri code, a
plain Python function with no dependency on colibri, any specific
provider, or any part of this project's own `ai_gateway`/`decision`
packages.

**Not yet wired into `decision.agent.BaselineRuleDecisionAgent`.**
Today's only provider (`ai_gateway.provider.MockProviderAdapter`)
returns a single structured JSON response, never a probability
distribution over a closed set of outcomes -- there is nothing real to
compute entropy from yet. This primitive exists so a future `Predictor`
or provider that DOES expose logprobs/probabilities over discrete
options (colibri's own Brio mode, or any OpenAI-compatible provider
that returns logprobs) has a ready, independently tested formula to
plug into a new gate, following this project's own ADR-0151 "adopt now,
wire in later" precedent (also used for `ai_gateway.admission.
RpmAdmissionGate`, Batch K)."""

from __future__ import annotations

import math
from typing import Sequence


def normalized_entropy(probabilities: Sequence[float]) -> float:
    """Shannon entropy of `probabilities`, normalized to `[0, 1]` by
    dividing by the maximum possible entropy for this many outcomes
    (`ln(n)`, guarded to `ln(max(n, 2))` so a single-outcome
    distribution never divides by `ln(1) == 0`, matching colibri's own
    guard).

    `0.0` means fully certain (one outcome has probability 1); `1.0`
    means maximally uncertain (a uniform distribution over every
    outcome). `probabilities` need not already sum to 1.0 -- raw
    softmax output or unnormalized weights are normalized here first,
    so the result is the same as if the caller had normalized before
    calling."""
    if not probabilities:
        raise ValueError("normalized_entropy requires at least one probability")
    if any(p < 0 for p in probabilities):
        raise ValueError("normalized_entropy requires every probability to be non-negative")
    total = sum(probabilities)
    if total <= 0:
        raise ValueError("normalized_entropy requires the probabilities to sum to a positive value")

    normalized = [p / total for p in probabilities]
    entropy = -sum(p * math.log(max(p, 1e-12)) for p in normalized)
    max_entropy = math.log(max(len(probabilities), 2))
    return entropy / max_entropy
