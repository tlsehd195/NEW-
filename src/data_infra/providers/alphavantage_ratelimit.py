"""AlphaVantageRateLimiter: proactive, client-side pacing of real Alpha
Vantage calls to stay under its real published free-tier limit of 1
request/second.

**Confirmed as a real, not theoretical, constraint** (2026-09-25,
`scripts/recon_corporate_action_providers.py`'s own real
`workflow_dispatch` run): two Alpha Vantage calls fired ~4ms apart --
the first got real DIVIDENDS data, the second (SPLITS) got only Alpha
Vantage's own "Information" throttle notice ("Please consider spreading
out your free API requests more sparingly (1 request per second)")
instead of real data. A re-run with a >1s gap between calls got a real
answer for both. `AlphaVantageDataProvider.fetch_corporate_actions()`
below makes exactly this same back-to-back pattern (DIVIDENDS then
SPLITS) for every symbol, so it needs the same pacing this recon script
already applied by hand.

**Sleeps until a call is safe, same reasoning `TwelveDataRateLimiter`
already gives for its own per-minute pacing**: Alpha Vantage's
per-second limit clears in about a second, so the accepted cost of
pacing is a slightly slower run, never a failed one -- unlike Tiingo's
real per-HOUR cap (`TiingoRequestBudget`), which cannot be waited out
inside the same run and is therefore a proactive REFUSAL instead. Alpha
Vantage's separate 25-requests/DAY cap is not enforced here -- this
provider is only ever reached as a fallback tier after Tiingo has
already failed for a symbol (rare in practice), and a real quota
rejection there already comes back as a real `TransientProviderError`
via the existing "Note"/"Information" body-shape handling in
`AlphaVantageDataProvider.fetch()`/`fetch_corporate_actions()` --
proactively refusing on top of that would need to track usage across
process restarts (this project's other budgets are explicitly
per-process only, see `TiingoRequestBudget`'s own docstring) to be
worth the added complexity.

**Deliberately instance-shared, never a module-level global** -- a
limiter owned by `AlphaVantageHttpTransport` is shared automatically,
by construction, as long as only one transport instance is built and
reused, mirroring `TwelveDataRateLimiter`'s identical discipline.
"""

from __future__ import annotations

import time
from typing import Callable, List


class AlphaVantageRateLimiter:
    """Tracks real Alpha Vantage HTTP calls in a rolling 1-second
    window against the account's real per-second cap, sleeping before a
    call that would exceed it rather than refusing."""

    _WINDOW_SECONDS = 1.0

    def __init__(
        self,
        *,
        limit_per_second: int = 1,
        clock: Callable[[], float] = time.monotonic,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        if limit_per_second <= 0:
            raise ValueError("limit_per_second must be positive")
        self.limit_per_second = limit_per_second
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
        while len(self._request_times) >= self.limit_per_second:
            oldest = self._request_times[0]
            wait_seconds = (oldest + self._WINDOW_SECONDS) - self._clock()
            if wait_seconds > 0:
                self._sleep_fn(wait_seconds)
            self._prune_expired()

    def record_request(self) -> None:
        """Must be called once for every real HTTP call actually made
        against Alpha Vantage, including one that goes on to fail."""
        self._prune_expired()
        self._request_times.append(self._clock())
