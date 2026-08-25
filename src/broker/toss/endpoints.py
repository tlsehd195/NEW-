"""Toss Securities Open API endpoint paths.

Every constant here is annotated CONFIRMED or UNCONFIRMED, per
docs/specifications/PHASE-13-toss-securities-adapter.md's "Toss API
Verification" section -- confirmed via public research on 2026-08-25
(the official documentation host, developers.tossinvest.com, and the
API host, openapi.tossinvest.com, are both blocked by this
environment's network egress proxy, so nothing here was read directly
from the OpenAPI spec; everything below is corroborated by at least the
Toss Securities Open API's official announcement of general
availability on 2026-08-13 plus independent third-party technical
write-ups quoting example requests). PROJECT_MASTER_PLAN.md section
9.3: "추측해서 endpoint를 만들지 않는다" -- an UNCONFIRMED path is never
used by `broker.toss.adapter.TossBrokerAdapter`; the corresponding
operation raises `broker.errors.BrokerCapabilityError` instead (see
`broker.toss.adapter`).
"""

from __future__ import annotations

BASE_URL = "https://openapi.tossinvest.com"

# CONFIRMED: OAuth2 Client Credentials token endpoint.
TOKEN_PATH = "/oauth2/token"

# CONFIRMED: order creation, quoted directly in third-party technical
# write-ups with an example body ({"symbol": "005930", "side": "BUY",
# "orderType": "LIMIT", "quantity": "10", "price": "70000"}) and a
# clientOrderId field for idempotency.
CREATE_ORDER_PATH = "/api/v1/orders"

# UNCONFIRMED: research corroborates that order modification/
# cancellation, order status/history queries, and account/balance/
# holdings queries all exist as endpoints (the account-scoped ones
# additionally requiring an `X-Tossinvest-Account` header), but no
# source available to this session names their exact paths. Left
# undefined here deliberately -- see broker.toss.adapter, which
# declares these operations CapabilityStatus.UNKNOWN and refuses to
# guess a path.
CANCEL_ORDER_PATH: None = None
ORDER_STATUS_PATH: None = None
ACCOUNT_PATH: None = None
POSITIONS_PATH: None = None

# Header Toss requires on every account-scoped call (order/account/
# position), per research -- confirmed to exist, name confirmed.
ACCOUNT_HEADER = "X-Tossinvest-Account"
