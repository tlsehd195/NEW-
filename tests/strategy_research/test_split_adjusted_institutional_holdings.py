"""Split adjustment of raw 13F share counts before
institutional_ownership_change_score takes its quarter-over-quarter log
change -- a real 7:1 split (AAPL, 2014) must not read as buying."""

from __future__ import annotations

import math
from datetime import datetime, timezone

from data_infra.enums import CorporateActionType
from data_infra.institutional_holding_models import InstitutionalHoldingRecord, thirteen_f_available_time
from data_infra.models import CorporateAction, Provenance
from strategy_research.factor_scores import institutional_ownership_change_score
from strategy_research.split_adjusted_institutional_holdings import SplitAdjustedInstitutionalHoldingRepository


def _dt(y, m, d):
    return datetime(y, m, d, tzinfo=timezone.utc)


def _prov(rid):
    return Provenance(source="test", source_dataset="t", source_record_id=rid, retrieved_at=_dt(2026, 1, 1), data_version="v1")


def _holding(quarter_end, shares):
    return InstitutionalHoldingRecord(
        security_id="AAPL", quarter_end=quarter_end, institutional_shares=shares, num_institutions=1,
        available_time=thirteen_f_available_time(quarter_end), ingestion_time=_dt(2026, 1, 1), provenance=_prov(f"h{quarter_end.date()}"),
    )


def _split(effective, ratio, available=None, rid="s1"):
    return CorporateAction(
        security_id="AAPL", action_type=CorporateActionType.SPLIT, available_time=available or effective,
        ingestion_time=_dt(2026, 1, 1), provenance=_prov(rid), effective_time=effective, details={"ratio": ratio},
    )


class _Holdings:
    def __init__(self, records):
        self._records = records

    def get_institutional_holding_history(self, security_id, as_of_time, *, start=None, end=None):
        return [r for r in self._records if r.available_time <= as_of_time]


class _Prices:
    def __init__(self, actions):
        self._actions = actions

    def get_corporate_actions(self, security_id, start, end, as_of_time):
        return [a for a in self._actions if a.available_time <= as_of_time and start <= a.effective_time <= end]


Q1, Q2 = _dt(2014, 3, 31), _dt(2014, 6, 30)
HOLDINGS = _Holdings([_holding(Q1, 100.0), _holding(Q2, 700.0)])


def test_a_split_between_quarters_is_not_read_as_buying() -> None:
    repo = SplitAdjustedInstitutionalHoldingRepository(HOLDINGS, _Prices([_split(_dt(2014, 6, 9), "7:1")]))
    assert institutional_ownership_change_score("AAPL", _dt(2014, 9, 1), repo) == 0.0
    assert repo.applied_split_count == 1


def test_without_adjustment_the_same_data_reads_as_a_large_increase() -> None:
    assert math.isclose(institutional_ownership_change_score("AAPL", _dt(2014, 9, 1), HOLDINGS), math.log(7))


def test_a_split_not_yet_known_at_as_of_time_is_not_applied() -> None:
    late = _split(_dt(2014, 6, 9), "7:1", available=_dt(2015, 1, 1))
    repo = SplitAdjustedInstitutionalHoldingRepository(HOLDINGS, _Prices([late]))
    assert math.isclose(institutional_ownership_change_score("AAPL", _dt(2014, 9, 1), repo), math.log(7))


def test_a_split_after_both_quarters_scales_both_and_leaves_the_change_unchanged() -> None:
    holdings = _Holdings([_holding(Q1, 100.0), _holding(Q2, 110.0)])
    repo = SplitAdjustedInstitutionalHoldingRepository(holdings, _Prices([_split(_dt(2014, 8, 20), "4:1")]))
    history = repo.get_institutional_holding_history("AAPL", _dt(2014, 9, 1))
    assert [h.institutional_shares for h in history] == [400.0, 440.0]
    assert math.isclose(institutional_ownership_change_score("AAPL", _dt(2014, 9, 1), repo), math.log(1.1))


def test_a_split_effective_on_the_quarter_end_itself_is_already_in_that_report() -> None:
    repo = SplitAdjustedInstitutionalHoldingRepository(HOLDINGS, _Prices([_split(Q2, "7:1")]))
    history = repo.get_institutional_holding_history("AAPL", _dt(2014, 9, 1))
    assert [h.institutional_shares for h in history] == [700.0, 700.0]


def test_a_spin_off_price_adjustment_is_not_applied_to_share_counts() -> None:
    """ADR-0216: Tiingo reports a spin-off as a splitFactor (real: HON
    1.011 on 2018-10-01) -- no holder's share count changes."""
    holdings = _Holdings([_holding(Q1, 100.0), _holding(Q2, 100.0)])
    repo = SplitAdjustedInstitutionalHoldingRepository(holdings, _Prices([_split(_dt(2014, 6, 9), 1.011)]))
    assert institutional_ownership_change_score("AAPL", _dt(2014, 9, 1), repo) == 0.0
    assert repo.applied_split_count == 0


def test_a_backfilled_tiingo_split_is_applied_in_a_historical_as_of_query(tmp_path) -> None:
    """The real regression (research-catalogs-v1, 2026-09-26): a split
    backfilled years later was stamped with the backfill's ingestion
    time, so a 2014 as-of query never saw it and 0 splits were applied."""
    from data_infra.providers.tiingo import TiingoDataProvider
    from data_infra.providers.tiingo_config import TiingoConfig
    from storage.config import StorageConfig
    from storage.data_repository import DuckDBDataRepository
    from storage.engine import StorageEngine

    provider = TiingoDataProvider(TiingoConfig(), transport=object())
    [action] = provider.normalize_corporate_actions(
        "AAPL", [{"date": "2014-06-09T00:00:00.000Z", "splitFactor": 7.000007, "divCash": 0.0}],
        retrieved_at=_dt(2026, 9, 11), ingestion_time=_dt(2026, 9, 11),
    )
    engine = StorageEngine(StorageConfig(root_dir=tmp_path))
    try:
        prices = DuckDBDataRepository(engine)
        prices.add_corporate_action(action)
        repo = SplitAdjustedInstitutionalHoldingRepository(HOLDINGS, prices)
        assert math.isclose(institutional_ownership_change_score("AAPL", _dt(2014, 9, 1), repo), math.log(700 / 700.0007), abs_tol=1e-6)
        assert repo.applied_split_count == 1
    finally:
        engine.close()
