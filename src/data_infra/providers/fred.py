"""FredMacroProvider: a real (not mock) adapter for FRED (Federal
Reserve Economic Data, https://fred.stlouisfed.org), the standard public
source for US macro/rates series (e.g. the 3-month Treasury rate,
DGS3MO) this project has never had a data source for -- see
`src/counterfactual/counterfactual.py`'s own docstring ("This system has
no risk-free-rate data source anywhere") and
`src/broker/paper/performance.py`'s `PaperPerformanceConfig.
risk_free_rate` (both default `0.0`, an explicit, disclosed assumption,
not a bug).

**Scope of this module, and what it deliberately does NOT do yet**: this
is the "adopt now, wire in later" step (ADR-0151's own precedent, applied
here the same way ADR-0206 applied it to the Gemini adapter before any
real predictor called it). It makes FRED data fetchable, real, and
tested. It does NOT change `risk_free_rate`'s `0.0` default anywhere,
and nothing in `backtest`/`broker`/`counterfactual`/`evolution` imports
this module. Replacing that disclosed `0.0` assumption with a real
FRED-sourced rate touches many already-shipped call sites and would
silently change every future Sharpe/Sortino/DSR/counterfactual-cash-
baseline number this project reports from that point on -- exactly the
kind of consequential, cross-cutting decision this project's own
discipline (ADR-0151, the Grounding Gate wiring deferral in CLAUDE.md)
requires making deliberately and explicitly, not as a side effect of
adding a data source. See ADR-0208 for the full reasoning and the
decision to defer it.

Not a `data_infra.provider.DataProvider` -- that Protocol's shape
(`fetch`/`validate`/`normalize` returning per-`security_id` `PriceBar`
rows) is OHLCV-specific and does not fit a macro time series keyed by
`series_id` alone, with no `security_id` concept at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional

from data_infra.macro_models import (
    MacroObservationRecord,
    date_to_utc_midnight,
    macro_record_id,
    vintage_available_time,
)
from data_infra.models import Provenance
from data_infra.provider import PermanentProviderError
from data_infra.providers.fred_auth import resolve_api_key
from data_infra.providers.fred_config import FredConfig
from data_infra.providers.fred_transport import ALFRED_REALTIME_END, FredHttpTransport

# FRED's own documented convention (this module's transport docstring,
# point 1): a missing/unavailable observation's "value" is this literal
# string, never absent/null/empty.
_MISSING_VALUE_MARKER = "."


@dataclass(frozen=True)
class FredObservation:
    series_id: str
    observation_date: date
    value: Optional[float]  # None when FRED reports "." (no data for that date)
    retrieved_at: datetime


# FRED's own max `limit` per observations page.
_VINTAGE_PAGE_LIMIT = 100_000


@dataclass(frozen=True)
class FredVintageObservation:
    """One ALFRED row: the `value` FRED published for `observation_date`
    during the real-time period `[realtime_start, realtime_end]`.
    `realtime_start` is the date that value first appeared (the release
    or revision date); `realtime_end` is `None` while the value is still
    current (FRED's `9999-12-31` sentinel)."""

    series_id: str
    observation_date: date
    value: Optional[float]
    realtime_start: date
    realtime_end: Optional[date]
    retrieved_at: datetime


def _parse_observation_date(raw: str, *, series_id: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise PermanentProviderError(
            f"FRED returned an unparseable observation date {raw!r} for series {series_id!r}"
        ) from exc


def _parse_value(raw: object, *, series_id: str) -> Optional[float]:
    if raw == _MISSING_VALUE_MARKER:
        return None
    if not isinstance(raw, str):
        raise PermanentProviderError(
            f"FRED returned a non-string observation value {raw!r} for series {series_id!r}"
        )
    try:
        return float(raw)
    except ValueError as exc:
        raise PermanentProviderError(
            f"FRED returned an unparseable observation value {raw!r} for series {series_id!r}"
        ) from exc


class FredMacroProvider:
    def __init__(self, config: FredConfig, transport: FredHttpTransport) -> None:
        self._config = config
        self._transport = transport

    def fetch_series(self, series_id: str, start: date, end: date) -> list[FredObservation]:
        if end < start:
            raise ValueError(f"end ({end}) must not be before start ({start})")
        api_key = resolve_api_key(self._config)
        response = self._transport.get_series_observations(
            series_id=series_id,
            api_key=api_key,
            observation_start=start.isoformat(),
            observation_end=end.isoformat(),
            timeout=self._config.timeout_seconds,
        )
        if not isinstance(response.body, dict) or not isinstance(response.body.get("observations"), list):
            raise PermanentProviderError(
                f"unexpected FRED response shape for series {series_id!r}: {response.body!r}"
            )
        retrieved_at = datetime.now(timezone.utc)
        observations: list[FredObservation] = []
        for raw in response.body["observations"]:
            if not isinstance(raw, dict) or "date" not in raw or "value" not in raw:
                raise PermanentProviderError(
                    f"unexpected FRED observation shape for series {series_id!r}: {raw!r}"
                )
            observations.append(
                FredObservation(
                    series_id=series_id,
                    observation_date=_parse_observation_date(raw["date"], series_id=series_id),
                    value=_parse_value(raw["value"], series_id=series_id),
                    retrieved_at=retrieved_at,
                )
            )
        return observations

    def fetch_series_vintages(self, series_id: str, start: date, end: date) -> list[FredVintageObservation]:
        """Every vintage (ALFRED) of every observation of `series_id`
        with `start <= observation_date <= end`, following FRED's
        `count`/`offset` paging until all rows are read."""
        if end < start:
            raise ValueError(f"end ({end}) must not be before start ({start})")
        api_key = resolve_api_key(self._config)
        retrieved_at = datetime.now(timezone.utc)
        rows: list[FredVintageObservation] = []
        offset = 0
        while True:
            response = self._transport.get_series_vintage_observations(
                series_id=series_id,
                api_key=api_key,
                observation_start=start.isoformat(),
                observation_end=end.isoformat(),
                offset=offset,
                limit=_VINTAGE_PAGE_LIMIT,
                timeout=self._config.timeout_seconds,
            )
            body = response.body
            if not isinstance(body, dict) or not isinstance(body.get("observations"), list):
                raise PermanentProviderError(
                    f"unexpected FRED vintage response shape for series {series_id!r}: {body!r}"
                )
            page = body["observations"]
            for raw in page:
                if not isinstance(raw, dict) or not {"date", "value", "realtime_start", "realtime_end"} <= raw.keys():
                    raise PermanentProviderError(
                        f"unexpected FRED vintage observation shape for series {series_id!r}: {raw!r}"
                    )
                realtime_end_raw = raw["realtime_end"]
                rows.append(
                    FredVintageObservation(
                        series_id=series_id,
                        observation_date=_parse_observation_date(raw["date"], series_id=series_id),
                        value=_parse_value(raw["value"], series_id=series_id),
                        realtime_start=_parse_observation_date(raw["realtime_start"], series_id=series_id),
                        realtime_end=(
                            None if realtime_end_raw == ALFRED_REALTIME_END
                            else _parse_observation_date(realtime_end_raw, series_id=series_id)
                        ),
                        retrieved_at=retrieved_at,
                    )
                )
            offset += len(page)
            count = body.get("count")
            if not page:
                return rows
            if isinstance(count, int):
                if offset >= count:
                    return rows
            elif len(page) < _VINTAGE_PAGE_LIMIT:
                return rows

    def metadata(self) -> dict:
        return {
            "provider_id": self._config.provider_id,
            "provider_name": "FRED (Federal Reserve Economic Data)",
            "is_real_external_provider": True,
        }


ALFRED_DATA_VERSION = "alfred_vintage_v1"


def vintage_to_macro_record(obs: FredVintageObservation, *, ingestion_time: datetime) -> MacroObservationRecord:
    """Stores one ALFRED row as a `MacroObservationRecord`, with
    `available_time` from `realtime_start` (never `observation_date`) --
    see `data_infra.macro_models`' own docstring."""
    record_id = macro_record_id("fred", obs.series_id, obs.observation_date, obs.realtime_start)
    return MacroObservationRecord(
        series_id=obs.series_id,
        observation_date=date_to_utc_midnight(obs.observation_date),
        value=obs.value,
        realtime_start=date_to_utc_midnight(obs.realtime_start),
        realtime_end=None if obs.realtime_end is None else date_to_utc_midnight(obs.realtime_end),
        available_time=vintage_available_time(obs.realtime_start),
        ingestion_time=ingestion_time,
        provenance=Provenance(
            source="fred",
            source_dataset=f"alfred:{obs.series_id}",
            source_record_id=record_id,
            retrieved_at=obs.retrieved_at,
            data_version=ALFRED_DATA_VERSION,
        ),
    )
