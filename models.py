from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# -----------------------------------------------------------------------------
# Shared type aliases
# -----------------------------------------------------------------------------
# These aliases make the intent of allocations and scores explicit across the
# engine, UI, validation, and storage layers.
# -----------------------------------------------------------------------------
FundsAlloc = dict[str, float]
Scores = dict[str, int]


# -----------------------------------------------------------------------------
# Market snapshot contract
# -----------------------------------------------------------------------------
# MarketData is the normalized, engine-ready snapshot produced by
# data_sources.py and validated by validation.py.
#
# Keep this class focused on data only:
# - no scoring
# - no fetching
# - no persistence
# - no UI logic
# -----------------------------------------------------------------------------
@dataclass
class MarketData:
    """Normalized macro and market snapshot used by the engine.

    Notes
    -----
    - Most fields are inputs used directly by factor scoring.
    - Some fields are derived overlays or short-horizon panic indicators.
    - `timestamp` should represent when the snapshot was assembled, not when a
      source originally published its underlying data.
    """

    # Core macro inputs
    core_pce_yoy: float
    ism_pmi: float
    services_pmi: float
    initial_claims: float
    breakeven_inflation: float
    fed_assets_growth_yoy: float
    real_yield_10y: float
    move_index: float
    sloos_net_pct: float
    hy_oas: float
    shiller_cape: float
    fwd_eps_growth_yoy: float
    vix_spot: float
    pct_dist_200_sma: float
    drawdown_pct: float
    stlfsi_index: float
    bond_yield_10y: float
    dxy_spot: float
    market_breadth_pct: float
    spx_spot: float

    # Optional / derived spread and overlay inputs
    treasury_10y_3m_spread: float = 0.0
    inflation_shock: float = 0.0
    central_bank_stance: float = 0.0
    liquidity_pressure: float = 0.0

    # Short-horizon panic flags
    vix_3d_panic: bool = False
    spx_3d_panic: bool = False

    # Optional short lookback series for overlay logic / diagnostics
    vix_last_3: list[float] = field(default_factory=list)
    spx_dist_last_3: list[float] = field(default_factory=list)

    # Snapshot assembly time in UTC-localized or ISO-formatted form
    timestamp: datetime | None = None


# -----------------------------------------------------------------------------
# Interpreted market state contract
# -----------------------------------------------------------------------------
# MarketState separates raw indicator interpretation from tactical policy.
# This is the abstraction layer used by the engine to reason in categorical
# market conditions instead of repeatedly checking raw thresholds.
# -----------------------------------------------------------------------------
@dataclass(frozen=True)
class MarketState:
    """Categorical macro state used by tactical allocation logic."""

    inflation: str
    growth: str
    liquidity: str
    credit: str
    stress: str
    trend: str
    policy: str
    valuation: str
    dxy: str
    curve: str

    panic: bool = False
    asymmetric_vol: bool = False
    f_unlock: bool = False
    dxy_strong: bool = False


# -----------------------------------------------------------------------------
# Engine output contract
# -----------------------------------------------------------------------------
# EngineResult is the single output object returned by engine.py.
# It carries both the target allocation and the reasoning flags needed by the
# UI and downstream IFT gate.
# -----------------------------------------------------------------------------
@dataclass
class EngineResult:
    """Decision output from the tactical engine."""

    allocations: FundsAlloc
    scores: Scores
    composite_score: int
    regime: str
    base_alloc: FundsAlloc

    # Decision flags used for UI and IFT logic
    asymmetric_vol_trigger: bool
    dxy_strong: bool
    emergency_triggered: bool


# -----------------------------------------------------------------------------
# User / app configuration contract
# -----------------------------------------------------------------------------
# Config contains user-editable settings and runtime preferences.
# It should be persisted by storage.py and edited via app.py UI controls.
# -----------------------------------------------------------------------------
@dataclass
class Config:
    """Editable application configuration."""

    current_alloc: FundsAlloc

    # IFT and drift controls
    allow_second_ift: bool = False
    normal_drift_threshold_pct: float = 7.5
    score_change_threshold: int = 3
    confirmation_days: int = 3
    cooldown_days: int = 5

    # Data source preferences
    use_live_macro: bool = True
    fred_api_key: str = ""

    # Manual override controls
    manual_override_enabled: bool = False
    manual_regime: str = "OPTIMIZED NEUTRAL"

    # Free-form storage for experimental or advanced settings
    overrides: dict[str, Any] = field(default_factory=dict)


# -----------------------------------------------------------------------------
# Application runtime state
# -----------------------------------------------------------------------------
# AppState tracks locally persisted operational state across Streamlit reruns
# and between sessions.
#
# Important:
# - This is not the engine result.
# - This is not the config.
# - This is mutable operational memory for IFT counters, recent runs, and
#   transaction-related history.
# -----------------------------------------------------------------------------
@dataclass
class AppState:
    """Persisted application state."""

    month: str

    # Monthly IFT tracking
    ift_count_this_month: int = 0

    # Most recent lifecycle timestamps
    last_ift_date: str | None = None
    last_run_date: str | None = None

    # Recent history for UI and diagnostics
    recent_regimes: list[str] = field(default_factory=list)
    recent_scores: list[int] = field(default_factory=list)
    recent_allocations: list[FundsAlloc] = field(default_factory=list)

    # Optional rerun / idempotency guard
    last_confirmation_key: str | None = None


# -----------------------------------------------------------------------------
# Optional transaction record contract
# -----------------------------------------------------------------------------
# If you formalize audit rows later, this dataclass can be used by storage.py
# and the transaction log. It is included here because the architecture notes
# mention transaction records as a likely extension point.
# -----------------------------------------------------------------------------
@dataclass
class TransactionRecord:
    """Audit record for confirmed IFT or safety actions."""

    timestamp: datetime
    action_type: str
    regime: str
    from_alloc: FundsAlloc
    to_alloc: FundsAlloc
    ift_count_after: int
    snapshot_hash: str = ""
    notes: str = ""


__all__ = [
    "FundsAlloc",
    "Scores",
    "MarketData",
    "MarketState",
    "EngineResult",
    "Config",
    "AppState",
    "TransactionRecord",
]
