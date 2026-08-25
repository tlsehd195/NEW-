"""TossAuthClient: resolves `BrokerConfig`'s credential *references* to
real values and exchanges them for a bearer access token via Toss
Securities' confirmed OAuth2 Client Credentials token endpoint.

**This module is the only place in `broker.*` that calls
`os.environ`/`os.getenv`** (`tests/broker/test_broker_boundary.py`
verifies this by AST scan across the whole package). It is reached only
from `broker.toss.adapter.TossBrokerAdapter`, itself only reachable when
a caller explicitly constructs a `BrokerConfig` with
`execution_mode=LIVE, live_opt_in=True` -- never from `broker.mock`,
never from any test outside `tests/broker/toss/test_toss_auth.py`
(which stubs the transport, never the network).

Neither the resolved `ResolvedCredentials` nor the returned bearer token
is ever returned to a caller beyond this module's own immediate use, put
in a persisted model field, or logged (instruction section 9).
"""

from __future__ import annotations

import os

from broker.auth import ResolvedCredentials
from broker.config import BrokerConfig
from broker.errors import BrokerAuthError
from broker.transport import BrokerTransport
from broker.toss.endpoints import TOKEN_PATH


def resolve_credentials(config: BrokerConfig) -> ResolvedCredentials:
    client_id = os.environ.get(config.api_key_reference)
    client_secret = os.environ.get(config.api_secret_reference)
    account_id = os.environ.get(config.account_reference)
    if not client_id or not client_secret or not account_id:
        raise BrokerAuthError(
            "missing credentials: one or more of "
            f"{config.api_key_reference}/{config.api_secret_reference}/{config.account_reference} "
            "is not set in the environment"
        )
    return ResolvedCredentials(client_id=client_id, client_secret=client_secret, account_id=account_id)


class TossAuthClient:
    def __init__(self, transport: BrokerTransport, config: BrokerConfig) -> None:
        self._transport = transport
        self._config = config

    def fetch_access_token(self) -> str:
        credentials = resolve_credentials(self._config)
        response = self._transport.post(
            TOKEN_PATH,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            json_body={
                "grant_type": "client_credentials",
                "client_id": credentials.client_id,
                "client_secret": credentials.client_secret,
            },
            timeout=self._config.timeout_seconds,
        )
        if response.status_code != 200 or response.body is None:
            raise BrokerAuthError(f"token request failed with status {response.status_code}")
        token = response.body.get("access_token")
        if not token:
            raise BrokerAuthError("token response missing access_token")
        return token
