"""RpmAdmissionGate: evenly-spaced requests-per-minute admission control.

Batch K (EXTERNAL_REPO_APPLICABILITY_REPORT.md, priority-5 recommendation):
an independent reimplementation of the pacing idea in ByteDance DeerFlow's
`models/request_admission.py` (MIT license) -- not a copy of that file
(this project stays dependency-free in `src/`; DeerFlow's own version
subclasses `langchain_core`'s `BaseRateLimiter`), but the same evenly-
spaced, no-burst-on-idle admission policy, rebuilt in this project's own
clock-injected style.

`ai_gateway.config.ProviderConfig.rpm_limit`/`tpm_limit` have existed
since Phase 12 but nothing in this codebase has ever enforced them --
`ai_gateway.provider.MockProviderAdapter.get_limits()` only reports the
configured value back to a caller that asks. This module is that missing
enforcement, added standing alone and independently tested here.

**Deliberately NOT wired into `AIGateway`/`ProviderSelector` yet.** This
phase ships only `MockProviderAdapter`, which makes no real network call
and therefore cannot be rate-limited by a live provider's own servers in
the first place -- wiring an admission gate into the routing pipeline
has no real traffic to protect until a real provider adapter exists.
Adding the capability now, verified independently, follows this
project's own `ADR-0151` "adopt now, wire in later" precedent for
skfolio/purgedcv/exchange_calendars: clearing a component for use is a
different decision from integrating it into a specific pipeline stage,
and the latter is separate, scheduled follow-up work once a real
provider adapter's own actual traffic needs pacing.

**Evenly spaced, not a token bucket: idle time never accumulates burst
allowance.** A provider that admits nothing for an hour is not then
permitted to send `rpm_limit` requests in the same second -- every
admission must be spaced at least `60 / rpm_limit` seconds after the
previous one, computed purely from caller-supplied timestamps. Like
`backtest.clock.BacktestClock` and `ai_gateway.quota_manager.
QuotaManager`, this module never calls `datetime.now()`/`datetime.
utcnow()` itself; the caller supplies every timestamp it reads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional


@dataclass(frozen=True)
class AdmissionDecision:
    admitted: bool
    # When this same request could be retried; always None when
    # `admitted` is True or no `rpm_limit` is configured (nothing to
    # retry against).
    retry_after: Optional[datetime]


class RpmAdmissionGate:
    """One gate per provider (construct one per `provider_id`, matching
    `QuotaManager`'s own per-provider state granularity). Call
    `evaluate(at=...)` before attempting a request; if the decision is
    admitted, call `record_admission(at=...)` only once the caller
    actually proceeds with that attempt -- a caller that decides not to
    proceed after all must not record it, mirroring the "a recorded
    state change reflects something that actually happened" discipline
    `QuotaManager`'s own append-only history already established."""

    def __init__(self, rpm_limit: Optional[int]) -> None:
        if rpm_limit is not None and rpm_limit <= 0:
            raise ValueError(f"rpm_limit must be positive when configured, got {rpm_limit!r}")
        self._min_interval: Optional[timedelta] = (
            None if rpm_limit is None else timedelta(seconds=60.0 / rpm_limit)
        )
        self._last_admitted_at: Optional[datetime] = None

    def evaluate(self, *, at: datetime) -> AdmissionDecision:
        if self._min_interval is None or self._last_admitted_at is None:
            return AdmissionDecision(admitted=True, retry_after=None)
        earliest_next = self._last_admitted_at + self._min_interval
        if at >= earliest_next:
            return AdmissionDecision(admitted=True, retry_after=None)
        return AdmissionDecision(admitted=False, retry_after=earliest_next)

    def record_admission(self, *, at: datetime) -> None:
        if self._last_admitted_at is not None and at < self._last_admitted_at:
            raise ValueError(
                f"record_admission called with at={at!r} before the last recorded "
                f"admission at {self._last_admitted_at!r} -- caller-supplied "
                "timestamps must be monotonically non-decreasing"
            )
        self._last_admitted_at = at
