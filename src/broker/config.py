"""BrokerConfig: every threshold, credential *reference*, and execution
mode the Broker Adapter layer uses, kept out of code -- the same
discipline `ai_gateway.config.ProviderConfig` (Phase 12) already
established, applied here with one additional, load-bearing rule:
`execution_mode` cannot be `LIVE` unless the caller also passes
`live_opt_in=True` explicitly.

See docs/specifications/PHASE-13-toss-securities-adapter.md sections 5,
10.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from broker.enums import BrokerExecutionMode

from data_infra.versioning import compute_data_version


@dataclass(frozen=True)
class BrokerConfig:
    version: str = "broker_config_v1"
    broker_id: str = "mock-broker"
    broker_name: str = "Mock Broker"
    execution_mode: BrokerExecutionMode = BrokerExecutionMode.OFFLINE
    # PROJECT_MASTER_PLAN.md section 14.2: never a secret value, only an
    # environment-variable *name* -- matching the placeholders
    # .env.example already reserves (Phase 0): TOSS_API_KEY/TOSS_API_SECRET/
    # TOSS_ACCOUNT_ID.
    api_key_reference: str = "TOSS_API_KEY"
    api_secret_reference: str = "TOSS_API_SECRET"
    account_reference: str = "TOSS_ACCOUNT_ID"
    base_url: str = "https://openapi.tossinvest.com"
    timeout_seconds: float = 10.0
    max_retries: int = 1
    # a required, explicit second signal -- setting execution_mode=LIVE
    # alone is not enough (instruction section 10: "환경변수 하나만
    # 존재해도 실계좌 주문이 발생하는 구조를 만들지 마라").
    live_opt_in: bool = False

    def __post_init__(self) -> None:
        if not self.broker_id:
            raise ValueError("BrokerConfig.broker_id must not be empty")
        if self.execution_mode == BrokerExecutionMode.LIVE and not self.live_opt_in:
            raise ValueError(
                "BrokerConfig.execution_mode == LIVE requires live_opt_in=True to be passed "
                "explicitly -- setting execution_mode alone is never sufficient "
                "(PROJECT_MASTER_PLAN.md section 14.4, instruction section 10)"
            )
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.max_retries < 0:
            raise ValueError("max_retries must not be negative")

    def configuration_version(self) -> str:
        return compute_data_version({**asdict(self), "execution_mode": self.execution_mode.value})


DEFAULT_BROKER_CONFIG = BrokerConfig()
