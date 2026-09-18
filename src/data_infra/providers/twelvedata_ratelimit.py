"""TwelveDataRateLimiter: proactive, client-side pacing of real Twelve
Data calls to stay under its real published free-tier limit (8
requests/minute).

**Confirmed as a real, not theoretical, constraint** by a real
`workflow_dispatch` production run (2026-09-18, ADR-0164's own
follow-up correction): with no pacing at all, ~39 requests fired in a
tight burst (the tail of `RESEARCH_UNIVERSE` Tiingo's own exhausted
budget hands off to this tier) immediately exceeded 8/minute, so this
project's own second fallback tier failed Transient just as often as
the first tier's exhausted budget it exists to relieve.

**Sleeps until a call is safe, unlike `TiingoRequestBudget`'s hard
proactive refusal.** Tiingo's real cap is per-HOUR -- a quota already
used up genuinely cannot be waited out inside the same run, so refusing
outright is correct there. Twelve Data's real cap is per-MINUTE, which
genuinely clears within seconds -- the accepted cost of pacing is a
slower ingestion run (at most a few minutes for `RESEARCH_UNIVERSE`'s
current size), never a failed one.

**Rolling window, not a fixed-minute bucket**, same reasoning
`TiingoRequestBudget` already gives for its own rolling hour: tracks
individual request timestamps and prunes whatever has aged out of the
trailing 60 seconds, rather than a wall-clock minute boundary this
project would otherwise have to invent and guess the phase of.

**Deliberately instance-shared, never a module-level global** -- a
limiter owned by `TwelveDataHttpTransport` is shared automatically, by
construction, as long as only one transport instance is built and
reused, mirroring `TiingoRequestBudget`'s identical discipline.
"""

from __future__ import annotations

import time
from typing import Callable, List


class TwelveDataRateLimiter:
    """Tracks real Twelve Data HTTP calls in a rolling 60-second window
    against the account's real per-minute cap, sleeping before a call
    that would exceed it rather than refusing. `safety_margin=1` (7 of
    the real 8 treated as the effective cap) mirrors
    `TiingoRequestBudget`'s reasoning: small enough not to waste much
    real throughput, large enough to absorb an off-by-one without a
    real 429."""

    _WINDOW_SECONDS = 60.0

    def __init__(
        self,
        *,
        limit_per_minute: int = 8,
        safety_margin: int = 1,
        clock: Callable[[], float] = time.monotonic,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        if limit_per_minute <= 0:
            raise ValueError("limit_per_minute must be positive")
        if safety_margin < 0 or safety_margin >= limit_per_minute:
            raise ValueError("safety_margin must be non-negative and less than limit_per_minute")
        self.limit_per_minute = limit_per_minute
        self.safety_margin = safety_margin
        self._effective_cap = limit_per_minute - safety_margin
        self._clock = clock
        self._sleep_fn = sleep_fn
        self._request_times: List[float] = []

    def _prune_expired(self) -> None:
        cutoff = self._clock() - self._WINDOW_SECONDS
        while self._request_times and self._request_times[0] <= cutoff:
            self._request_times.pop(0)

    def wait_if_needed(self) -> None:
        """Must be called immediately BEFORE every real HTTP call --
        sleeps (possibly zero times, possibly more than once if the
        clock/sleep_fn are faked in a test) until making the call would
        not exceed the effective cap."""
        self._prune_expired()
        while len(self._request_times) >= self._effective_cap:
            oldest = self._request_times[0]
            wait_seconds = (oldest + self._WINDOW_SECONDS) - self._clock()
            if wait_seconds > 0:
                self._sleep_fn(wait_seconds)
            self._prune_expired()

    def record_request(self) -> None:
        """Must be called once for every real HTTP call actually made
        against Twelve Data, including one that goes on to fail --
        same discipline as `TiingoRequestBudget.record_request()`."""
        self._prune_expired()
        self._request_times.append(self._clock())
