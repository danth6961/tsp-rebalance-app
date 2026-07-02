"""
Author: Donald J Anthony
Date: 2026-07-02

app.py — Streamlit orchestration layer.

Owns:
    - Page layout
    - Sidebar controls
    - Fetch/run flow
    - Rendering
    - Manual confirmation wiring

Does not own:
    - Scoring logic
    - Persistence internals
    - Data acquisition
    - CSS definitions
    - Regime definitions

This module sets up the Streamlit page, handles user inputs, fetches market data,
orchestrates the engine execution, and renders the results. It pulls configuration,
state, and constants from external modules for a modular architecture.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Dict, List, Tuple

import pandas as pd
import streamlit as st

from constants import (
    BASELINE_ALLOCATIONS,
    DEFAULTS,
    LOG_FILE,
    PROXIES,
    REGIME_ORDER,
    TRANSACTION_FILE,
)
from data_sources import fetch_ytd_return, get_cached_proxy_df, get_market_snapshot
from engine import (
    build_engine_result,
    cumulative_alloc_drift,
    latest_regime_from_history,
    should_use_tsp_ift,
)
from ift_state_machine import IFTStateMachine
from storage import (
    append_log_row,
    default_state,
    load_config,
    load_state_for_today,
    save_config,
    save_state,
)
from styles import inject_styles
from ui import (
    make_alloc_chart,
    make_score_chart,
    recent_state_cards,
    render_decision_breakdown,
    render_editable_metric_tile,
    render_history_table,
    render_metric_cards,
    render_regime_cards,
    render_snapshot_quality_badge,
    render_tile_grid,
)
from utils import compute_snapshot_quality, get_est_now
from validation import validate_market_data

# -----------------------------------------------------------------------------
# Streamlit page configuration and session setup
# -----------------------------------------------------------------------------

st.set_page_config(
    page_title="TSP Rebalance Engine",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# -----------------------------------------------------------------------------
# Editable market fields for session state.
# -----------------------------------------------------------------------------
EDITABLE_KEYS: List[str] = [
    "core_pce_yoy",
    "ism_pmi",
    "services_pmi",
    "initial_claims",
    "breakeven_inflation",
    "fed_assets_growth_yoy",
    "real_yield_10y",
    "move_index",
    "sloos_net_pct",
    "hy_oas",
    "shiller_cape",
    "fwd_eps_growth_yoy",
    "stlfsi_index",
    "bond_yield_10y",
    "bond_yield_3m",
    "market_breadth_pct",
    "vix_spot",
    "dxy_spot",
    "spx_spot",
    "pct_dist_200_sma",
    "drawdown_pct",
    "treasury_10y_3m_spread",
    "inflation_shock",
    "central_bank_stance",
    "liquidity_pressure",
    "dxy_sma_5",
    "dxy_sma_20",
    "dxy_trend_up",
    "dxy_range_regime",
]

BOOLEAN_KEYS: set[str] = {"dxy_trend_up"}
TEXT_KEYS: set[str] = {"dxy_range_regime"}


def init_session(cfg: Dict[str, Any]) -> None:
    """
    Initialize Streamlit session state with editable market inputs and related keys.

    The function sets defaults for each indicator in the session state so that
    user edits persist across Streamlit reruns.
    
    Args:
        cfg (Dict[str, Any]): Configuration dictionary loaded from persistent storage.
    """
    # Combine preset editable keys with additional calculated items.
    indicators: List[str] = EDITABLE_KEYS + [
        "vix_3d_panic",
        "spx_3d_panic",
        "vix_last_3",
        "spx_dist_last_3",
    ]

    # Initialize each indicator only if not already set.
    for key in indicators:
        if key not in st.session_state:
            if key in {"vix_3d_panic", "spx_3d_panic"}:
                st.session_state[key] = False
            elif key in {"vix_last_3", "spx_dist_last_3"}:
                st.session_state[key] = []
            elif key in BOOLEAN_KEYS:
                st.session_state[key] = bool(cfg.get(key, False))
            elif key in TEXT_KEYS:
                st.session_state[key] = str(cfg.get(key, "UNKNOWN"))
            else:
                st.session_state[key] = float(cfg.get(key, DEFAULTS.get(key, 0.0)))

        # Set the source for each key if it hasn't been initialized.
        if f"{key}_source" not in st.session_state:
            st.session_state[f"{key}_source"] = "CONFIG/DEFAULT"

    # Initialize additional session state fields.
    st.session_state.setdefault("engine_ran", False)
    st.session_state.setdefault("last_engine_result", None)
    st.session_state.setdefault("live_market_data", {})
    st.session_state.setdefault("live_market_sources", {})
    st.session_state.setdefault("market_data_warnings", [])


def get_current_market_sources() -> Dict[str, str]:
    """
    Retrieve the current source labels for all editable market fields.

    Returns:
        Dict[str, str]: Mapping of market field keys to their assigned source label.
    """
    source_keys: List[str] = EDITABLE_KEYS + ["vix_3d_panic", "spx_3d_panic"]
    return {key: st.session_state.get(f"{key}_source", "CONFIG/DEFAULT") for key in source_keys}


def load_editable_market_data() -> Dict[str, Any]:
    """
    Assemble the market data payload by reading from the session state.

    Returns:
        Dict[str, Any]: Dictionary of market indicators, ensuring correct type conversions.
    """
    market: Dict[str, Any] = {}
    for key in EDITABLE_KEYS:
        if key in BOOLEAN_KEYS:
            market[key] = bool(st.session_state.get(key, False))
        elif key in TEXT_KEYS:
            market[key] = str(st.session_state.get(key, "UNKNOWN"))
        else:
            market[key] = st.session_state.get(key, DEFAULTS.get(key, 0.0))

    # Add additional fields that may not be part of EDITABLE_KEYS.
    market["vix_3d_panic"] = bool(st.session_state.get("vix_3d_panic", False))
    market["spx_3d_panic"] = bool(st.session_state.get("spx_3d_panic", False))
    market["vix_last_3"] = st.session_state.get("vix_last_3", [])
    market["spx_dist_last_3"] = st.session_state.get("spx_dist_last_3", [])
    return market


def _render_market_snapshot_controls() -> None:
    """
    Render interactive controls for editing the market snapshot.

    This function lays out the editable cards for each market indicator, applying the
    same aesthetic styling across all cards.
    """
    st.markdown("### Market Snapshot")
    st.caption("Editable market inputs with the same card aesthetic.")

    # Render a quality badge to indicate the source quality of current data.
    render_snapshot_quality_badge(
        compute_snapshot_quality(get_current_market_sources()),
        st.session_state.get("engine_ran", False),
    )

    # Define a mapping for each market indicator to be displayed.
    market_edit_items: List[Tuple[str, str, str]] = [
        ("Core PCE YoY", "core_pce_yoy", st.session_state.get("core_pce_yoy_source")),
        ("ISM Manufacturing PMI", "ism_pmi", st.session_state.get("ism_pmi_source")),
        ("ISM Services PMI", "services_pmi", st.session_state.get("services_pmi_source")),
        ("Initial Claims (K)", "initial_claims", st.session_state.get("initial_claims_source")),
        ("10Y Breakeven Inflation", "breakeven_inflation", st.session_state.get("breakeven_inflation_source")),
        ("Fed Assets Growth YoY", "fed_assets_growth_yoy", st.session_state.get("fed_assets_growth_yoy_source")),
        ("10Y Real Yield", "real_yield_10y", st.session_state.get("real_yield_10y_source")),
        ("MOVE Volatility", "move_index", st.session_state.get("move_index_source")),
        ("SLOOS Net %", "sloos_net_pct", st.session_state.get("sloos_net_pct_source")),
        ("HY OAS", "hy_oas", st.session_state.get("hy_oas_source")),
        ("Shiller CAPE", "shiller_cape", st.session_state.get("shiller_cape_source")),
        ("Fwd EPS Growth YoY", "fwd_eps_growth_yoy", st.session_state.get("fwd_eps_growth_yoy_source")),
        ("VIX Spot", "vix_spot", st.session_state.get("vix_spot_source")),
        ("SPX vs 200SMA %", "pct_dist_200_sma", "DERIVED"),
        ("Drawdown %", "drawdown_pct", "DERIVED"),
        ("STLFSI", "stlfsi_index", st.session_state.get("stlfsi_index_source")),
        ("10Y Yield", "bond_yield_10y", st.session_state.get("bond_yield_10y_source")),
        ("3M Yield", "bond_yield_3m", st.session_state.get("bond_yield_3m_source")),
        ("10Y-3M Spread", "treasury_10y_3m_spread", "DERIVED"),
        ("Inflation Shock", "inflation_shock", "DERIVED"),
        ("Central Bank Stance", "central_bank_stance", "DERIVED"),
        ("Liquidity Pressure", "liquidity_pressure", "DERIVED"),
        ("DXY Spot", "dxy_spot", st.session_state.get("dxy_spot_source")),
        ("DXY SMA 5", "dxy_sma_5", st.session_state.get("dxy_sma_5_source")),
        ("DXY SMA 20", "dxy_sma_20", st.session_state.get("dxy_sma_20_source")),
        ("DXY Trend Up", "dxy_trend_up", st.session_state.get("dxy_trend_up_source")),
        ("DXY Range Regime", "dxy_range_regime", st.session_state.get("dxy_range_regime_source")),
        ("Breadth %", "market_breadth_pct", st.session_state.get("market_breadth_pct_source")),
        ("SPX Spot", "spx_spot", st.session_state.get("spx_spot_source")),
    ]

    # Create a grid of columns (4 per row) to display the cards.
    cols = st.columns(4)
    for i, (label, key, source) in enumerate(market_edit_items):
        with cols[i % 4]:
            render_editable_metric_tile(
                label=label,
                value=st.session_state.get(
                    key,
                    False if key in BOOLEAN_KEYS else "UNKNOWN" if key in TEXT_KEYS else 0.0,
                ),
                source=source,
                key=key,
                step=1.0 if key in BOOLEAN_KEYS else 0.1,
                fmt="%s" if key in BOOLEAN_KEYS or key in TEXT_KEYS else "%.2f",
                color="#3b82f6",
            )


def _load_market_snapshot(fred_api_key: str, use_live_macro: bool) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """
    Fetch market data from live sources, or return default values if fetching fails.

    Args:
        fred_api_key (str): API key for live data access.
        use_live_macro (bool): Flag to determine whether to use live macro data.

    Returns:
        Tuple[Dict[str, Any], Dict[str, str]]: A tuple containing the market data and the data sources.
    """
    try:
        # Attempt to fetch live market snapshot using FRED key if instructed.
        snapshot: Dict[str, Any] = get_market_snapshot(fred_api_key if use_live_macro else "")
        fetched_data: Dict[str, Any] = snapshot["market_data"]
        fetched_sources: Dict[str, str] = snapshot["market_sources"]
    except Exception:
        # Fall back to default values if any error occurs.
        fetched_data = {k: DEFAULTS.get(k, 0.0) for k in DEFAULTS.keys()}
        fetched_data["vix_3d_panic"] = False
        fetched_data["spx_3d_panic"] = False
        fetched_data["vix_last_3"] = []
        fetched_data["spx_dist_last_3"] = []
        fetched_sources = {k: "CONFIG/DEFAULT" for k in fetched_data.keys()}
    return fetched_data, fetched_sources


def _sync_session_with_snapshot(fetched_data: Dict[str, Any], fetched_sources: Dict[str, str]) -> None:
    """
    Sync the fetched market snapshot into the Streamlit session state.

    Args:
        fetched_data (Dict[str, Any]): Market indicator values fetched.
        fetched_sources (Dict[str, str]): Data source labels for each market indicator.
    """
    st.session_state["live_market_data"] = fetched_data
    st.session_state["live_market_sources"] = fetched_sources

    # Sync individual editable keys.
    for key in EDITABLE_KEYS:
        if key in BOOLEAN_KEYS:
            st.session_state[key] = bool(fetched_data.get(key, False))
        elif key in TEXT_KEYS:
            st.session_state[key] = str(fetched_data.get(key, "UNKNOWN"))
        else:
            st.session_state[key] = float(fetched_data.get(key, DEFAULTS.get(key, 0.0)))
        st.session_state[f"{key}_source"] = fetched_sources.get(key, "CONFIG/DEFAULT")

    # Sync additional fields that are not in EDITABLE_KEYS.
    st.session_state["vix_3d_panic"] = bool(fetched_data.get("vix_3d_panic", False))
    st.session_state["spx_3d_panic"] = bool(fetched_data.get("spx_3d_panic", False))
    st.session_state["vix_last_3"] = fetched_data.get("vix_last_3", [])
    st.session_state["spx_dist_last_3"] = fetched_data.get("spx_dist_last_3", [])
    st.session_state["engine_ran"] = True


def _build_snapshot_log_row(
    today: date,
    action: str,
    reason: str,
    state: Dict[str, Any],
    current_alloc: Dict[str, float],
    result: Any,
    market_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Construct the log row to be appended to the daily run log file.

    Args:
        today (date): The current run date.
        action (str): The action taken (e.g., "SUBMIT IFT" or "HOLD").
        reason (str): The reason for the chosen action.
        state (Dict[str, Any]): The current state of the engine.
        current_alloc (Dict[str, float]): The current allocation percentages.
        result (Any): The result from the engine execution that contains regime and scores.
        market_data (Dict[str, Any]): The market snapshot used.

    Returns:
        Dict[str, Any]: Log row ready for CSV persistence.
    """
    return {
        "date": today.isoformat(),
        "action": action,
        "reason": reason,
        "regime": result.regime,
        "total_score": result.composite_score,
        "ift_count_this_month": state.get("ift_count_this_month", 0),
        "current_alloc": json.dumps(current_alloc),
        "target_alloc": json.dumps(result.allocations),
        "vix": market_data.get("vix_spot", DEFAULTS["vix_spot"]),
        "spx_200sma_dist": market_data.get("pct_dist_200_sma", 0.0),
        "drawdown_pct": market_data.get("drawdown_pct", 0.0),
    }


