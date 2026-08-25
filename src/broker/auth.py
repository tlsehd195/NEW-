"""Authentication boundary: the *shape* of a resolved credential, never
the resolution logic itself -- resolving `BrokerConfig.
api_key_reference`/`api_secret_reference` to an actual secret value is
`broker.toss.auth`'s job alone (instruction section 21's confirmed
OAuth2 Client Credentials flow), and it is the *only* place in this
entire package that calls `os.environ`/`os.getenv`
(`tests/broker/test_broker_boundary.py`).

See docs/specifications/PHASE-13-toss-securities-adapter.md section 8.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResolvedCredentials:
    """Held only for the lifetime of one authenticated call -- never a
    field on any type this package persists or logs
    (`broker.models.*`, `storage.broker_repository.*`). Deliberately
    has no `__repr__`/`__str__` override that would make this *easier*
    to accidentally print -- the dataclass default repr is what would
    print, so nothing here hides that risk; the actual safety property
    is structural: no persisted/returned type ever holds one of these
    (verified by `tests/broker/test_broker_secret_safety.py`, which
    checks every field name across every persisted model)."""

    client_id: str
    client_secret: str
    account_id: str
