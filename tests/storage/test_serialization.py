"""Category: Persistence Test -- direct round-trip checks for
storage.serialization's explicit dataclass<->dict/row conversion pairs,
the ones with no other test coverage of their own (most are only
exercised indirectly through a full repository round trip)."""

from __future__ import annotations

from datetime import datetime, timezone

from backtest.portfolio import PortfolioView, PositionView

from storage.serialization import dict_to_portfolio_view, portfolio_view_to_dict


def _utc(year, month, day, hour=0, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


class TestPortfolioViewRoundTrip:
    def test_market_value_survives_the_round_trip(self) -> None:
        """Session 37 (ADR-0115, external review N-4): before this fix,
        `portfolio_view_to_dict` silently dropped `PositionView.
        market_value` entirely -- every `DecisionSnapshot.portfolio_state`
        persisted through `storage.trade_journal_repository` and reloaded
        came back with `market_value=None` on every position regardless
        of what was actually recorded there, reverting any downstream
        re-assessment to `risk.engine.DeterministicPortfolioRiskEngine`'s
        cost-basis fallback."""
        view = PortfolioView(
            as_of_time=_utc(2024, 1, 1, 20),
            cash=1_000.0,
            positions={
                "AAA": PositionView(security_id="AAA", quantity=10.0, average_cost=95.0, market_value=1_050.0),
            },
            portfolio_value=2_050.0,
        )
        reloaded = dict_to_portfolio_view(portfolio_view_to_dict(view))
        assert reloaded == view
        assert reloaded.positions["AAA"].market_value == 1_050.0

    def test_a_position_with_no_recorded_market_value_round_trips_as_none(self) -> None:
        view = PortfolioView(
            as_of_time=_utc(2024, 1, 1, 20),
            cash=1_000.0,
            positions={"AAA": PositionView(security_id="AAA", quantity=10.0, average_cost=95.0)},
            portfolio_value=1_950.0,
        )
        reloaded = dict_to_portfolio_view(portfolio_view_to_dict(view))
        assert reloaded.positions["AAA"].market_value is None

    def test_a_payload_persisted_before_market_value_existed_still_loads(self) -> None:
        """Backward compatibility: an already-stored payload with no
        `market_value` key at all (written before this fix) must not
        raise -- it falls back to `PositionView`'s own default (None),
        identically to a position that was never given one."""
        legacy_payload = {
            "as_of_time": _utc(2024, 1, 1, 20).isoformat(),
            "cash": 1_000.0,
            "positions": {"AAA": {"security_id": "AAA", "quantity": 10.0, "average_cost": 95.0}},
            "portfolio_value": 1_950.0,
        }
        view = dict_to_portfolio_view(legacy_payload)
        assert view.positions["AAA"].market_value is None

    def test_as_of_time_round_trips_timezone_aware(self) -> None:
        view = PortfolioView(as_of_time=_utc(2024, 3, 15, 13, 30), cash=500.0, positions={}, portfolio_value=500.0)
        reloaded = dict_to_portfolio_view(portfolio_view_to_dict(view))
        assert reloaded.as_of_time == view.as_of_time
        assert reloaded.as_of_time.tzinfo is not None

    def test_none_round_trips_to_none(self) -> None:
        assert portfolio_view_to_dict(None) is None
        assert dict_to_portfolio_view(None) is None
