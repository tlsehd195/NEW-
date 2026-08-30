"""Target registry (schema, per ML-RESEARCH-PROTOCOL.md section 8).

Reuses `strategy_research.signal_ic.forward_return` directly rather
than reimplementing forward-return computation a second time -- same
realized-return definition, same "queried directly against the
repository, deliberately bypassing AsOfDataView, because this is an
after-the-fact predictiveness check reading what actually happened"
reasoning documented in that module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from data_infra.repository import DataRepository

from strategy_research.signal_ic import forward_return

TARGET_ID = "forward_return_60d"


@dataclass(frozen=True)
class TargetSpec:
    target_id: str
    definition: str
    horizon: str
    calculation: str
    availability_time_rule: str
    version: str


TARGET_FORWARD_RETURN_60D = TargetSpec(
    target_id=TARGET_ID,
    definition="realized total return from as_of_time to as_of_time + 60 calendar days",
    horizon="60 calendar days",
    calculation="(adjusted_close[end] / adjusted_close[start]) - 1",
    availability_time_rule="only computable once end_time has fully elapsed -- as_of_time for the "
    "availability filter is end_time itself (strategy_research.signal_ic.forward_return)",
    version="v1",
)

HORIZON_DAYS = 60


def compute_target(
    price_repository: DataRepository, security_id: str, as_of_time: datetime,
) -> Optional[float]:
    return forward_return(price_repository, security_id, as_of_time, HORIZON_DAYS)
