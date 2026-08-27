"""Toss Securities Open API endpoint paths.

Every constant here is annotated CONFIRMED or UNCONFIRMED. Phase 13/17
research left `CANCEL_ORDER_PATH`/`ORDER_STATUS_PATH`/`ACCOUNT_PATH`/
`POSITIONS_PATH` as `None` -- the official documentation host was
network-blocked from this environment (still true, ADR-0025 confirms
the same blanket restriction extends to market-data providers too).

**Phase 21 update**: the user provided the full official Toss
Securities Open API OpenAPI 3.1.0 specification directly in-session
during Phase 20. Every path below is now Tier 1 evidence, extracted
from that document and recorded in full in
`docs/operations/TOSS-API-GAP-ANALYSIS.md`'s "Phase 20 addendum" --
none of it is guessed or inferred from naming convention.
PROJECT_MASTER_PLAN.md section 9.3: "추측해서 endpoint를 만들지
않는다."
"""

from __future__ import annotations

BASE_URL = "https://openapi.tossinvest.com"

# CONFIRMED (Phase 13, Tier 2 at the time -- corroborated again by the
# Tier 1 spec in Phase 20): OAuth2 Client Credentials token endpoint.
TOKEN_PATH = "/oauth2/token"

# CONFIRMED: order creation.
CREATE_ORDER_PATH = "/api/v1/orders"

# CONFIRMED (Phase 21, Tier 1): cash/buying-power query. Requires a
# `currency` query param (`KRW` or `USD`) -- this project queries `USD`
# only (see broker.toss.adapter.get_account), since every position and
# every internal accounting figure in this system is USD-denominated
# (US equities only, ADR-0025/ADR-0026). KRW buying power exists on a
# real Toss account too but is out of this phase's scope -- no
# KRW/USD conversion logic exists anywhere in this codebase
# (docs/operations/MARKET-DATA-FX-REFERENCE.md).
BUYING_POWER_PATH = "/api/v1/buying-power"

# CONFIRMED (Phase 21, Tier 1): holdings/positions query. Optional
# `symbol` query param filter, not used here (this adapter always
# fetches the full position list).
HOLDINGS_PATH = "/api/v1/holdings"

# CONFIRMED (Phase 21, Tier 1): single-order detail by Toss's own
# orderId -- this specific variant was never found at any evidence tier
# before Phase 20's Tier 1 document (Phase 13's original research only
# ever found the list endpoint, `GET /api/v1/orders`, which this
# project does not use -- see broker.toss.adapter.get_order_status's
# docstring for why the detail endpoint is used instead).
ORDER_DETAIL_PATH_TEMPLATE = "/api/v1/orders/{order_id}"

# CONFIRMED (Phase 21, Tier 1): cancel. **Critical, non-obvious
# semantics**: the response's `orderId` is a newly issued identifier
# for the cancel operation itself, explicitly documented as different
# from the original order's `orderId` -- see
# broker.models.BrokerOrderResponse.cancel_reference_id and
# broker.toss.mapping.parse_cancel_response.
CANCEL_ORDER_PATH_TEMPLATE = "/api/v1/orders/{order_id}/cancel"

# Account discovery (`GET /api/v1/accounts`, returns the account list
# an operator's TOSS_ACCOUNT_ID should be one of) is Tier 1 documented
# but deliberately not wired up as its own capability method this
# phase -- this project's existing credential model (Phase 13,
# `BrokerConfig.account_reference`) already has the human operator
# pre-configure the exact account identifier used in the
# `X-Tossinvest-Account` header, the same way `submit_order` already
# does; every account-scoped call below reuses that established
# pattern rather than adding new account-discovery/resolution logic
# not requested this phase. A future phase could use `/api/v1/accounts`
# to validate the configured id against the real account list.

# Header Toss requires on every account-scoped call (order/account/
# position), per research -- confirmed to exist, name confirmed.
ACCOUNT_HEADER = "X-Tossinvest-Account"
