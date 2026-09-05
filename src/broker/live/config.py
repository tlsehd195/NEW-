"""LiveTradingConfig: every threshold Live Trading uses, kept out of
code -- the same discipline `broker.paper.config.PaperTradingConfig`
(Phase 15) already established. `environment` is fixed to the literal
string `"live"` and validated in `__post_init__`; `live_trading_enabled`
defaults `False` (`PROJECT_MASTER_PLAN.md` section 14.4's
`LIVE_TRADING = false` default, applied structurally rather than left
to a caller's discipline).

See docs/specifications/PHASE-16-live-trading.md section 4.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional

from data_infra.versioning import compute_data_version


@dataclass(frozen=True)
class LiveTradingConfig:
    version: str = "live_trading_config_v1"
    broker_id: str = "toss"
    environment: str = "live"  # structurally the only allowed value -- see __post_init__

    # PROJECT_MASTER_PLAN.md section 14.4 -- default off, requires an
    # explicit, separate opt-in (never sufficient by itself -- see
    # broker.live.safety_gate.evaluate_safety_gate, which also requires
    # a LiveActivationApproval).
    live_trading_enabled: bool = False

    # -- reconciliation --
    reconciliation_tolerance: float = 0.01  # absolute; cash/quantity comparisons within this are MATCHED

    # -- kill switch triggers, all None ("not enforced") by default --
    # PROJECT_MASTER_PLAN.md section 13.12: capital/loss-limit policy is
    # explicitly deferred, never invented here (instruction section 22,
    # 53). An operator must set these explicitly for them to have any
    # effect.
    max_daily_loss: Optional[float] = None
    max_order_frequency_per_hour: Optional[int] = None

    # -- max_consecutive_failures (LIVE-RISK-POLICY.md item #11,
    # ADR-0065): `None` means "halt on the very first BrokerError" --
    # LiveTradingSession's own original, stricter behavior, preserved
    # exactly as the default so an existing caller that never sets this
    # sees no change. Setting a value explicitly LOOSENS that default
    # (tolerates up to N-1 consecutive failures before halting to
    # RECONCILIATION_REQUIRED) -- a real capital-risk trade-off, only
    # ever taken on an explicit human decision (see ADR-0065 for the
    # user's own ratified value).
    max_consecutive_failures: Optional[int] = None

    # Cancel-on-kill-switch automation (Session 36 -- the user explicitly
    # decided this should be automatic, resolving the long-open "DECISION
    # REQUIRED" this project had repeatedly cited without ever actually
    # recording a decision; see docs/decisions/ADR-0045). `True` by
    # default: this field only has any effect once `live_trading_enabled`
    # is separately opted into, so defaulting it "on" does not itself
    # make the system any less inert.
    auto_cancel_on_kill_switch: bool = True

    def __post_init__(self) -> None:
        if self.environment != "live":
            raise ValueError(
                f"LiveTradingConfig.environment must be exactly 'live', got {self.environment!r} "
                "-- a Live Trading configuration can never represent a non-live environment"
            )
        if not self.broker_id:
            raise ValueError("LiveTradingConfig.broker_id must not be empty")
        if self.reconciliation_tolerance < 0:
            raise ValueError("LiveTradingConfig.reconciliation_tolerance must not be negative")
        if self.max_daily_loss is not None and self.max_daily_loss <= 0:
            raise ValueError("LiveTradingConfig.max_daily_loss must be positive if set")
        if self.max_order_frequency_per_hour is not None and self.max_order_frequency_per_hour <= 0:
            raise ValueError("LiveTradingConfig.max_order_frequency_per_hour must be positive if set")
        if self.max_consecutive_failures is not None and self.max_consecutive_failures < 1:
            raise ValueError("LiveTradingConfig.max_consecutive_failures must be >= 1 if set")

    def configuration_version(self) -> str:
        return compute_data_version(asdict(self))


DEFAULT_LIVE_TRADING_CONFIG = LiveTradingConfig()  # live_trading_enabled=False -- inert by construction
