from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

FundsAlloc = Dict[str, float]
Scores = Dict[str, int]

@dataclass
class MarketData:
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
    vix_3d_panic: bool = False
    spx_3d_panic: bool = False
    vix_last_3: List[float] = field(default_factory=list)
    spx_dist_last_3: List[float] = field(default_factory=list)
    timestamp: Optional[str] = None

@dataclass
class EngineResult:
    allocations: FundsAlloc
    scores: Scores
    composite_score: int
    regime: str
    base_alloc: FundsAlloc
    asymmetric_vol_trigger: bool
    dxy_strong: bool
    emergency_triggered: bool

@dataclass
class Config:
    current_alloc: FundsAlloc
    allow_second_ift: bool = False
    normal_drift_threshold_pct: float = 7.5
    score_change_threshold: int = 3
    confirmation_days: int = 3
    cooldown_days: int = 5
    use_live_macro: bool = True
    fred_api_key: str = ""
    manual_override_enabled: bool = False
    manual_regime: str = "OPTIMIZED NEUTRAL"
    overrides: Dict[str, Any] = field(default_factory=dict)

@dataclass
class AppState:
    month: str
    ift_count_this_month: int = 0
    last_ift_date: Optional[str] = None
    last_run_date: Optional[str] = None
    recent_regimes: List[str] = field(default_factory=list)
    recent_scores: List[int] = field(default_factory=list)
    recent_allocations: List[FundsAlloc] = field(default_factory=list)
