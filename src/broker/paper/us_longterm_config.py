"""Reference configuration for the Phase 22 "US long-term Paper Trading"
session -- the user-specified 10,000,000 KRW paper capital, and the
explicit, documented choice for how that KRW figure maps to this
system's USD-denominated internal accounting.

See docs/decisions/ADR-0028-us-longterm-paper-trading-operating-model.md
for the full rationale. This module does not change
`broker.paper.config.PaperTradingConfig`'s own class-level default
(`initial_cash=1_000_000.0`, unchanged since Phase 15) -- it is a
separate, explicitly-named preset, the same pattern as
`broker.config.DEFAULT_BROKER_CONFIG`/
`data_infra.providers.tiingo_config.DEFAULT_TIINGO_CONFIG`.

**KRW/USD handling (instruction section 14) -- decision recorded here**:
no verified real-time or dateable reference FX rate is available from
this environment (`docs/operations/MARKET-DATA-FX-REFERENCE.md`,
unchanged since Phase 20 -- every FX data source domain was
unreachable, and this model has no way to independently verify a
current or historical rate). Rather than fabricate a KRW-per-USD figure
to convert 10,000,000 KRW into a "precise" USD number, this reference
session takes the explicitly-permitted alternative (instruction section
14: "USD-denominated Paper account를 별도로 지원하는 것도 허용한다"):
the Paper account is natively USD-denominated (as this system's
PortfolioAccounting/PriceBar architecture already requires, since it
prices exclusively in USD -- ADR-0025/ADR-0026), and
`PAPER_CAPITAL_USD` below is a **round, order-of-magnitude USD stand-in
for the user's stated 10,000,000 KRW target -- explicitly NOT a
currency conversion**. It carries no implied exchange rate. Once a real,
verified reference FX rate is available, this constant should be
replaced with an actual KRW-converted figure and this docstring updated
to record the rate's source/date, per instruction section 14's
requirements for that path.
"""

from __future__ import annotations

from broker.paper.config import PaperTradingConfig

# The user's actual stated target, in their own currency -- recorded
# for documentation/traceability, never used in any arithmetic in this
# codebase (no FX conversion is performed).
PAPER_CAPITAL_KRW_STATED_TARGET = 10_000_000.0

# Explicitly NOT a currency-converted figure -- see module docstring.
PAPER_CAPITAL_USD = 10_000.0

# Long-term, low-frequency Paper Trading over a 16-symbol universe does
# not need PaperTradingConfig's other fields to differ from their
# existing Phase 15 defaults (cost/slippage/participation modeling
# already applies equally regardless of holding period).


def build_us_longterm_paper_config(**overrides) -> PaperTradingConfig:
    """The reference Phase 22 Paper Trading configuration --
    `initial_cash=PAPER_CAPITAL_USD`, every other field left at
    `PaperTradingConfig`'s own Phase 15 defaults unless explicitly
    overridden by the caller."""
    fields = dict(initial_cash=PAPER_CAPITAL_USD)
    fields.update(overrides)
    return PaperTradingConfig(**fields)