def main() -> None:
    """
    Main entrypoint for the Streamlit application.

    This function orchestrates the following:
        - Injecting custom styles.
        - Loading configuration and state.
        - Initializing session state.
        - Defining sidebar controls for configuration and manual override.
        - Fetching and syncing live market data.
        - Executing the engine to compute current regime, scores, and allocation drift.
        - Rendering the metrics, historical charts, and logs.
    """
    inject_styles()

    # Load persistent configuration and current state.
    cfg: Dict[str, Any] = load_config()
    today: date = date.today()
    state: Dict[str, Any] = load_state_for_today(today)
    init_session(cfg)

    # ---------------------------
    # Sidebar controls
    # ---------------------------
    with st.sidebar:
        st.markdown("## 🏛️ TSP Rebalance Engine")

        # Current allocation editing control.
        with st.expander("💼 Current Allocation", expanded=False):
            neutral: Dict[str, float] = BASELINE_ALLOCATIONS["OPTIMIZED NEUTRAL"]
            st.caption(
                "Startup allocation is set to the tactical neutral baseline: "
                f"G {neutral['G']} / C {neutral['C']} / I {neutral['I']} / S {neutral['S']} / F {neutral['F']}."
            )
            current_alloc: Dict[str, float] = {
                "G": st.number_input(
                    "G Fund %",
                    min_value=0.0,
                    max_value=100.0,
                    value=float(cfg["current_alloc"]["G"]),
                    step=1.0,
                ),
                "C": st.number_input(
                    "C Fund %",
                    min_value=0.0,
                    max_value=100.0,
                    value=float(cfg["current_alloc"]["C"]),
                    step=1.0,
                ),
                "I": st.number_input(
                    "I Fund %",
                    min_value=0.0,
                    max_value=100.0,
                    value=float(cfg["current_alloc"]["I"]),
                    step=1.0,
                ),
                "S": st.number_input(
                    "S Fund %",
                    min_value=0.0,
                    max_value=100.0,
                    value=float(cfg["current_alloc"]["S"]),
                    step=1.0,
                ),
                "F": st.number_input(
                    "F Fund %",
                    min_value=0.0,
                    max_value=100.0,
                    value=float(cfg["current_alloc"]["F"]),
                    step=1.0,
                ),
            }

        # Warn if the current allocation does not sum to 100%
        total_alloc: float = sum(current_alloc.values())
        if abs(total_alloc - 100.0) > 0.5:
            st.warning(f"Current allocation totals {total_alloc:.1f}%. Expected 100.0%.")

        # Rules and live macro-data controls.
        with st.expander("🛡️ Rules", expanded=False):
            allow_second_ift: bool = st.checkbox("Allow second IFT", value=bool(cfg["allow_second_ift"]))
            normal_drift_threshold_pct: float = st.number_input(
                "Normal drift threshold %",
                value=float(cfg["normal_drift_threshold_pct"]),
                step=0.5,
            )
            score_change_threshold: int = st.number_input(
                "Score change threshold",
                value=int(cfg["score_change_threshold"]),
                step=1,
            )
            confirmation_days: int = st.number_input(
                "Confirmation days",
                value=int(cfg["confirmation_days"]),
                step=1,
            )
            cooldown_days: int = st.number_input(
                "Cooldown days",
                value=int(cfg["cooldown_days"]),
                step=1,
            )
            use_live_macro: bool = st.checkbox("Use live macro data", value=bool(cfg["use_live_macro"]))

        # Manual override controls.
        with st.expander("🛠️ Manual Override", expanded=False):
            manual_override_enabled: bool = st.checkbox(
                "Enable manual override", value=bool(cfg["manual_override_enabled"])
            )
            manual_regime_default: str = str(cfg.get("manual_regime", "OPTIMIZED NEUTRAL"))
            manual_regime_index: int = (
                REGIME_ORDER.index(manual_regime_default) if manual_regime_default in REGIME_ORDER else 1
            )
            manual_regime: str = st.selectbox("Override regime", REGIME_ORDER, index=manual_regime_index)

        st.divider()
        fred_api_key: str = st.text_input("FRED API Key", value=str(cfg.get("fred_api_key", "")), type="password")

        st.divider()
        confirm_clicked: bool = st.button("✅ Submit IFT", use_container_width=True, disabled=not st.session_state.get("engine_ran", False))
        st.divider()
        save_clicked: bool = st.button("💾 Save Config", use_container_width=True)
        reset_state_clicked: bool = st.button("♻️ Reset State", use_container_width=True)
        clear_logs_clicked: bool = st.button("🗑️ Clear Log File", use_container_width=True)
        clear_tx_clicked: bool = st.button("🗑️ Clear Audit Trail", use_container_width=True)
        st.divider()
        run_clicked: bool = st.button("🚀 Fetch & Run Engine", use_container_width=True, type="primary")

    # ---------------------------
    # Sidebar action handlers
    # ---------------------------
    if save_clicked:
        cfg["current_alloc"] = current_alloc
        cfg["allow_second_ift"] = allow_second_ift
        cfg["normal_drift_threshold_pct"] = float(normal_drift_threshold_pct)
        cfg["score_change_threshold"] = int(score_change_threshold)
        cfg["confirmation_days"] = int(confirmation_days)
        cfg["cooldown_days"] = int(cooldown_days)
        cfg["use_live_macro"] = bool(use_live_macro)
        cfg["manual_override_enabled"] = bool(manual_override_enabled)
        cfg["manual_regime"] = manual_regime
        cfg["fred_api_key"] = fred_api_key

        # Save each editable market variable from session state into config.
        for key in EDITABLE_KEYS:
            cfg[key] = st.session_state.get(key, DEFAULTS.get(key, 0.0))
        save_config(cfg)
        st.sidebar.success("Config saved.")
        st.rerun()

    if reset_state_clicked:
        save_state(
            {
                "month": today.strftime("%Y-%m"),
                "ift_count_this_month": 0,
                "last_ift_date": None,
                "last_run_date": None,
                "recent_regimes": [],
                "recent_scores": [],
                "recent_allocations": [],
                "recent_run_dates": [],
                "last_confirmation_key": None,
            }
        )
        st.session_state["last_engine_result"] = None
        st.session_state["engine_ran"] = False
        st.rerun()

    if clear_logs_clicked:
        if LOG_FILE.exists():
            LOG_FILE.unlink()
        st.rerun()

    if clear_tx_clicked:
        if TRANSACTION_FILE.exists():
            TRANSACTION_FILE.unlink()
        st.rerun()

    # ---------------------------
    # Fetch and run the engine flow
    # ---------------------------
    if run_clicked:
        with st.spinner("Connecting to live feeds..."):
            fetched_data, fetched_sources = _load_market_snapshot(fred_api_key, bool(use_live_macro))
            _sync_session_with_snapshot(fetched_data, fetched_sources)

        market_data: Dict[str, Any] = load_editable_market_data()
        range_warnings: List[str] = validate_market_data(market_data)
        st.session_state["market_data_warnings"] = range_warnings

        # Build engine result based on live market data and override settings.
        result = build_engine_result(
            market_data,
            override_active=bool(manual_override_enabled),
            override_regime=str(manual_regime),
            previous_regime=latest_regime_from_history(state.get("recent_regimes")),
        )
        st.session_state["last_engine_result"] = result

        # Determine last IFT date if available.
        last_ift_date: Any = date.fromisoformat(state["last_ift_date"]) if state.get("last_ift_date") else None

        # Decide whether to submit an IFT based on drift and other criteria.
        use_ift, reason = should_use_tsp_ift(
            today=today,
            current_alloc=current_alloc,
            target_alloc=result.allocations,
            recent_regimes=state.get("recent_regimes", []),
            recent_scores=state.get("recent_scores", []),
            emergency_triggered=result.emergency_triggered,
            ift_count_this_month=int(state.get("ift_count_this_month", 0)),
            last_ift_date=last_ift_date,
            allow_second_ift=bool(allow_second_ift),
            normal_drift_threshold_pct=float(normal_drift_threshold_pct),
            score_change_threshold=int(score_change_threshold),
            confirmation_days=int(confirmation_days),
            cooldown_days=int(cooldown_days),
        )

        action: str = "SUBMIT IFT" if use_ift else "HOLD"

        # Update state history with the latest engine result.
        state.setdefault("recent_regimes", [])
        state.setdefault("recent_scores", [])
        state.setdefault("recent_allocations", [])
        state.setdefault("recent_run_dates", [])

        state["recent_regimes"].append(result.regime)
        state["recent_scores"].append(result.composite_score)
        state["recent_allocations"].append(result.allocations)
        state["recent_run_dates"].append(today.isoformat())
        state["last_run_date"] = today.isoformat()
        save_state(state)

        append_log_row(
            _build_snapshot_log_row(
                today=today,
                action=action,
                reason=reason,
                state=state,
                current_alloc=current_alloc,
                result=result,
                market_data=market_data,
            )
        )

    # ---------------------------
    # Rendering flow: Prepare current result and render display components.
    # ---------------------------
    market_data = load_editable_market_data()
    result = st.session_state.get("last_engine_result")
    # Build an engine result if one is not available in the session state.
    if result is None:
        result = build_engine_result(
            market_data,
            override_active=bool(cfg.get("manual_override_enabled", False)),
            override_regime=str(cfg.get("manual_regime", "OPTIMIZED NEUTRAL")),
            previous_regime=latest_regime_from_history(state.get("recent_regimes")),
        )

    last_ift_date = date.fromisoformat(state["last_ift_date"]) if state.get("last_ift_date") else None
    use_ift, reason = should_use_tsp_ift(
        today=today,
        current_alloc=current_alloc,
        target_alloc=result.allocations,
        recent_regimes=state.get("recent_regimes", []),
        recent_scores=state.get("recent_scores", []),
        emergency_triggered=result.emergency_triggered,
        ift_count_this_month=int(state.get("ift_count_this_month", 0)),
        last_ift_date=last_ift_date,
        allow_second_ift=bool(allow_second_ift),
        normal_drift_threshold_pct=float(normal_drift_threshold_pct),
        score_change_threshold=int(score_change_threshold),
        confirmation_days=int(confirmation_days),
        cooldown_days=int(cooldown_days),
    )
    action = "SUBMIT IFT" if use_ift else "HOLD"

    # Confirm IFT submission if the corresponding button is clicked.
    if confirm_clicked:
        machine: IFTStateMachine = IFTStateMachine.load(today)
        decision = machine.confirm(
            current_alloc=current_alloc,
            target_alloc=result.allocations,
            regime=result.regime,
            confirmation_key=f"{today.isoformat()}::{result.regime}",
        )
        if decision.allowed:
            st.sidebar.success(decision.reason)
        else:
            st.sidebar.warning(decision.reason)
        st.rerun()

    # Render the top-level metric cards.
    render_metric_cards(
        result.composite_score,
        result.regime,
        action,
        int(state.get("ift_count_this_month", 0)),
        reason,
    )

    # Define layout tabs for different visualization components.
    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        ["📈 Allocation", "🧠 Factors", "📊 Proxy Charts", "🕒 History", "📁 Logs & State"]
    )

    # ---------------------------
    # Tab 1: Allocation and regime overview.
    # ---------------------------
    with tab1:
        est_now: datetime = get_est_now()
        if est_now.hour >= 12:
            st.warning(f"⚠️ Noon cutoff exceeded. Current time: {est_now.strftime('%I:%M %p')}")
        else:
            st.info(f"🕒 Execution window open. Current time: {est_now.strftime('%I:%M %p')}")

        if bool(cfg.get("manual_override_enabled", False)):
            st.warning(
                f"🛠️ Regime Lock Active: engine is bypassed; allocations are locked to {cfg.get('manual_regime')}."
            )

        cum_drift: float = cumulative_alloc_drift(current_alloc, result.allocations)
        st.markdown("### 🎚️ Portfolio Drift Runway")
        c1, c2 = st.columns([1, 3])
        with c1:
            st.metric(
                "Cumulative Portfolio Drift",
                f"{cum_drift:.2f}%",
                f"{cum_drift - float(normal_drift_threshold_pct):+.2f}% vs Threshold",
            )
        with c2:
            st.write(
                f"**Rebalance Threshold Progress**: `{cum_drift:.2f}%` / `{float(normal_drift_threshold_pct):.2f}%` required."
            )
            st.progress(
                min(cum_drift / float(normal_drift_threshold_pct), 1.0)
                if float(normal_drift_threshold_pct) > 0
                else 1.0
            )

        st.markdown("### Allocation Comparison")
        st.dataframe(
            make_alloc_chart(result.allocations, current_alloc),
            use_container_width=True,
            hide_index=True,
        )
        render_regime_cards(result.regime)

    # ---------------------------
    # Tab 2: Factor Scores and breakdown.
    # ---------------------------
    with tab2:
        st.markdown("### Factor Scores")
        factor_items: List[Dict[str, Any]] = []
        for key, label in [
            ("inflation", "Inflation"),
            ("growth", "Growth"),
            ("liquidity", "Liquidity"),
            ("credit_spreads", "Credit Spreads"),
            ("valuation", "Valuation"),
            ("market_stress", "Market Stress"),
            ("momentum", "Momentum"),
            ("drawdown", "Drawdown"),
            ("yield_curve", "Yield Curve"),
            ("inflation_shock", "Inflation Shock"),
            ("central_bank", "Central Bank"),
            ("liquidity_pressure", "Liquidity Pressure"),
        ]:
            value = result.scores.get(key, 0)
            factor_items.append(
                {
                    "label": label,
                    "value": str(value),
                    "note": "Factor contribution",
                    "color": "#16a34a" if value > 0 else "#dc2626" if value < 0 else "#64748b",
                    "icon": "▲" if value > 0 else "▼" if value < 0 else "●",
                }
            )
        render_tile_grid(factor_items, columns=4)

        # Render the market snapshot controls within Tab 2.
        _render_market_snapshot_controls()

        render_decision_breakdown(
            result=result,
            action=action,
            reason=reason,
            state=state,
            current_alloc=current_alloc,
            dxy_range_regime=str(st.session_state.get("dxy_range_regime", "UNKNOWN")),
            dxy_trend_up=bool(st.session_state.get("dxy_trend_up", False)),
            cooldown_days=int(cooldown_days),
            confirmation_days=int(confirmation_days),
            allow_second_ift=bool(allow_second_ift),
            normal_drift_threshold_pct=float(normal_drift_threshold_pct),
            score_change_threshold=int(score_change_threshold),
        )

    # ---------------------------
    # Tab 3: Proxy charts for TSP funds.
    # ---------------------------
    with tab3:
        st.markdown("### Live TSP Fund Proxy Price Tracking")
        st.write("Proxy ETFs are used because TSP funds do not have direct tickers.")

        st.markdown("#### YTD Performance Overview")
        ytd_cols = st.columns(5)
        fund_short_names = [
            "C Fund (S&P 500)",
            "S Fund (Mid/Small)",
            "I Fund (Intl ACWX)",
            "F Fund (Bonds)",
            "G Fund (T-Bills)",
        ]

        # Show YTD returns for each proxy in the sidebar.
        for idx, (fund_label, ticker) in enumerate(PROXIES.items()):
            with ytd_cols[idx]:
                ytd_val = fetch_ytd_return(ticker)
                st.metric(
                    label=f"{fund_short_names[idx]} ({ticker})",
                    value=f"{ytd_val:+.2f}%" if ytd_val is not None else "N/A",
                )

        st.markdown("---")
        col_chart_1, col_chart_2 = st.columns([1, 3])
        with col_chart_1:
            fund_selected = st.selectbox("Select TSP Fund to Plot", options=list(PROXIES.keys()))
            timeframe_selected = st.selectbox(
                "Select Performance Chart Timeframe",
                options=["1 Month", "3 Months", "6 Months", "1 Year", "5 Years", "10 Years"],
                index=5,
            )

        ticker = PROXIES[fund_selected]
        period_map: Dict[str, str] = {
            "1 Month": "1mo",
            "3 Months": "3mo",
            "6 Months": "6mo",
            "1 Year": "1y",
            "5 Years": "5y",
            "10 Years": "10y",
        }
        proxy_df = get_cached_proxy_df(ticker, period_map[timeframe_selected])
        if not proxy_df.empty:
            with col_chart_2:
                st.line_chart(proxy_df.set_index("Date")["Price"])
        else:
            st.error(f"Failed to fetch market data for proxy ticker: {ticker}.")

    # ---------------------------
    # Tab 4: Historical score chart.
    # ---------------------------
    with tab4:
        st.markdown("### Score History")
        score_df = make_score_chart(state)
        if score_df is not None:
            st.line_chart(score_df)
        else:
            st.info("No score history yet.")

    # ---------------------------
    # Tab 5: Logs, recent state, and audit trail.
    # ---------------------------
    with tab5:
        st.markdown("### Recent State Overview")
        recent_state_cards(state)

        st.markdown("### Run History Log")
        render_history_table(state)

        st.markdown("---")
        st.markdown("### Transaction History (Audit Trail)")
        if TRANSACTION_FILE.exists():
            tx_df = pd.read_csv(TRANSACTION_FILE).tail(25)
            tx_df = tx_df.rename(
                columns={
                    "date": "Date",
                    "regime": "Regime",
                    "from_G": "From G Fund",
                    "from_C": "From C Fund",
                    "from_I": "From I Fund",
                    "from_S": "From S Fund",
                    "from_F": "From F Fund",
                    "to_G": "To G Fund",
                    "to_C": "To C Fund",
                    "to_I": "To I Fund",
                    "to_S": "To S Fund",
                    "to_F": "To F Fund",
                }
            )
            st.dataframe(tx_df, use_container_width=True, hide_index=True)
        else:
            st.info("No physical portfolio transactions recorded yet.")

        st.markdown("---")
        st.markdown("### Daily Run Log Viewer")
        if LOG_FILE.exists():
            log_df = pd.read_csv(LOG_FILE)
            st.dataframe(log_df.tail(25), use_container_width=True, hide_index=True)

            export_col1, export_col2, export_col3 = st.columns(3)
            with export_col1:
                st.download_button(
                    "Download Log CSV",
                    data=log_df.to_csv(index=False).encode("utf-8"),
                    file_name="tsp_daily_log.csv",
                    mime="text/csv",
                )
            with export_col2:
                st.download_button(
                    "Download Log JSON",
                    data=log_df.to_json(orient="records", indent=2).encode("utf-8"),
                    file_name="tsp_daily_log.json",
                    mime="application/json",
                )
            with export_col3:
                st.download_button(
                    "Download Latest Snapshot JSON",
                    data=json.dumps(
                        {
                            "market_data": market_data,
                            "market_sources": {k: st.session_state.get(f"{k}_source") for k in market_data.keys()},
                            "factor_scores": result.scores,
                            "regime": result.regime,
                            "total_score": result.composite_score,
                            "action": action,
                            "reason": reason,
                            "current_alloc": current_alloc,
                            "target_alloc": result.allocations,
                            "state": state,
                        },
                        indent=2,
                    ).encode("utf-8"),
                    file_name="tsp_snapshot.json",
                    mime="application/json",
                )
        else:
            st.info("No log file yet.")


if __name__ == "__main__":
    main()
