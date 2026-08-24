"""CorporateActionApplier: applies SPLIT/DIVIDEND events to portfolio
state at the moment they become available and effective.

See docs/specifications/PHASE-2-backtesting.md section 8.4.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from data_infra.enums import CorporateActionType
from data_infra.models import CorporateAction

from backtest.portfolio import PortfolioAccounting

_SPLIT_TYPES = {CorporateActionType.SPLIT, CorporateActionType.REVERSE_SPLIT}
_DIVIDEND_TYPES = {CorporateActionType.DIVIDEND, CorporateActionType.SPECIAL_DIVIDEND}


def _parse_ratio(raw: object) -> Optional[float]:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str) and ":" in raw:
        try:
            num_str, den_str = raw.split(":", 1)
            numerator, denominator = float(num_str), float(den_str)
        except ValueError:
            return None
        if denominator == 0:
            return None
        return numerator / denominator
    return None


class CorporateActionApplier:
    """MERGER/ACQUISITION/SPIN_OFF/TICKER_CHANGE/DELISTING are not
    handled in Phase 2 (Phase 2 spec section 8.4) — encountering one
    produces a warning, not a silent no-op and not a crash."""

    def __init__(self) -> None:
        self._applied: set[str] = set()  # provenance.source_record_id already applied

    def apply(
        self,
        actions: Sequence[CorporateAction],
        portfolio: PortfolioAccounting,
        as_of_time: datetime,
    ) -> list[str]:
        warnings: list[str] = []
        for action in actions:
            key = action.provenance.source_record_id
            if key in self._applied:
                continue
            if action.available_time > as_of_time:
                # Defensive re-check — AsOfDataView should never surface
                # this in the first place (Phase 2 spec section 4).
                continue

            if action.action_type in _SPLIT_TYPES:
                ratio = _parse_ratio(action.details.get("ratio"))
                if ratio is None or ratio <= 0:
                    warnings.append(
                        f"could not parse split ratio for {action.security_id}: {action.details!r}"
                    )
                    self._applied.add(key)
                    continue
                portfolio.apply_split(action.security_id, ratio)
            elif action.action_type in _DIVIDEND_TYPES:
                amount = action.details.get("amount")
                if amount is None:
                    warnings.append(
                        f"missing dividend amount for {action.security_id}: {action.details!r}"
                    )
                    self._applied.add(key)
                    continue
                portfolio.apply_dividend(action.security_id, float(amount), as_of_time)
            else:
                warnings.append(
                    f"corporate action type {action.action_type} is not handled in Phase 2 "
                    f"(security {action.security_id}) — see Phase 2 spec section 8.4"
                )

            self._applied.add(key)
        return warnings
