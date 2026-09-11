"""TiingoDataProvider: a real (not mock) `data_infra.provider.DataProvider`
implementation for US equity daily OHLCV, plus split/dividend corporate
action fetching (an addition beyond the `DataProvider` Protocol itself
-- see the module docstring on that distinction below).

See docs/decisions/ADR-0025-market-data-provider-selection.md and
docs/operations/MARKET-DATA-PROVIDER.md.

**Honesty about evidence tier**: this implementation is built against
Tier 2 (secondary-source) documentation of Tiingo's long-stable, widely
publicly documented EOD price and corporate-action API shape -- it has
never been exercised against a live Tiingo response in this
environment (network access to `api.tiingo.com` is blocked here; see
ADR-0025). Every parsing assumption lives in `normalize()`/
`normalize_corporate_actions()` alone, so it can be corrected in one
place once real verification is possible, mirroring exactly how
`broker.toss.mapping` isolated Toss's own unverified assumptions in
Phase 13.

**Why this module has two more methods than `DataProvider` requires**:
`data_infra.provider.DataProvider`'s Protocol (`fetch`/`validate`/
`normalize`/`metadata`) is scoped to price bars alone (Phase 1 never
needed corporate-action fetching from a *provider* -- Phase 1's own
mock dataset supplied `CorporateAction` records directly). Rather than
widen that shared Protocol (which every other `DataProvider`
implementation, including `MockDataProvider`, would then need to
satisfy, a change well outside this phase's additive-only scope), this
class adds `fetch_corporate_actions`/`normalize_corporate_actions` as
extra methods a caller can use directly -- `IngestionRunner` (Phase 1,
unmodified) still only ever calls the four Protocol methods.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from data_infra.enums import CorporateActionType
from data_infra.models import CorporateAction, PriceBar, Provenance
from data_infra.provider import PermanentProviderError, bar_available_time, clamp_ingestion_time
from data_infra.providers.tiingo_auth import resolve_api_key
from data_infra.providers.tiingo_config import TiingoConfig
from data_infra.providers.tiingo_transport import TiingoHttpTransport, TiingoTransportResponse
from data_infra.versioning import compute_data_version

_DAILY_PRICES_PATH_TEMPLATE = "/tiingo/daily/{ticker}/prices"
_ACTIONS_PATH_TEMPLATE = "/tiingo/daily/{ticker}/prices"  # Tiingo's EOD endpoint carries split/dividend fields inline per row (Tier 2 documentation); see normalize_corporate_actions
_METADATA_PATH_TEMPLATE = "/tiingo/daily/{ticker}"  # the symbol-metadata endpoint (no /prices suffix, no date range) -- see fetch_symbol_metadata

_REQUIRED_RAW_FIELDS = ("date", "open", "high", "low", "close", "volume")


class TiingoDataProvider:
    """Implements `data_infra.provider.DataProvider` for real (not
    mock) Tiingo EOD data. `retrieved_at`/`ingestion_time` must always
    be supplied explicitly by the caller (never `datetime.now()`/
    `datetime.utcnow()` -- instruction section 13)."""

    def __init__(self, config: TiingoConfig, transport: TiingoHttpTransport) -> None:
        self._config = config
        self._transport = transport

    def _auth_params(self) -> dict[str, str]:
        # Tiingo authenticates via a `token` query parameter, not a
        # bearer header (Tier 2 documentation) -- resolved once per
        # call, never cached/logged, mirroring broker.toss.auth's
        # "resolve transiently, never persist" discipline.
        api_key = resolve_api_key(self._config)
        return {"token": api_key, "format": "json"}

    # -- DataProvider Protocol --------------------------------------

    def fetch(self, security_id: str, start: datetime, end: datetime) -> list[dict]:
        params = dict(self._auth_params())
        params["startDate"] = start.date().isoformat()
        params["endDate"] = end.date().isoformat()
        response = self._transport.get(
            _DAILY_PRICES_PATH_TEMPLATE.format(ticker=security_id),
            params=params,
            timeout=self._config.timeout_seconds,
        )
        if not isinstance(response.body, list):
            raise PermanentProviderError(
                f"unexpected Tiingo response shape for {security_id}: expected a JSON array"
            )
        # `end` -- the caller's own explicit as-of instant for this whole
        # ingestion call (never datetime.now()/utcnow()) -- is stamped
        # onto each raw record here, so normalize() (whose signature the
        # DataProvider Protocol fixes at exactly (security_id,
        # raw_records), matching IngestionRunner's own call site) can
        # read it back without a wall-clock call or a Protocol change.
        # Mirrors MockDataProvider.normalize()'s identical
        # `record.get("retrieved_at", ...)` pattern.
        return [dict(row, security_id=security_id, _fetched_as_of=end) for row in response.body]

    def validate(self, raw_records: Sequence[dict]) -> list[str]:
        issues: list[str] = []
        for i, record in enumerate(raw_records):
            missing = [f for f in _REQUIRED_RAW_FIELDS if f not in record]
            if missing:
                issues.append(f"record[{i}] missing fields: {missing}")
        return issues

    def normalize(self, security_id: str, raw_records: Sequence[dict]) -> list[PriceBar]:
        """Matches the `DataProvider` Protocol's exact 2-argument
        signature (`IngestionRunner` calls it that way) -- `retrieved_at`/
        `ingestion_time` are read back from `_fetched_as_of`, which
        `fetch()` already stamped onto each record from the caller's own
        explicit `end` parameter (never `datetime.now()`/`utcnow()`
        here, point-in-time discipline instruction section 13)."""
        bars: list[PriceBar] = []
        for record in raw_records:
            timestamp = _parse_tiingo_date(record["date"])
            as_of = record["_fetched_as_of"]
            # data_version must reflect only the actual fetched content
            # -- excluding the caller-supplied `_fetched_as_of`/
            # `security_id` keys this module injected in fetch() keeps
            # re-ingesting the identical real-world bar on a later run
            # (with a different `end`) idempotent, matching
            # IngestionRunner's own (security_id, timestamp, source,
            # data_version) dedup key (Phase 1 spec section 25).
            content_fields = {k: v for k, v in record.items() if k not in ("_fetched_as_of", "security_id")}
            provenance = Provenance(
                source="tiingo",
                source_dataset=f"tiingo_eod_{security_id}",
                source_record_id=f"{security_id}:{record['date']}",
                retrieved_at=as_of,
                data_version=compute_data_version(content_fields),
            )
            bars.append(
                PriceBar(
                    security_id=security_id,
                    timestamp=timestamp,
                    open=float(record["open"]),
                    high=float(record["high"]),
                    low=float(record["low"]),
                    close=float(record["close"]),
                    volume=float(record["volume"]),
                    # Session 36 continued (external review remediation):
                    # was `timestamp` (this bar's own event date, midnight
                    # UTC) -- see `data_infra.provider.bar_available_time`'s
                    # own docstring for why an intraday as-of query made
                    # before real market close needs this, not the bare
                    # event date, to avoid seeing the day's own not-yet-
                    # final close early.
                    available_time=bar_available_time(timestamp),
                    # Session 37 (ADR-0115, external review N-3): clamped
                    # -- see `data_infra.provider.clamp_ingestion_time`'s
                    # own docstring for why the batch-level `as_of` can
                    # otherwise fall before this bar's own available_time
                    # for a month-end/current-day bar.
                    ingestion_time=clamp_ingestion_time(as_of, bar_available_time(timestamp)),
                    provenance=provenance,
                    # adjClose is a Tiingo-computed, split/dividend-adjusted
                    # value -- kept as the *optional*, separate
                    # `adjusted_close` field, never substituted for the
                    # raw `close` above (ADR-0004 / this project's
                    # point-in-time discipline: raw OHLCV is the record
                    # of truth, adjustment is a derived, optional view).
                    adjusted_close=float(record["adjClose"]) if record.get("adjClose") is not None else None,
                    # Session 36 continued addition -- Tiingo's EOD
                    # response already carries `adjHigh`/`adjLow`
                    # alongside `adjClose` (same response already
                    # fetched above, zero new network requests), simply
                    # never parsed by any earlier field on this model.
                    # Same "separate optional field, never substituted
                    # for the raw value" discipline as `adjusted_close`.
                    adjusted_high=float(record["adjHigh"]) if record.get("adjHigh") is not None else None,
                    adjusted_low=float(record["adjLow"]) if record.get("adjLow") is not None else None,
                    currency="USD",
                )
            )
        return bars

    def metadata(self) -> dict:
        return {
            "provider_id": self._config.provider_id,
            "provider_name": "Tiingo",
            "rate_limit_per_minute": None,  # UNKNOWN -- see ADR-0025, not asserted without Tier 1 confirmation
            "is_real_external_provider": True,
            "configuration_version": self._config.configuration_version(),
        }

    # -- Corporate actions (extra, not part of the DataProvider Protocol) --

    def fetch_corporate_actions(self, security_id: str, start: datetime, end: datetime) -> list[dict]:
        """Reuses the same EOD endpoint -- Tier 2 documentation
        describes Tiingo's daily-prices rows as carrying `splitFactor`/
        `divCash` fields inline per date, rather than a separate
        actions endpoint. This is recorded as an explicit, isolated
        assumption (see the module docstring's "Honesty about evidence
        tier") -- a future session with real access must confirm or
        correct it."""
        params = dict(self._auth_params())
        params["startDate"] = start.date().isoformat()
        params["endDate"] = end.date().isoformat()
        response = self._transport.get(
            _ACTIONS_PATH_TEMPLATE.format(ticker=security_id),
            params=params,
            timeout=self._config.timeout_seconds,
        )
        if not isinstance(response.body, list):
            raise PermanentProviderError(
                f"unexpected Tiingo response shape for {security_id}: expected a JSON array"
            )
        return [dict(row, security_id=security_id) for row in response.body]

    def normalize_corporate_actions(
        self, security_id: str, raw_records: Sequence[dict], *, retrieved_at: datetime, ingestion_time: datetime,
    ) -> list[CorporateAction]:
        """A `splitFactor` != 1.0 becomes a SPLIT/REVERSE_SPLIT event;
        a `divCash` > 0 becomes a DIVIDEND event. Never fabricates an
        event for a row with neither -- most rows produce zero
        `CorporateAction` records, which is the honest, expected
        common case."""
        actions: list[CorporateAction] = []
        for record in raw_records:
            event_date = _parse_tiingo_date(record["date"])
            split_factor = record.get("splitFactor")
            if split_factor is not None and float(split_factor) != 1.0:
                ratio = float(split_factor)
                action_type = CorporateActionType.SPLIT if ratio > 1.0 else CorporateActionType.REVERSE_SPLIT
                actions.append(
                    CorporateAction(
                        security_id=security_id,
                        action_type=action_type,
                        # available_time = when OUR system could have known
                        # about this (PHASE-1-data-infrastructure.md section
                        # 7 / ADR-0004) -- Tiingo's EOD feed only reports
                        # splitFactor/divCash on ingestion, so that is
                        # ingestion_time, never the (possibly much earlier)
                        # event/effective date itself. Backdating this to
                        # event_date would make a late-discovered action
                        # falsely visible to an as-of query made before we
                        # actually knew about it -- exactly the leak
                        # tests/integration/test_market_data_point_in_time.py
                        # exists to catch.
                        available_time=ingestion_time,
                        ingestion_time=ingestion_time,
                        provenance=Provenance(
                            source="tiingo", source_dataset=f"tiingo_eod_{security_id}",
                            source_record_id=f"{security_id}:{record['date']}:split",
                            retrieved_at=retrieved_at,
                            data_version=compute_data_version({"date": record["date"], "splitFactor": split_factor}),
                        ),
                        event_time=event_date,
                        effective_time=event_date,
                        details={"ratio": ratio},
                    )
                )
            div_cash = record.get("divCash")
            if div_cash is not None and float(div_cash) > 0.0:
                actions.append(
                    CorporateAction(
                        security_id=security_id,
                        action_type=CorporateActionType.DIVIDEND,
                        # Session 36 continued (external review
                        # remediation): was `event_date` -- the exact
                        # leak the SPLIT branch immediately above this
                        # one already documents and avoids. Tiingo's EOD
                        # feed only reports divCash on ingestion, same as
                        # splitFactor; backdating to event_date (the
                        # ex-dividend date) made a late-discovered
                        # dividend falsely visible to an as-of query made
                        # before this system had actually ingested it,
                        # most exploitable on a backfill of older history.
                        available_time=ingestion_time,
                        ingestion_time=ingestion_time,
                        provenance=Provenance(
                            source="tiingo", source_dataset=f"tiingo_eod_{security_id}",
                            source_record_id=f"{security_id}:{record['date']}:dividend",
                            retrieved_at=retrieved_at,
                            data_version=compute_data_version({"date": record["date"], "divCash": div_cash}),
                        ),
                        event_time=event_date,
                        effective_time=event_date,
                        details={"amount": float(div_cash), "currency": "USD"},
                    )
                )
        return actions


    # -- Symbol metadata (extra, Phase 29, not part of the DataProvider
    # Protocol) -- groundwork for broad-universe discovery (instruction
    # section 15 Stage 1: "provider가 실제로 제공하는 metadata 전체에서
    # 미국 equity 후보 목록을 확보"). Never exercised against a live
    # Tiingo response in this environment (see this module's own
    # "Honesty about evidence tier" docstring) -- every field name below
    # is a Tier 2 documentation assumption, isolated in these two
    # methods alone so it can be corrected in one place once real
    # verification is possible, exactly mirroring how
    # fetch_corporate_actions/normalize_corporate_actions isolate their
    # own Tier 2 assumptions.

    def fetch_symbol_metadata(self, security_id: str) -> dict:
        """Tier 2 documentation: `GET /tiingo/daily/<ticker>` (no date
        range params, unlike the EOD/corporate-action endpoints above)
        returns a single JSON object describing the symbol itself --
        `ticker`, `name`, `exchangeCode`, `startDate`, `endDate`,
        `description` -- rather than a list of daily rows."""
        response = self._transport.get(
            _METADATA_PATH_TEMPLATE.format(ticker=security_id),
            params=dict(self._auth_params()),
            timeout=self._config.timeout_seconds,
        )
        if not isinstance(response.body, dict):
            raise PermanentProviderError(
                f"unexpected Tiingo response shape for {security_id} metadata: expected a JSON object"
            )
        return dict(response.body, security_id=security_id)

    def normalize_symbol_metadata(self, security_id: str, raw: dict) -> "SymbolMetadata":
        """Maps only the fields Tier 2 documentation actually names --
        `sector`/`market_cap_bucket` are never populated from this
        endpoint (not part of its documented shape), left `None` per
        this project's honesty discipline (never guess a value a
        provider does not actually supply). `listed_to` stays `None`
        (still active) unless Tiingo's own `endDate` is present and
        non-null -- never inferred from anything else."""
        from data_infra.universe import SymbolMetadata  # local import: avoids a module-level

        # providers -> universe dependency for every other use of this file.
        end_date = raw.get("endDate")
        return SymbolMetadata(
            symbol=security_id,
            exchange=raw.get("exchangeCode") or None,
            listed_from=_parse_tiingo_date(raw["startDate"]) if raw.get("startDate") else None,
            listed_to=_parse_tiingo_date(end_date) if end_date else None,
            source="tiingo",
        )


def _parse_tiingo_date(raw: str) -> datetime:
    """Tiingo dates are ISO 8601 (Tier 2 documentation), e.g.
    `"2024-01-02T00:00:00.000Z"` -- always UTC, always timezone-aware
    once parsed (this project never stores a naive datetime)."""
    text = raw.replace("Z", "+00:00")
    return datetime.fromisoformat(text)
