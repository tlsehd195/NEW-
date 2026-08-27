"""FallbackDataProvider: Provider A -> fails -> Provider B, per Phase 22
instruction section 7. Implements `data_infra.provider.DataProvider`
by composing two other `DataProvider` implementations (e.g.
`TiingoDataProvider` primary, `StooqDataProvider` secondary) -- never a
new provider identity of its own.

**Never hides which provider actually answered.** Each raw record is
stamped with `_answered_by=<provider_id>` in `fetch()`, and `normalize()`
routes each record back to the provider that produced it, so the
resulting `PriceBar.provenance.source` is always the real provider's own
name ("tiingo"/"stooq"), never "fallback" -- a caller inspecting
provenance can always tell which provider a given bar actually came
from. A `data_version` computed from a secondary-provider fallback is
never presented as if the primary had answered.

**Fallback is per-call, not "retry A fully then try B."** Every call to
`fetch()` independently tries primary then secondary -- if
`data_infra.provider.IngestionRunner`'s own retry/backoff logic retries
a transient failure, each retry attempt gets a fresh primary-then-
secondary chance, rather than this class trying to out-guess the
Runner's own retry policy.

**No silent "success" fabrication.** If both providers fail, `fetch()`
raises `PermanentProviderError` naming both failures -- never returns
an empty list or partial data presented as complete.
"""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

from data_infra.models import PriceBar
from data_infra.provider import DataProvider, PermanentProviderError, TransientProviderError


class FallbackDataProvider:
    def __init__(self, primary: DataProvider, secondary: DataProvider) -> None:
        self._primary = primary
        self._secondary = secondary
        self._by_id: dict[str, DataProvider] = {
            primary.metadata()["provider_id"]: primary,
            secondary.metadata()["provider_id"]: secondary,
        }

    def fetch(self, security_id: str, start: datetime, end: datetime) -> list[dict]:
        primary_id = self._primary.metadata()["provider_id"]
        try:
            records = self._primary.fetch(security_id, start, end)
            return [dict(r, _answered_by=primary_id) for r in records]
        except (TransientProviderError, PermanentProviderError) as primary_exc:
            secondary_id = self._secondary.metadata()["provider_id"]
            try:
                records = self._secondary.fetch(security_id, start, end)
                return [dict(r, _answered_by=secondary_id) for r in records]
            except (TransientProviderError, PermanentProviderError) as secondary_exc:
                raise PermanentProviderError(
                    f"both providers failed for {security_id}: "
                    f"{primary_id}={type(primary_exc).__name__}({primary_exc}); "
                    f"{secondary_id}={type(secondary_exc).__name__}({secondary_exc})"
                ) from secondary_exc

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

    def metadata(self) -> dict:
        primary_meta = self._primary.metadata()
        secondary_meta = self._secondary.metadata()
        return {
            "provider_id": "fallback",
            "provider_name": f"Fallback({primary_meta['provider_id']}->{secondary_meta['provider_id']})",
            "primary_provider_id": primary_meta["provider_id"],
            "secondary_provider_id": secondary_meta["provider_id"],
            "rate_limit_per_minute": None,  # depends on which provider actually answers a given call
            "is_real_external_provider": True,
        }
