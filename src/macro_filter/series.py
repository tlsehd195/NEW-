"""In-memory point-in-time view of one macro series (ADR-0220).

`DuckDBMacroRepository.get_series_as_of` answers one as-of query per SQL
call; a 20-year daily backtest asks thousands of them, so the filter
loads each series' vintages once and answers as-of reads here, with the
same rules: per observation date, the latest vintage already known at
`as_of`; FRED "." values and withdrawn observations are skipped.

One addition, the ADR-0217 stage-2 fallback: for a series that is never
revised (`MacroSeriesSpec.revised is False`), an observation OLDER than
the series' first archived vintage is treated as known `lag` days after
its observation date instead of on that first vintage date (ALFRED
stamps every pre-archive observation with the first vintage, which made
yields invisible before 2005 and VIX before 2010). The lag is the
series' maximum observed release lag, so the rule is never earlier than
the vintage era's own worst case.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable, Optional, Sequence

from data_infra.macro_models import MACRO_SERIES_BY_ID, MacroObservationRecord, vintage_available_time


@dataclass(frozen=True)
class _Vintage:
    realtime_start: date
    value: Optional[float]
    known_at: datetime
    # When the vintage's end (FRED withdrew it with no successor) became
    # known; None while it is still current.
    end_known_at: Optional[datetime]


class PointInTimeMacroSeries:
    def __init__(
        self,
        series_id: str,
        records: Iterable[MacroObservationRecord],
        *,
        fallback_lag_days: Optional[int] = None,
    ) -> None:
        records = list(records)
        spec = MACRO_SERIES_BY_ID.get(series_id)
        if fallback_lag_days is not None and (spec is None or spec.revised):
            raise ValueError(f"{series_id}: the fallback lag is only allowed for never-revised series")
        if fallback_lag_days is not None and fallback_lag_days < 0:
            raise ValueError("fallback_lag_days must be >= 0")
        self.series_id = series_id
        self.first_vintage_date: Optional[date] = (
            min(r.realtime_start for r in records).date() if records else None
        )
        by_date: dict[date, list[_Vintage]] = {}
        for r in records:
            if r.series_id != series_id:
                raise ValueError(f"record for {r.series_id} passed to {series_id}")
            obs_date = r.observation_date.date()
            start = r.realtime_start.date()
            known_at = r.available_time
            if (
                fallback_lag_days is not None
                and start == self.first_vintage_date
                and obs_date < self.first_vintage_date
            ):
                known_at = min(known_at, vintage_available_time(obs_date + timedelta(days=fallback_lag_days)))
            end_known_at = (
                vintage_available_time(r.realtime_end.date() + timedelta(days=1)) if r.realtime_end is not None else None
            )
            by_date.setdefault(obs_date, []).append(_Vintage(start, r.value, known_at, end_known_at))
        self._dates: list[date] = sorted(by_date)
        self._vintages: list[list[_Vintage]] = [
            sorted(by_date[d], key=lambda v: v.realtime_start) for d in self._dates
        ]

    def values_as_of(self, as_of: datetime, *, since: date) -> list[tuple[date, float]]:
        """(observation_date, value) for every observation dated in
        `[since, as_of's date]` whose value was known at `as_of`, oldest
        first."""
        lo = bisect.bisect_left(self._dates, since)
        hi = bisect.bisect_right(self._dates, as_of.date())
        out: list[tuple[date, float]] = []
        for i in range(lo, hi):
            known = None
            for vintage in reversed(self._vintages[i]):
                if vintage.known_at <= as_of:
                    known = vintage
                    break
            if known is None or known.value is None:
                continue
            if known.end_known_at is not None and known.end_known_at <= as_of:
                continue
            out.append((self._dates[i], known.value))
        return out


def build_series(
    series_id: str,
    records: Sequence[MacroObservationRecord],
    fallback_lag_days: dict[str, int],
) -> PointInTimeMacroSeries:
    spec = MACRO_SERIES_BY_ID.get(series_id)
    lag = fallback_lag_days.get(series_id) if spec is not None and not spec.revised else None
    return PointInTimeMacroSeries(series_id, records, fallback_lag_days=lag)
