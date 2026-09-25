#!/usr/bin/env python3
"""Verifies a real Alpaca **paper** trading account by actually
submitting a market buy order, waiting for it to fill, then submitting
a market sell to close the position back out -- a real, executable
round trip, not just an account-info read (account owner's own
request, 2026-09-18: "매수/매도까지 검증" -- verify all the way through
buy/sell, not just connectivity).

**This places real orders against whatever account the credentials
point to.** No real money is ever at risk (Alpaca's paper endpoint is
fully simulated), but this is a genuinely stateful action against an
external system -- never run this on a schedule, only deliberately
(`workflow_dispatch` in this project's own CI, or by hand). This
script refuses to run at all against anything but Alpaca's own paper
domain (`paper-api.alpaca.markets`) -- see `_is_paper_endpoint`
below -- so a misconfigured `ALPACA_BASE_URL` pointing at the real
live-trading domain can never reach this code path.

**Optional dependency, never imported by src/.** Install with
`pip install -e '.[broker-verification]'` (adds `alpaca-py`, the
official SDK -- unlike this project's own `src/data_infra/providers/`
stack, which deliberately never depends on a third-party HTTP/SDK
library for anything that ships in production, this is a one-off,
manually/`workflow_dispatch`-triggered verification tool, not a
component of the live trading pipeline itself, so the official SDK is
the pragmatic choice here).

Credentials are read only from `ALPACA_API_KEY`/`ALPACA_SECRET_KEY`
environment variables (never a CLI flag, so a real secret is never
visible in a process list or shell history) -- `ALPACA_BASE_URL` is
optional and defaults to Alpaca's own paper domain when unset.

Usage:
    export ALPACA_API_KEY=...
    export ALPACA_SECRET_KEY=...
    pip install -e '.[broker-verification]'
    python3 scripts/verify_alpaca_paper_broker.py --symbol AAPL --qty 1
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from urllib.parse import urlparse

_PAPER_DOMAIN = "paper-api.alpaca.markets"
_TERMINAL_ORDER_STATUSES = frozenset(
    {"filled", "canceled", "expired", "rejected", "done_for_day", "stopped"}
)


def _is_paper_endpoint(base_url: str | None) -> bool:
    """`None` means "use alpaca-py's own default paper domain" -- only
    an explicit, non-paper `base_url` is rejected.

    Independent audit finding (2026-09-24): the previous check was a
    plain substring test (`_PAPER_DOMAIN in base_url`), which this
    docstring's own claim ("a misconfigured ALPACA_BASE_URL pointing at
    the real live-trading domain can never reach this code path")
    relies on being a real domain guard. A substring check is not one:
    `_PAPER_DOMAIN` also matches as a QUERY STRING or PATH component of
    an entirely different, attacker-controlled host (e.g.
    `"https://evil.example.com/?x=paper-api.alpaca.markets"`), or as a
    prefix of a look-alike hostname the real domain is not actually a
    suffix of. Fixed by parsing the URL and checking the real hostname
    is either exactly `_PAPER_DOMAIN` or a subdomain of it (`.` prefix
    match), which a query string/path/look-alike host cannot satisfy."""
    if base_url is None:
        return True
    hostname = urlparse(base_url).hostname
    return hostname is not None and (hostname == _PAPER_DOMAIN or hostname.endswith("." + _PAPER_DOMAIN))


def _poll_until_terminal(client, order_id, timeout_seconds: float, interval_seconds: float):
    deadline = time.monotonic() + timeout_seconds
    order = client.get_order_by_id(order_id)
    while order.status.value not in _TERMINAL_ORDER_STATUSES and time.monotonic() < deadline:
        time.sleep(interval_seconds)
        order = client.get_order_by_id(order_id)
    return order


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbol", default="AAPL", help="A liquid, actively-traded symbol (default: AAPL)")
    parser.add_argument("--qty", type=float, default=1.0, help="Whole or fractional shares to buy then sell back (default: 1.0)")
    parser.add_argument("--poll-seconds", type=float, default=60.0, help="How long to wait for each order to reach a terminal status before giving up (default: 60s)")
    parser.add_argument("--poll-interval-seconds", type=float, default=2.0, help="Delay between order-status polls (default: 2s)")
    args = parser.parse_args(argv)

    try:
        from alpaca.trading.client import TradingClient
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest
    except ImportError:
        print("FATAL: alpaca-py is required -- install with: pip install -e '.[broker-verification]'", file=sys.stderr)
        return 1

    api_key = os.environ.get("ALPACA_API_KEY")
    secret_key = os.environ.get("ALPACA_SECRET_KEY")
    base_url = os.environ.get("ALPACA_BASE_URL") or None
    if not api_key or not secret_key:
        print("FATAL: ALPACA_API_KEY and ALPACA_SECRET_KEY environment variables are required", file=sys.stderr)
        return 1
    if not _is_paper_endpoint(base_url):
        print(
            f"FATAL: refusing to run against a non-paper endpoint ({base_url!r}) -- "
            f"this script only ever verifies the Alpaca PAPER broker (must contain "
            f"{_PAPER_DOMAIN!r}), never live trading.",
            file=sys.stderr,
        )
        return 1

    client = TradingClient(api_key, secret_key, paper=True, url_override=base_url)

    account = client.get_account()
    print(
        f"Connected to Alpaca paper account {account.account_number}: "
        f"status={account.status.value} cash={account.cash} "
        f"buying_power={account.buying_power} portfolio_value={account.portfolio_value}"
    )
    if account.trading_blocked or account.account_blocked:
        print("FATAL: this account is blocked from trading -- refusing to submit a test order", file=sys.stderr)
        return 1

    clock = client.get_clock()
    if not clock.is_open:
        print(
            f"Market is currently closed (next open: {clock.next_open.isoformat()}) -- "
            "a market order submitted now would not fill promptly, so this run stops "
            "here rather than submitting an order that would just sit unfilled. "
            "Re-run this script during real market hours to actually verify a fill.",
            file=sys.stderr,
        )
        return 2

    print(f"Submitting a real market BUY order: {args.qty} share(s) of {args.symbol} ...")
    buy_order = client.submit_order(
        MarketOrderRequest(symbol=args.symbol, qty=args.qty, side=OrderSide.BUY, time_in_force=TimeInForce.DAY)
    )
    print(f"Buy order submitted: id={buy_order.id} status={buy_order.status.value}")

    filled_buy = _poll_until_terminal(client, buy_order.id, args.poll_seconds, args.poll_interval_seconds)
    if filled_buy.status.value != "filled":
        print(
            f"Buy order did not fill within {args.poll_seconds}s (status={filled_buy.status.value}) -- "
            "not claiming a verified round trip.",
            file=sys.stderr,
        )
        return 1
    print(f"Buy filled: {filled_buy.filled_qty} share(s) @ {filled_buy.filled_avg_price} at {filled_buy.filled_at.isoformat()}")

    print(f"Submitting a real market SELL order to close the position: {filled_buy.filled_qty} share(s) of {args.symbol} ...")
    sell_order = client.submit_order(
        MarketOrderRequest(symbol=args.symbol, qty=filled_buy.filled_qty, side=OrderSide.SELL, time_in_force=TimeInForce.DAY)
    )
    print(f"Sell order submitted: id={sell_order.id} status={sell_order.status.value}")

    filled_sell = _poll_until_terminal(client, sell_order.id, args.poll_seconds, args.poll_interval_seconds)
    if filled_sell.status.value != "filled":
        print(
            f"WARNING: sell order to close the test position did not fill within "
            f"{args.poll_seconds}s (status={filled_sell.status.value}) -- a "
            f"{filled_buy.filled_qty}-share {args.symbol} position may remain open on "
            "this paper account; check it manually.",
            file=sys.stderr,
        )
        return 1
    print(f"Sell filled: {filled_sell.filled_qty} share(s) @ {filled_sell.filled_avg_price} at {filled_sell.filled_at.isoformat()}")

    print(f"Real buy->fill->sell->fill round trip verified against the Alpaca paper broker ({args.symbol}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
