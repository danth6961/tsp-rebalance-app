import streamlit as st
from datetime import date
from typing import Dict, Any

from constants import DEFAULTS, BASELINE_ALLOCATIONS, EDITABLE_KEYS, DISPLAY_NAMES
from engine import build_engine_result, should_use_tsp_ift
from storage import (
    load_config,
    save_config,
    load_state,
    save_state,
    append_transaction_row,
)
from data_sources import get_market_snapshot
from ui import (
    render_regime_card,
    render_score_chart,
    render_allocation_chart,
    render_metric_card,
    render_history_table,
)

# ============================================================
# Page setup
# ============================================================

st.set_page_config(
    page_title="TSP Rebalance Engine",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .small-kpi {
        padding: 1rem;
        border-radius: 12px;
        border: 1px solid rgba(148, 163, 184, 0.15);
        background-color: rgba(248, 250, 252, 0.5);
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.04), 0 2px 4px -2px rgba(0, 0, 0, 0.04);
        margin-top: 6px;
        margin-bottom: 0.6rem;
        transition: transform 0.18s ease, box-shadow 0.18s ease;
    }
    .small-kpi:hover {
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.07), 0 4px 6px -4px rgba(0, 0, 0, 0.07);
        transform: translateY(-2px);
    }
    .small-kpi-title {
        font-size: 0.75rem;
        color: #64748b;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        margin-bottom: 0.25rem;
        font-weight: 700;
    }
    .small-kpi-value {
        font-size: 1.2rem;
        font-weight: 800;
        line-height: 1.15;
        word-break: break-word;
    }
    .small-kpi-note {
        font-size: 0.8rem;
        color: #64748b;
        margin-top: 0.15rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ============================================================
# Editable keys
# Keep this synchronized with constants.py, models.py, and data_sources.py
# ============================================================

EDITABLE_KEYS = [
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
    "market_breadth_pct",
    "vix_spot",
    "dxy_spot",
    "spx_spot",
    "pct_dist_200_sma",
    "drawdown_pct",
    # Step 2 additions
    "yield_curve_slope",
    "inflation_trend",
    "labor_trend",
    "vol_term_structure",
    "commodity_shock",
    "earnings_breadth",
]

# ============================================================
# Helpers
# ============================================================

def init_session(cfg: Dict[str, Any]):
    indicators = EDITABLE_KEYS + [
        "vix_3d_panic",
        "spx_3d_panic",
        "vix_last_3",
        "spx_dist_last_3",
    ]

    for key in indicators:
        if key not in st.session_state:
            if key in ["vix_3d_panic", "spx_3d_panic"]:
                st.session_state[key] = False
            elif key in ["vix_last_3", "spx_dist_last_3"]:
                st.session_state[key] = []
            else:
                st.session_state[key] = float(cfg.get(key, DEFAULTS.get(key, 0.0)))

        if f"{key}_source" not in st.session_state:
            st.session_state[f"{key}_source"] = "CONFIG/DEFAULT"

    if "engine_ran" not in st.session_state:
        st.session_state["engine_ran"] = False
    if "live_market_data" not in st.session_state:
        st.session_state["live_market_data"] = {}
    if "live_market_sources" not in st.session_state:
        st.session_state["live_market_sources"] = {}
    if "engine_result" not in st.session_state:
        st.session_state["engine_result"] = None
    if "current_alloc" not in st.session_state:
        st.session_state["current_alloc"] = cfg.get("current_alloc", BASELINE_ALLOCATIONS["OPTIMIZED NEUTRAL"]).copy()

def load_editable_market_data():
    payload = {}
    for k in EDITABLE_KEYS:
        if k in st.session_state:
            payload[k] = st.session_state.get(k, DEFAULTS.get(k, 0.0))
        else:
            payload[k] = DEFAULTS.get(k, 0.0)

    payload["vix_3d_panic"] = st.session_state.get("vix_3d_panic", False)
    payload["spx_3d_panic"] = st.session_state.get("spx_3d_panic", False)
    payload["vix_last_3"] = st.session_state.get("vix_last_3", [])
    payload["spx_dist_last_3"] = st.session_state.get("spx_dist_last_3", [])
    return payload

def confirm_ift_used(today, current_alloc, target_alloc, regime):
    state = load_state()

    if state.get("month") != today.strftime("%Y-%m"):
        state["month"] = today.strftime("%Y-%m")
        state["ift_count_this_month"] = 0
        state["recent_regimes"] = []
        state["recent_scores"] = []
        state["recent_allocations"] = []

    state["ift_count_this_month"] = int(state.get("ift_count_this_month", 0)) + 1
    state["last_ift_date"] = today.isoformat()
    state["last_run_date"] = today.isoformat()

    try:
        append_transaction_row(
            today.isoformat(),
            current_alloc,
            target_alloc,
            regime,
        )
    except Exception as e:
        st.warning(f"IFT transaction log write failed: {e}")

    save_state(state)

def _market_input_card(col, key):
    label = DISPLAY_NAMES.get(key, key.replace("_", " ").title())
    value = st.session_state.get(key, DEFAULTS.get(key, 0.0))
    source = st.session_state.get(f"{key}_source", "CONFIG/DEFAULT")
    with col:
        st.number_input(label, key=key, value=float(value), step=0.1, format="%.2f")
        st.caption(source)

# ============================================================
# Main app
# ============================================================

def main():
    cfg = load_config()
    state = load_state()
    today = date.today()
    init_session(cfg)

    with st.sidebar:
        st.markdown("## 🏛️ TSP Rebalance Engine")

        with st.expander("💼 Current Allocation", expanded=True):
            current_alloc = {
                "G": st.number_input("G Fund %", value=float(cfg["current_alloc"]["G"]), step=1.0),
                "C": st.number_input("C Fund %", value=float(cfg["current_alloc"]["C"]), step=1.0),
                "I": st.number_input("I Fund %", value=float(cfg["current_alloc"]["I"]), step=1.0),
                "S": st.number_input("S Fund %", value=float(cfg["current_alloc"]["S"]), step=1.0),
                "F": st.number_input("F Fund %", value=float(cfg["current_alloc"]["F"]), step=1.0),
            }

        with st.expander("🛡️ Rules", expanded=False):
            allow_second_ift = st.checkbox("Allow second IFT", value=bool(cfg["allow_second_ift"]))
            normal_drift_threshold_pct = st.number_input("Normal drift threshold %", value=float(cfg["normal_drift_threshold_pct"]), step=0.5)
            score_change_threshold = st.number_input("Score change threshold", value=int(cfg["score_change_threshold"]), step=1)
            confirmation_days = st.number_input("Confirmation days", value=int(cfg["confirmation_days"]), step=1)
            cooldown_days = st.number_input("Cooldown days", value=int(cfg["cooldown_days"]), step=1)
            use_live_macro = st.checkbox("Use live macro data", value=bool(cfg["use_live_macro"]))

        with st.expander("⚙️ Manual Regime Override", expanded=False):
            manual_override_enabled = st.checkbox("Enable manual override", value=bool(cfg.get("manual_override_enabled", False)))
            manual_regime = st.selectbox(
                "Manual regime",
                list(BASELINE_ALLOCATIONS.keys()),
                index=list(BASELINE_ALLOCATIONS.keys()).index(cfg.get("manual_regime", "OPTIMIZED NEUTRAL"))
                if cfg.get("manual_regime", "OPTIMIZED NEUTRAL") in BASELINE_ALLOCATIONS
                else 1,
            )

        save_clicked = st.button("💾 Save Config", use_container_width=True)

        if save_clicked:
            cfg["current_alloc"] = current_alloc
            cfg["allow_second_ift"] = allow_second_ift
            cfg["normal_drift_threshold_pct"] = normal_drift_threshold_pct
            cfg["score_change_threshold"] = score_change_threshold
            cfg["confirmation_days"] = confirmation_days
            cfg["cooldown_days"] = cooldown_days
            cfg["use_live_macro"] = use_live_macro
            cfg["manual_override_enabled"] = manual_override_enabled
            cfg["manual_regime"] = manual_regime
            save_config(cfg)
            st.success("Config saved.")

    st.title("TSP Rebalance Engine")
    st.caption("Tactical allocation engine for G, F, C, S, and I funds.")

    # ========================================================
    # Live snapshot
    # ========================================================
    if st.button("🔄 Refresh Live Data", use_container_width=True):
        snap = get_market_snapshot(cfg.get("fred_api_key", ""))
        st.session_state["live_market_data"] = snap.get("market_data", {})
        st.session_state["live_market_sources"] = snap.get("market_sources", {})
        for k, v in st.session_state["live_market_data"].items():
            if k in EDITABLE_KEYS or k in ["vix_3d_panic", "spx_3d_panic", "vix_last_3", "spx_dist_last_3"]:
                st.session_state[k] = v
                st.session_state[f"{k}_source"] = st.session_state["live_market_sources"].get(k, "LIVE")
        st.success("Live market data refreshed.")

    # Pull current working data from session
    market_data = load_editable_market_data()

    # Optional live source display
    with st.expander("📡 Data Source Health", expanded=False):
        if st.session_state.get("live_market_sources"):
            for k in EDITABLE_KEYS:
                src = st.session_state["live_market_sources"].get(k, st.session_state.get(f"{k}_source", "CONFIG/DEFAULT"))
                st.write(f"**{DISPLAY_NAMES.get(k, k)}:** {src}")
        else:
            st.info("No live refresh has been run yet.")

    # ========================================================
    # Engine run
    # ========================================================
    override_regime = cfg.get("manual_regime", "OPTIMIZED NEUTRAL")
    override_active = bool(cfg.get("manual_override_enabled", False))

    engine_result = build_engine_result(
        market_data,
        override_active=override_active,
        override_regime=override_regime,
    )
    st.session_state["engine_result"] = engine_result
    st.session_state["engine_ran"] = True

    allocations = engine_result["allocations"]
    scores = engine_result["scores"]
    composite_score = engine_result["composite_score"]
    regime = engine_result["regime"]
    base_alloc = engine_result["base_alloc"]
    asymmetric_vol_trigger = engine_result["asymmetric_vol_trigger"]
    dxy_strong = engine_result["dxy_strong"]
    emergency_triggered = engine_result["emergency_triggered"]

    # ========================================================
    # Regime cards
    # ========================================================
    st.subheader("Regime Overview")
    regime_cards = [
        {
            "name": "Risk-On Override",
            "profile": "Aggressive growth tilt",
            "score": "Strongly positive",
            "alloc": "G 30 / C 40 / I 25 / S 10 / F 0",
            "desc": "Used when macro, liquidity, and market signals are supportive.",
            "color": "#2563eb",
            "bg": "rgba(37, 99, 235, 0.08)",
            "icon": "🚀",
        },
        {
            "name": "Optimized Neutral",
            "profile": "Balanced tactical stance",
            "score": "Mixed / stable environment",
            "alloc": "G 40 / C 30 / I 20 / S 10 / F 0",
            "desc": "Default balanced posture when signals are not decisive.",
            "color": "#0f766e",
            "bg": "rgba(15, 118, 110, 0.08)",
            "icon": "⚖️",
        },
        {
            "name": "Defensive Allocation",
            "profile": "Capital preservation tilt",
            "score": "Weaker / deteriorating conditions",
            "alloc": "G 70 / C 15 / I 10 / S 5 / F 0",
            "desc": "Used when macro conditions soften or stress rises.",
            "color": "#b45309",
            "bg": "rgba(180, 83, 9, 0.08)",
            "icon": "🛡️",
        },
        {
            "name": "Emergency Dispatch",
            "profile": "Panic protection",
            "score": "High stress / panic",
            "alloc": "G 100 / C 0 / I 0 / S 0 / F 0",
            "desc": "Triggered by panic rules or emergency conditions.",
            "color": "#b91c1c",
            "bg": "rgba(185, 28, 28, 0.08)",
            "icon": "🚨",
        },
    ]

    cols = st.columns(4)
    for c, info in zip(cols, regime_cards):
        render_regime_card(info, is_active=(info["name"].upper() == regime.upper()))

    # ========================================================
    # Summary metrics
    # ========================================================
    st.subheader("Engine Summary")
    m1, m2, m3, m4 = st.columns(4)
    render_metric_card(m1, "Composite Score", str(composite_score), "Final tactical score")
    render_metric_card(m2, "Selected Regime", regime, "Current environment")
    render_metric_card(m3, "Asym Vol Trigger", "Yes" if asymmetric_vol_trigger else "No", "S Fund overlay rule")
    render_metric_card(m4, "DXY Strong", "Yes" if dxy_strong else "No", "I-to-C overlay rule")

    # ========================================================
    # Market snapshot / editable inputs
    # ========================================================
    st.subheader("Market Snapshot Inputs")
    snap_cols = st.columns(3)
    editable_with_labels = EDITABLE_KEYS

    for idx, key in enumerate(editable_with_labels):
        _market_input_card(snap_cols[idx % 3], key)
        if idx % 3 == 2:
            pass

    st.markdown("---")

    # ========================================================
    # Engine details
    # ========================================================
    with st.expander("🔎 Engine Decision Breakdown", expanded=True):
        a, b, c, d = st.columns(4)
        render_metric_card(a, "Base Allocation", f"G {base_alloc['G']:.0f} / C {base_alloc['C']:.0f} / I {base_alloc['I']:.0f} / S {base_alloc['S']:.0f} / F {base_alloc['F']:.0f}", "Pre-overlay base mix")
        render_metric_card(b, "Final Allocation", f"G {allocations['G']:.0f} / C {allocations['C']:.0f} / I {allocations['I']:.0f} / S {allocations['S']:.0f} / F {allocations['F']:.0f}", "After overlays")
        render_metric_card(c, "IFT Decision", "SUBMIT IFT" if should_use_tsp_ift(
            today,
            current_alloc,
            allocations,
            state.get("recent_regimes", []),
            state.get("recent_scores", []),
            emergency_triggered,
            int(state.get("ift_count_this_month", 0)),
            None,
            allow_second_ift,
            normal_drift_threshold_pct,
            score_change_threshold,
            confirmation_days,
            cooldown_days,
        )[0] else "HOLD", "Recommendation only")
        render_metric_card(d, "Emergency Trigger", "Yes" if emergency_triggered else "No", "Panic logic")

        st.markdown("### Factor Scores")
        if scores:
            score_cols = st.columns(4)
            keys = list(scores.keys())
            for idx, key in enumerate(keys):
                render_metric_card(score_cols[idx % 4], key.replace("_", " ").title(), str(scores[key]), "Factor contribution")

    # ========================================================
    # Charts
    # ========================================================
    st.subheader("Charts")
    chart_cols = st.columns(2)
    with chart_cols[0]:
        render_score_chart(st.session_state.get("recent_scores", []))
    with chart_cols[1]:
        render_allocation_chart(allocations)

    # ========================================================
    # IFT workflow
    # ========================================================
    st.subheader("IFT Workflow")
    hold_or_submit, reason = should_use_tsp_ift(
        today,
        current_alloc,
        allocations,
        state.get("recent_regimes", []),
        state.get("recent_scores", []),
        emergency_triggered,
        int(state.get("ift_count_this_month", 0)),
        None,
        allow_second_ift,
        normal_drift_threshold_pct,
        score_change_threshold,
        confirmation_days,
        cooldown_days,
    )

    st.info(f"Decision: {'SUBMIT IFT' if hold_or_submit else 'HOLD'} — {reason}")

    submit_clicked = st.button("✅ Manual Submit IFT", use_container_width=True)
    if submit_clicked:
        confirm_ift_used(today, current_alloc, allocations, regime)
        st.success("IFT recorded.")

    # ========================================================
    # History
    # ========================================================
    st.subheader("Transaction History")
    try:
        history_df = render_history_table()
        st.dataframe(history_df, use_container_width=True)
    except Exception as e:
        st.warning(f"Could not load history: {e}")

    st.markdown("---")
    st.caption("Manual confirmation remains the source of truth for IFT tracking.")

if __name__ == "__main__":
    main()
