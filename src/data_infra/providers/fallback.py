"""FallbackDataProvider: Provider A -> fails -> Provider B -> fails ->
Provider C -> ..., per Phase 22 instruction section 7 (originally a
fixed 2-provider composition; ADR-0164 widened it to an ordered chain
of 2 or more, still composing other `DataProvider` implementations
(e.g. `TiingoDataProvider` -> `TwelveDataDataProvider` ->
`AlphaVantageDataProvider`) -- never a new provider identity of its
own.

**ADR-0164: nesting two `FallbackDataProvider` instances to build a
3-tier chain was tried first and rejected** -- the outer instance's
`fetch()` unconditionally overwrites `_answered_by` with its own
secondary's `metadata()["provider_id"]` (always the constant string
`"fallback"` for a nested instance), destroying the inner instance's
already-correct stamp; `normalize()`/`validate()` then strip
`_answered_by` before delegating to that nested instance, so its own
`_group_by_provider` sees no `_answered_by` at all and raises
`PermanentProviderError` on every single record -- a real, reproduced
crash, not a theoretical concern (confirmed by directly nesting two
instances against a `MockDataProvider` before this fix). Taking a
variadic list of providers instead, keyed by each REAL provider's own
id the whole way through, has no such recursion to get wrong.

**Never hides which provider actually answered.** Each raw record is
stamped with `_answered_by=<provider_id>` in `fetch()`, and `normalize()`
routes each record back to the provider that produced it, so the
resulting `PriceBar.provenance.source` is always the real provider's own
name ("tiingo"/"twelvedata"/"alphavantage"), never "fallback" -- a
caller inspecting provenance can always tell which provider a given bar
actually came from. A `data_version` computed from a non-first-tier
provider's answer is never presented as if an earlier tier had answered.

**Fallback is per-call, not "retry each tier fully before the next."**
Every call to `fetch()` independently tries each provider in order --
if `data_infra.provider.IngestionRunner`'s own retry/backoff logic
retries a transient failure, each retry attempt gets a fresh full pass
through the chain, rather than this class trying to out-guess the
Runner's own retry policy.

**No silent "success" fabrication.** If every provider in the chain
fails, `fetch()` raises `PermanentProviderError` naming all of them --
never returns an empty list or partial data presented as complete.
"""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

from data_infra.models import PriceBar
from data_infra.provider import DataProvider, PermanentProviderError, TransientProviderError


class FallbackDataProvider:
    def __init__(self, primary: DataProvider, secondary: DataProvider, *rest: DataProvider) -> None:
        # `primary`/`secondary` (not just *providers) keeps the original
        # 2-argument call shape everywhere it's already used, while
        # `*rest` extends it to any number of further fallback tiers
        # (ADR-0164) without a breaking signature change.
        self._providers: tuple[DataProvider, ...] = (primary, secondary, *rest)
        self._by_id: dict[str, DataProvider] = {
            provider.metadata()["provider_id"]: provider for provider in self._providers
        }

    def fetch(self, security_id: str, start: datetime, end: datetime) -> list[dict]:
        failures: list[tuple[str, Exception]] = []
        for provider in self._providers:
            provider_id = provider.metadata()["provider_id"]
            try:
                records = provider.fetch(security_id, start, end)
                return [dict(r, _answered_by=provider_id) for r in records]
            except (TransientProviderError, PermanentProviderError) as exc:
                failures.append((provider_id, exc))

        # Session 37 (ADR-0115, external review N-12): a failure across
        # every tier is only truly non-retryable (PermanentProviderError)
        # if EVERY tier's own failure was itself permanent -- any tier
        # reporting TransientProviderError means a retry could plausibly
        # recover, so IngestionRunner must still get that fresh chance
        # (its own docstring's "each retry attempt gets a fresh...
        # chance" promise, generalized from 2 tiers to N).
        message = f"all providers failed for {security_id}: " + "; ".join(
            f"{provider_id}={type(exc).__name__}({exc})" for provider_id, exc in failures
        )
        transient_failures = [exc for _, exc in failures if isinstance(exc, TransientProviderError)]
        if transient_failures:
            # ADR-0157: prefer whichever tier actually told us a real
            # Retry-After -- never invent one, and never silently drop a
            # real server-stated wait time just because it came from
            # re-wrapping N exceptions into one. Earlier tiers are
            # preferred only in that they are checked first; the first
            # tier with a real value wins.
            retry_after = next((exc.retry_after_seconds for exc in transient_failures if exc.retry_after_seconds is not None), None)
            raise TransientProviderError(message, retry_after_seconds=retry_after) from transient_failures[-1]
        raise PermanentProviderError(message) from failures[-1][1]

    def validate(self, raw_records: Sequence[dict]) -> list[str]:
        issues: list[str] = []
        for provider_id, group in self._group_by_provider(raw_records).items():
            stripped = [{k: v for k, v in r.items() if k != "_answered_by"} for r in group]
            issues.extend(f"[{provider_id}] {issue}" for issue in self._by_id[provider_id].validate(stripped))
        return issues

    def normalize(self, security_id: str, raw_records: Sequence[dict]) -> list[PriceBar]:
        bars: list[PriceBar] = []
        for provider_id, group in self._group_by_provider(raw_records).items():
            stripped = [{k: v for k, v in r.items() if k != "_answered_by"} for r in group]
            bars.extend(self._by_id[provider_id].normalize(security_id, stripped))
        return sorted(bars, key=lambda b: b.timestamp)

    def _group_by_provider(self, raw_records: Sequence[dict]) -> dict[str, list[dict]]:
        groups: dict[str, list[dict]] = {}
        for record in raw_records:
            provider_id = record.get("_answered_by")
            if provider_id not in self._by_id:
                raise PermanentProviderError(
                    f"raw record has no recognized _answered_by provider id: {record.get('_answered_by')!r} "
                    f"-- was this record produced by FallbackDataProvider.fetch()?"
                )
            groups.setdefault(provider_id, []).append(record)
        return groups

    def metadata(self) -> dict:
        provider_ids = [p.metadata()["provider_id"] for p in self._providers]
        return {
            "provider_id": "fallback",
            "provider_name": f"Fallback({'->'.join(provider_ids)})",
            # Kept for backward compatibility with the original
            # 2-provider shape -- always the first/second tier of the
            # full chain, even when `provider_ids` below names more than
            # two (ADR-0164).
            "primary_provider_id": provider_ids[0],
            "secondary_provider_id": provider_ids[1],
            "provider_ids": tuple(provider_ids),
            "rate_limit_per_minute": None,  # depends on which provider actually answers a given call
            "is_real_external_provider": True,
        }
