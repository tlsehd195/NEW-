"""TiingoRequestBudget: proactive, client-side tracking of Tiingo's real
account-wide rate limit -- confirmed directly against the real account
this session: 50 requests/hour (overrides the previous `"rate_limit_per_
minute": None  # UNKNOWN` placeholder in `tiingo.py::metadata()`, which
predates this confirmation). See ADR-0160.

ADR-0157 already made the retry path respect a real `Retry-After`
header instead of guessing a fixed backoff -- but a real `workflow_
dispatch` production run proved that reactive fix alone is
insufficient, and actually counterproductive, once the hourly quota is
genuinely exhausted: waiting and retrying 3x per symbol cannot refill
an account-wide hourly cap that has already been used up. It only
spends ~25 minutes failing on 88 symbols one by one instead of ~3.5
minutes failing on the 7 that could not possibly succeed either way.
The real fix is to stop calling Tiingo once the budget is known to be
exhausted, and fail fast instead of wasting a retry proving the
obvious.

**Rolling window, not a fixed-hour bucket.** Tiingo's own real quota is
naturally rolling -- each request's own hour-ago mark is when it drops
back off the account's usage, not a wall-clock hour boundary this
project would otherwise have to invent and guess the phase of. A fixed
window (e.g. "reset every hour on the hour") could under-count right
after its own reset instant even though 50 real requests genuinely
landed in the last 60 minutes -- this class tracks individual request
timestamps and prunes whatever has aged out of the trailing 3600
seconds instead.

**Deliberately instance-shared, never a module-level global.** Both
real call paths that hit Tiingo -- `TiingoDataProvider.fetch()` (used
via `FallbackDataProvider`/`IngestionRunner`) and the direct
`fetch_corporate_actions`/`fetch_symbol_metadata` calls in `scripts/
ingest_real_market_data.py` -- go through the exact same `TiingoHttp
Transport.get()` choke point. A budget owned by that transport
instance is therefore shared automatically, by construction, as long
as only one `TiingoHttpTransport` instance is built and reused --
never by threading a new parameter through every caller.
"""

from __future__ import annotations

import time
from typing import Callable, List


class TiingoRequestBudget:
    """Tracks real Tiingo HTTP calls in a rolling 1-hour window against
    the account's real cap. A `safety_margin` is reserved below the real
    cap -- exhaustion is declared once `limit_per_hour - safety_margin`
    calls are already in the window, not at the real cap itself, so
    this class's own bookkeeping (clock granularity, a request some
    other untracked path made) can never itself be what tips the real
    account over its real limit. `safety_margin=2` (48 of the real 50
    treated as the effective cap) is this project's chosen headroom --
    small enough not to waste much real quota, large enough to absorb
    an off-by-one without a real 429."""

    _WINDOW_SECONDS = 3600.0

    def __init__(
        self,
        *,
        limit_per_hour: int = 50,
        safety_margin: int = 2,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if limit_per_hour <= 0:
            raise ValueError("limit_per_hour must be positive")
        if safety_margin < 0 or safety_margin >= limit_per_hour:
            raise ValueError("safety_margin must be non-negative and less than limit_per_hour")
        self.limit_per_hour = limit_per_hour
        self.safety_margin = safety_margin
        self._effective_cap = limit_per_hour - safety_margin
        self._clock = clock
        self._request_times: List[float] = []

    def _prune_expired(self) -> None:
        # An entry is dropped once its age reaches the full window (a
        # borrowed request's own timestamp equal to the cutoff counts
        # as expired) -- a documented, explicit boundary rather than an
        # ambiguous open/closed interval choice left implicit.
        cutoff = self._clock() - self._WINDOW_SECONDS
        while self._request_times and self._request_times[0] <= cutoff:
            self._request_times.pop(0)

    def remaining(self) -> int:
        """How many more requests this budget will allow before
        `would_exceed()` turns true -- already net of `safety_margin`,
        never negative."""
        self._prune_expired()
        return max(0, self._effective_cap - len(self._request_times))

    def would_exceed(self) -> bool:
        """True once the safety-margined cap has already been reached
        by requests still inside the rolling window -- callers must
        check this BEFORE making a real HTTP call, never after."""
        return self.remaining() <= 0

    def record_request(self) -> None:
        """Must be called once for every real HTTP call actually made
        against Tiingo, including one that goes on to fail -- Tiingo's
        own server-side quota counts a request against the account
        regardless of what response it returns."""
        self._prune_expired()
        self._request_times.append(self._clock())
