import pytest

from macro_filter.order_plan import build_order_plan

K = dict(max_order_notional_usd=1200.0)


def test_whole_share_buy_leaves_cash():
    p = build_order_plan(target_exposure=1.0, capital_usd=1071.0, price_usd=762.63, held_shares=0, fractional=False, **K)
    assert (p.side, p.total_shares, p.chunks, p.dry_run) == ("BUY", 1.0, (1.0,), True)
    assert p.estimated_notional_usd == 762.63


def test_too_little_capital_for_one_share_means_no_trade():
    p = build_order_plan(target_exposure=1.0, capital_usd=500.0, price_usd=762.63, held_shares=0, fractional=False, **K)
    assert p.side is None and p.chunks == ()


def test_risk_off_sells_everything_held():
    p = build_order_plan(target_exposure=0.0, capital_usd=1071.0, price_usd=700.0, held_shares=1, fractional=False, **K)
    assert (p.side, p.total_shares) == ("SELL", 1.0)


def test_fractional_buy_is_split_by_order_cap():
    p = build_order_plan(target_exposure=1.0, capital_usd=3000.0, price_usd=600.0, held_shares=0, fractional=True, max_order_notional_usd=1200.0)
    assert p.side == "BUY" and p.total_shares == 5.0
    assert p.chunks == (2.0, 2.0, 1.0)


def test_single_share_above_cap_is_flagged():
    p = build_order_plan(target_exposure=1.0, capital_usd=2000.0, price_usd=1500.0, held_shares=0, fractional=False, **K)
    assert "exceeds the per-order cap" in p.note


def test_already_at_target():
    p = build_order_plan(target_exposure=1.0, capital_usd=1071.0, price_usd=700.0, held_shares=1, fractional=False, **K)
    assert p.side is None


def test_invalid_exposure_rejected():
    with pytest.raises(ValueError):
        build_order_plan(target_exposure=1.5, capital_usd=1.0, price_usd=1.0, held_shares=0, fractional=False, **K)
