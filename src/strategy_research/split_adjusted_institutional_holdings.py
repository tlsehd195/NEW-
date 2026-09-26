"""Split-adjusting read-only view over an institutional-holdings
repository, for `factor_scores.institutional_ownership_change_score`.

SEC Form 13F reports raw share counts as of each quarter end, never
adjusted for later stock splits (real, observed in the first real
all-filer backfill, 2026-09-26: AAPL's aggregate institutional holdings
read ~506M shares at 2013-06-30 and ~2.98B at 2015-06-30, straddling its
2014 7:1 split). `institutional_ownership_change_score` takes the log
change between the two most recent quarters, so a quarter pair that
straddles a split would read a 7:1 split as a ~+1.95 "institutional
buying" signal. This wrapper restates every record's
`institutional_shares` on the share basis in effect at `as_of_time`,
leaving the factor's pre-registered construction (RULE 0.8) untouched.

Point-in-time: only splits whose `available_time <= as_of_time` are
applied, via the price repository's own `get_corporate_actions` look-
ahead guard. A split takes effect for every quarter ending strictly
before its `effective_time` (falling back to `event_time`); a 13F
report dated on or after that time already reflects post-split shares.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime
from typing import Optional

from backtest.corporate_actions import _parse_ratio
from data_infra.enums import CorporateActionType

_SPLIT_TYPES = {CorporateActionType.SPLIT, CorporateActionType.REVERSE_SPLIT}


class SplitAdjustedInstitutionalHoldingRepository:
    def __init__(self, inner: object, price_repository: object) -> None:
        self._inner = inner
        self._price_repository = price_repository
        self.applied_split_count = 0  # distinct (security, split) pairs ever applied, for run reporting
        self._applied_keys: set[tuple[str, str]] = set()

    def _splits(self, security_id: str, start: datetime, as_of_time: datetime) -> list[tuple[datetime, float, str]]:
        actions = self._price_repository.get_corporate_actions(security_id, start, as_of_time, as_of_time=as_of_time)
        splits = []
        for action in actions:
            if action.action_type not in _SPLIT_TYPES:
                continue
            when = action.effective_time or action.event_time
            ratio = _parse_ratio(action.details.get("ratio"))
            if when is None or ratio is None or ratio <= 0:
                continue
            splits.append((when, ratio, action.provenance.source_record_id))
        return splits

    def get_institutional_holding_history(
        self, security_id: str, as_of_time: datetime, *, start: Optional[datetime] = None, end: Optional[datetime] = None,
    ) -> list:
        history = self._inner.get_institutional_holding_history(security_id, as_of_time, start=start, end=end)
        if not history:
            return history
        splits = self._splits(security_id, history[0].quarter_end, as_of_time)
        if not splits:
            return history
        adjusted = []
        for record in history:
            factor = 1.0
            for when, ratio, key in splits:
                if record.quarter_end < when:
                    factor *= ratio
                    if (security_id, key) not in self._applied_keys:
                        self._applied_keys.add((security_id, key))
                        self.applied_split_count += 1
            adjusted.append(record if factor == 1.0 else dataclasses.replace(record, institutional_shares=record.institutional_shares * factor))
        return adjusted

    def get_latest_institutional_holding(self, security_id: str, as_of_time: datetime):
        history = self.get_institutional_holding_history(security_id, as_of_time)
        return history[-1] if history else None
