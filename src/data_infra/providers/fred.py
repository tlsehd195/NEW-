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
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Optional

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
from data_infra.providers.fred_transport import ALFRED_REALTIME_END, ALFRED_REALTIME_START, FredHttpTransport

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


# FRED's own max `limit` per observations page / vintage-dates page.
_VINTAGE_PAGE_LIMIT = 100_000
_VINTAGE_DATES_PAGE_LIMIT = 10_000
# FRED's own cap is 2000 vintage dates per real-time window; stay under it.
_VINTAGES_PER_WINDOW = 1_500


def _realtime_windows(vintage_dates: list[date]) -> list[tuple[str, str]]:
    """Contiguous real-time windows covering every vintage date, each
    holding at most `_VINTAGES_PER_WINDOW` of them. One window with FRED's
    whole-range sentinels when the series is short enough (or FRED
    listed no vintage dates at all)."""
    if len(vintage_dates) <= _VINTAGES_PER_WINDOW:
        return [(ALFRED_REALTIME_START, ALFRED_REALTIME_END)]
    starts = vintage_dates[::_VINTAGES_PER_WINDOW]
    windows: list[tuple[str, str]] = []
    for i, window_start in enumerate(starts):
        lower = ALFRED_REALTIME_START if i == 0 else window_start.isoformat()
        upper = ALFRED_REALTIME_END if i == len(starts) - 1 else (starts[i + 1] - timedelta(days=1)).isoformat()
        windows.append((lower, upper))
    return windows


def _merge_window_splits(rows: list[FredVintageObservation]) -> list[FredVintageObservation]:
    """Joins the pieces one value is cut into at window boundaries: same
    observation date and value, the next piece starting the day after
    the previous one ends (or an exact duplicate). Different values are
    real revisions and stay separate rows."""
    ordered = sorted(rows, key=lambda r: (r.observation_date, r.realtime_start))
    merged: list[FredVintageObservation] = []
    for row in ordered:
        prev = merged[-1] if merged else None
        if prev is not None and prev.observation_date == row.observation_date and prev.value == row.value and (
            prev.realtime_start == row.realtime_start
            or (prev.realtime_end is not None and prev.realtime_end + timedelta(days=1) == row.realtime_start)
        ):
            merged[-1] = FredVintageObservation(
                series_id=prev.series_id,
                observation_date=prev.observation_date,
                value=prev.value,
                realtime_start=prev.realtime_start,
                realtime_end=row.realtime_end if prev.realtime_start != row.realtime_start else (
                    None if prev.realtime_end is None or row.realtime_end is None
                    else max(prev.realtime_end, row.realtime_end)
                ),
                retrieved_at=prev.retrieved_at,
            )
            continue
        merged.append(row)
    return merged


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

    def fetch_series_vintages(
        self, series_id: str, start: date, end: date, *, progress: Optional[Callable[[str], None]] = None,
    ) -> list[FredVintageObservation]:
        """Every vintage (ALFRED) of every observation of `series_id`
        with `start <= observation_date <= end`.

        FRED refuses a real-time window with more than 2000 vintage
        dates, which every daily series exceeds. The series' vintage
        dates are therefore read first and split into contiguous windows
        of at most `_VINTAGES_PER_WINDOW` each (window i ends the day
        before window i+1 starts, so no real-time day is skipped).
        A value that spans a window boundary comes back once per window;
        `_merge_window_splits` joins those pieces back into one row."""
        if end < start:
            raise ValueError(f"end ({end}) must not be before start ({start})")
        api_key = resolve_api_key(self._config)
        retrieved_at = datetime.now(timezone.utc)
        vintage_dates = self._fetch_vintage_dates(series_id, api_key)
        windows = _realtime_windows(vintage_dates)
        if progress is not None:
            progress(f"{series_id}: {len(vintage_dates)} vintage dates, {len(windows)} real-time window(s)")
        rows: list[FredVintageObservation] = []
        for i, (realtime_start, realtime_end) in enumerate(windows, start=1):
            window_rows = self._fetch_vintage_window(
                series_id, api_key, start, end, realtime_start, realtime_end, retrieved_at
            )
            rows.extend(window_rows)
            if progress is not None:
                progress(f"{series_id}: window {i}/{len(windows)} {realtime_start}..{realtime_end}: {len(window_rows)} rows")
        return _merge_window_splits(rows)

    def fetch_series_first_releases(
        self, series_id: str, start: date, end: date, *, progress: Optional[Callable[[str], None]] = None,
    ) -> list[FredVintageObservation]:
        """Only the first print of each observation (ALFRED
        `output_type=4`, "initial release only"), each with the
        `realtime_start` it was first published on. `realtime_end` is
        dropped (stored as `None`): the store then holds one vintage per
        observation, so a point-in-time read returns the first print
        forever, never a later revision -- stale but never look-ahead.
        FRED's documentation does not spell out this response's shape;
        a row without `realtime_start` fails loudly rather than being
        stamped with a guessed date."""
        if end < start:
            raise ValueError(f"end ({end}) must not be before start ({start})")
        api_key = resolve_api_key(self._config)
        rows = self._fetch_vintage_window(
            series_id, api_key, start, end, ALFRED_REALTIME_START, ALFRED_REALTIME_END,
            datetime.now(timezone.utc), output_type="4",
        )
        if progress is not None:
            progress(f"{series_id}: {len(rows)} first-release rows")
        return [
            FredVintageObservation(r.series_id, r.observation_date, r.value, r.realtime_start, None, r.retrieved_at)
            for r in rows
        ]

    def _fetch_vintage_dates(self, series_id: str, api_key: str) -> list[date]:
        dates: list[date] = []
        offset = 0
        while True:
            response = self._transport.get_series_vintage_dates(
                series_id=series_id, api_key=api_key, offset=offset, limit=_VINTAGE_DATES_PAGE_LIMIT,
                timeout=self._config.vintage_timeout_seconds,
            )
            body = response.body
            if not isinstance(body, dict) or not isinstance(body.get("vintage_dates"), list):
                raise PermanentProviderError(
                    f"unexpected FRED vintage-dates response shape for series {series_id!r}: {body!r}"
                )
            page = body["vintage_dates"]
            dates.extend(_parse_observation_date(raw, series_id=series_id) for raw in page)
            offset += len(page)
            count = body.get("count")
            if not page or (isinstance(count, int) and offset >= count) or (
                not isinstance(count, int) and len(page) < _VINTAGE_DATES_PAGE_LIMIT
            ):
                return sorted(set(dates))

    def _fetch_vintage_window(
        self, series_id: str, api_key: str, start: date, end: date,
        realtime_start: str, realtime_end: str, retrieved_at: datetime, output_type: str = "1",
    ) -> list[FredVintageObservation]:
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
                timeout=self._config.vintage_timeout_seconds,
                realtime_start=realtime_start,
                realtime_end=realtime_end,
                output_type=output_type,
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
