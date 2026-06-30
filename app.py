from datetime import date
import json

import pandas as pd
import streamlit as st

from constants import DEFAULTS, PROXIES, LOG_FILE, TRANSACTION_FILE
from data_sources import get_market_snapshot, get_cached_proxy_df, fetch_ytd_return
from engine import build_engine_result, should_use_tsp_ift, cumulative_alloc_drift
from storage import load_state, load_config, save_config, save_state, append_log_row, append_transaction_row
from ui import (
    render_metric_cards,
    make_score_chart,
    make_alloc_chart,
    render_tile_grid,
    recent_state_cards,
    render_history_table,
    render_editable_metric_tile,
)
from utils import get_est_now

st.set_page_config(
    page_title="TSP Rebalance Engine",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
.block-container {
    padding-top: 3rem;
    padding-bottom: 2rem;
    padding-left: 2rem;
    padding-right: 2rem;
    max-width: 1450px;
}
.pill {
    display: inline-block;
    padding: 0.2rem 0.5rem;
    border-radius: 999px;
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    border: 1px solid rgba(148,163,184,0.18);
}
.pill-live { background: #dcfce7; color: #15803d; border-color: #bbf7d0; }
.pill-default { background: #f3f4f6; color: #4b5563; border-color: #e5e7eb; }
.pill-failed { background: #fee2e2; color: #991b1b; border-color: #fca5a5; }
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

EDITABLE_KEYS = [
    "core_pce_yoy", "ism_pmi", "services_pmi", "initial_claims",
    "breakeven_inflation", "fed_assets_growth_yoy", "real_yield_10y",
    "move_index", "sloos_net_pct", "hy_oas", "shiller_cape",
    "fwd_eps_growth_yoy", "stlfsi_index", "bond_yield_10y",
    "market_breadth_pct", "vix_spot", "dxy_spot", "spx_spot",
    "pct_dist_200_sma", "drawdown_pct"
]


def init_session(cfg):
    indicators = EDITABLE_KEYS + ["vix_3d_panic", "spx_3d_panic", "vix_last_3", "spx_dist_last_3"]
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


def render_regime_card(info, is_active: bool):
    border = info["color"] if is_active else "rgba(148,163,184,0.18)"
    bg = info["bg"] if is_active else "rgba(248, 250, 252, 0.5)"
    badge = "★ ACTIVE ENVIRONMENT" if is_active else ""
    badge_color = info["color"] if is_active else "#64748b"

    st.markdown(
        f"""
        <div class="small-kpi" style="border-left: 5px solid {border}; background-color: {bg}; min-height: 250px;">
            <div style="color: {badge_color}; font-weight: 800; font-size: 0.72rem; text-transform: uppercase; margin-bottom: 0.35rem;">{badge}</div>
            <div style="font-weight: 800; font-size: 0.95rem; color: {info['color']};">{info['icon']} {info['name']}</div>
            <div style="font-size: 0.75rem; font-weight: 600; color: #64748b; margin-bottom: 0.6rem;">{info['profile']} • {info['score']}</div>
            <div style="font-size: 0.8rem; font-weight: 700; margin-bottom: 0.6rem; color: {info['color']};">{info['alloc']}</div>
            <div style="font-size: 0.78rem; color: #64748b; line-height: 1.35;">{info['desc']}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def load_editable_market_data():
    return {k: st.session_state.get(k, DEFAULTS.get(k, 0.0)) for k in EDITABLE_KEYS + ["vix_3d_panic", "spx_3d_panic"]}


def is_pure_g_move(target_alloc: dict) -> bool:
    return (
        float(target_alloc.get("G", 0.0)) == 100.0
        and float(target_alloc.get("C", 0.0)) == 0.0
        and float(target_alloc.get("I", 0.0)) == 0.0
        and float(target_alloc.get("S", 0.0)) == 0.0
        and float(target_alloc.get("F", 0.0)) == 0.0
    )


def confirm_ift_used(today, current_alloc, target_alloc, regime):
    state = load_state()

    if state.get("month") != today.strftime("%Y-%m"):
        state["month"] = today.strftime("%Y-%m")
        state["ift_count_this_month"] = 0
        state["recent_regimes"] = []
        state["recent_scores"] = []
        state["recent_allocations"] = []

    current_count = int(state.get("ift_count_this_month", 0))

    # TSP-safe exception: a pure move to G does not consume a monthly IFT.
    if is_pure_g_move(target_alloc):
        state["last_ift_date"] = today.isoformat()
        state["last_run_date"] = today.isoformat()
        save_state(state)
        st.success("G Fund safety move recorded (does not count as a monthly IFT).")
        return

    # Hard stop: never allow more than 2 IFTs in a month.
    if current_count >= 2:
        st.warning("IFT not confirmed: monthly IFT limit of 2 has already been reached.")
        return

    state["ift_count_this_month"] = current_count + 1
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


def main():
    cfg = load_config()
    state = load_state()
    today = date.today()
    init_session(cfg)

    with st.sidebar:
        st.markdown("## 🏛️ TSP Rebalance Engine")

        with st.expander("💼 Current Allocation", expanded=True):
            st.caption("Startup allocation is set to the tactical neutral baseline: G 40 / C 30 / I 20 / S 10 / F 0.")
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

        with st.expander("🛠️ Manual Override", expanded=False):
            manual_override_enabled = st.checkbox("Enable manual override", value=bool(cfg["manual_override_enabled"]))
            manual_regime = st.selectbox(
                "Override regime",
                ["RISK-ON OVERRIDE", "OPTIMIZED NEUTRAL", "DEFENSIVE ALLOCATION", "EMERGENCY DISPATCH"],
                index=["RISK-ON OVERRIDE", "OPTIMIZED NEUTRAL", "DEFENSIVE ALLOCATION", "EMERGENCY DISPATCH"].index(cfg["manual_regime"])
            )

        st.divider()
        secrets_key = ""
        try:
            if "FRED_API_KEY" in st.secrets:
                secrets_key = st.secrets["FRED_API_KEY"]
            elif "fred_api_key" in st.secrets:
                secrets_key = st.secrets["fred_api_key"]
        except Exception:
            pass

        initial_fred_key = secrets_key if secrets_key else str(cfg.get("fred_api_key", ""))
        fred_api_key = st.text_input("FRED API Key", value=initial_fred_key, type="password")

        st.divider()
        confirm_ift_btn = st.button("✅ Submit IFT", use_container_width=True)
        st.caption("After a run, this becomes a G-only safety move when the target is 100% G.")

        st.divider()
        save_cfg = st.button("💾 Save Config", use_container_width=True)
        reset_state_btn = st.button("♻️ Reset State", use_container_width=True)
        clear_logs_btn = st.button("🗑️ Clear Log File", use_container_width=True)
        clear_tx_btn = st.button("🗑️ Clear Audit Trail", use_container_width=True)

        st.divider()
        run = st.button("🚀 Fetch & Run Engine", use_container_width=True, type="primary")

    if save_cfg:
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
        for key in EDITABLE_KEYS:
            cfg[key] = float(st.session_state.get(key, DEFAULTS.get(key, 0.0)))
        save_config(cfg)
        st.sidebar.success("Config saved.")
        st.rerun()

    if reset_state_btn:
        save_state({
            "month": today.strftime("%Y-%m"),
            "ift_count_this_month": 0,
            "last_ift_date": None,
            "last_run_date": None,
            "recent_regimes": [],
            "recent_scores": [],
            "recent_allocations": [],
        })
        st.rerun()

    if clear_logs_btn:
        if LOG_FILE.exists():
            LOG_FILE.unlink()
        st.rerun()

    if clear_tx_btn:
        if TRANSACTION_FILE.exists():
            TRANSACTION_FILE.unlink()
        st.rerun()

    if confirm_ift_btn:
        target_alloc = result["allocations"] if "result" in locals() else current_alloc
        if is_pure_g_move(target_alloc):
            confirm_ift_used(today, current_alloc, target_alloc, "G FUND SAFETY MOVE")
            st.sidebar.success("G Fund safety move recorded.")
        else:
            if int(state.get("ift_count_this_month", 0)) >= 2:
                st.sidebar.warning("Monthly IFT limit reached. Normal IFT submission blocked.")
            else:
                confirm_ift_used(today, current_alloc, target_alloc, "MANUAL IFT")
                st.sidebar.success("IFT confirmed and saved.")
        st.rerun()

    if run:
        with st.spinner("Connecting to live feeds..."):
            try:
                snapshot = get_market_snapshot(fred_api_key if use_live_macro else "")
                fetched_data = snapshot["market_data"]
                fetched_sources = snapshot["market_sources"]
            except Exception:
                fetched_data = {k: float(v) for k, v in DEFAULTS.items()}
                fetched_data["pct_dist_200_sma"] = 0.0
                fetched_data["drawdown_pct"] = 0.0
                fetched_data["vix_3d_panic"] = False
                fetched_data["spx_3d_panic"] = False
                fetched_data["vix_last_3"] = []
                fetched_data["spx_dist_last_3"] = []
                fetched_sources = {k: "CONFIG/DEFAULT" for k in fetched_data.keys()}

            st.session_state["live_market_data"] = fetched_data
            st.session_state["live_market_sources"] = fetched_sources

            for key in EDITABLE_KEYS:
                st.session_state[key] = float(fetched_data.get(key, DEFAULTS.get(key, 0.0)))
                st.session_state[f"{key}_source"] = fetched_sources.get(key, "CONFIG/DEFAULT")

            st.session_state["vix_3d_panic"] = bool(fetched_data.get("vix_3d_panic", False))
            st.session_state["spx_3d_panic"] = bool(fetched_data.get("spx_3d_panic", False))
            st.session_state["vix_last_3"] = fetched_data.get("vix_last_3", [])
            st.session_state["spx_dist_last_3"] = fetched_data.get("spx_dist_last_3", [])
            st.session_state["engine_ran"] = True

        state = load_state()
        if state.get("month") != today.strftime("%Y-%m"):
            state["month"] = today.strftime("%Y-%m")
            state["ift_count_this_month"] = 0
            state["recent_regimes"] = []
            state["recent_scores"] = []
            state["recent_allocations"] = []

        market_data = load_editable_market_data()
        market_data["vix_last_3"] = st.session_state.get("vix_last_3", [])
        market_data["spx_dist_last_3"] = st.session_state.get("spx_dist_last_3", [])

        result = build_engine_result(
            market_data,
            override_active=manual_override_enabled,
            override_regime=manual_regime
        )

        emergency_triggered = result["emergency_triggered"]
        last_ift_date = date.fromisoformat(state["last_ift_date"]) if state.get("last_ift_date") else None

        use_ift, reason = should_use_tsp_ift(
            today=today,
            current_alloc=current_alloc,
            target_alloc=result["allocations"],
            recent_regimes=state["recent_regimes"],
            recent_scores=state["recent_scores"],
            emergency_triggered=emergency_triggered,
            ift_count_this_month=state["ift_count_this_month"],
            last_ift_date=last_ift_date,
            allow_second_ift=allow_second_ift,
            normal_drift_threshold_pct=float(normal_drift_threshold_pct),
            score_change_threshold=int(score_change_threshold),
            confirmation_days=int(confirmation_days),
            cooldown_days=int(cooldown_days),
        )

        action = "SUBMIT IFT" if use_ift else "HOLD"

        if "recent_regimes" not in state:
            state["recent_regimes"] = []
        if "recent_scores" not in state:
            state["recent_scores"] = []
        if "recent_allocations" not in state:
            state["recent_allocations"] = []

        state["recent_regimes"].append(result["regime"])
        state["recent_scores"].append(result["composite_score"])
        state["recent_allocations"].append(result["allocations"])

        state["last_run_date"] = today.isoformat()
        save_state(state)

        append_log_row({
            "date": today.isoformat(),
            "action": action,
            "reason": reason,
            "regime": result["regime"],
            "total_score": result["composite_score"],
            "ift_count_this_month": state["ift_count_this_month"],
            "current_alloc": json.dumps(current_alloc),
            "target_alloc": json.dumps(result["allocations"]),
            "vix": market_data.get("vix_spot", DEFAULTS["vix_spot"]),
            "spx_200sma_dist": market_data.get("pct_dist_200_sma", 0.0),
            "drawdown_pct": market_data.get("drawdown_pct", 0.0),
        })

    market_data = load_editable_market_data()
    market_data["vix_last_3"] = st.session_state.get("vix_last_3", [])
    market_data["spx_dist_last_3"] = st.session_state.get("spx_dist_last_3", [])

    result = build_engine_result(
        market_data,
        override_active=cfg.get("manual_override_enabled", False),
        override_regime=cfg.get("manual_regime", "OPTIMIZED_NEUTRAL")
    )

    last_ift_date = date.fromisoformat(state["last_ift_date"]) if state.get("last_ift_date") else None
    use_ift, reason = should_use_tsp_ift(
        today=today,
        current_alloc=current_alloc,
        target_alloc=result["allocations"],
        recent_regimes=state["recent_regimes"],
        recent_scores=state["recent_scores"],
        emergency_triggered=result["emergency_triggered"],
        ift_count_this_month=state["ift_count_this_month"],
        last_ift_date=last_ift_date,
        allow_second_ift=allow_second_ift,
        normal_drift_threshold_pct=float(normal_drift_threshold_pct),
        score_change_threshold=int(score_change_threshold),
        confirmation_days=int(confirmation_days),
        cooldown_days=int(cooldown_days),
    )

    action = "SUBMIT IFT" if use_ift else "HOLD"

    render_metric_cards(result["composite_score"], result["regime"], action, state["ift_count_this_month"], reason)

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["📈 Allocation", "🧠 Factors", "📊 Proxy Charts", "🕒 History", "📁 Logs & State"])

    with tab1:
        est_now = get_est_now()
        if est_now.hour >= 12:
            st.warning(f"⚠️ Noon cutoff exceeded. Current time: {est_now.strftime('%I:%M %p')}")
        else:
            st.info(f"🕒 Execution window open. Current time: {est_now.strftime('%I:%M %p')}")

        if cfg.get("manual_override_enabled", False):
            st.warning(f"🛠️ Regime Lock Active: engine is bypassed; allocations are locked to {cfg.get('manual_regime')}.")

        cum_drift = cumulative_alloc_drift(current_alloc, result["allocations"])
        st.markdown("### 🎚️ Portfolio Drift Runway")
        c1, c2 = st.columns([1, 3])
        with c1:
            st.metric("Cumulative Portfolio Drift", f"{cum_drift:.2f}%", f"{cum_drift - float(normal_drift_threshold_pct):+.2f}% vs Threshold")
        with c2:
            st.write(f"**Rebalance Threshold Progress**: `{cum_drift:.2f}%` / `{float(normal_drift_threshold_pct):.2f}%` required.")
            st.progress(min(cum_drift / float(normal_drift_threshold_pct), 1.0) if float(normal_drift_threshold_pct) > 0 else 1.0)

        st.markdown("### Allocation Comparison")
        alloc_df = make_alloc_chart(result["allocations"], current_alloc)
        st.dataframe(alloc_df, use_container_width=True, hide_index=True)

        st.markdown("### 🧭 Strategic Regime Directory")
        st.caption("The engine maps the overall composite score to one of the four policy regimes below to determine baseline targets:")

        regimes_info = [
            {
                "name": "RISK-ON OVERRIDE",
                "icon": "🚀",
                "score": "Score: ≥ +5",
                "profile": "Aggressive Profile",
                "alloc": "Base: G 30% / C 40% / I 25% / S 10% / F 0%",
                "desc": "Strong macro backdrop and solid upward momentum.",
                "color": "#10b981",
                "bg": "rgba(16, 185, 129, 0.08)"
            },
            {
                "name": "OPTIMIZED NEUTRAL",
                "icon": "⚖️",
                "score": "Score: 0 to +4",
                "profile": "Balanced Profile",
                "alloc": "Base: G 40% / C 30% / I 20% / S 10% / F 0%",
                "desc": "Default balanced state when signals are constructive but mixed.",
                "color": "#3b82f6",
                "bg": "rgba(59, 130, 246, 0.08)"
            },
            {
                "name": "DEFENSIVE ALLOCATION",
                "icon": "🛡️",
                "score": "Score: < 0",
                "profile": "Defensive Profile",
                "alloc": "Base: G 70% / C 15% / I 10% / S 5% / F 0%",
                "desc": "Used when risk rises or the composite turns negative.",
                "color": "#f59e0b",
                "bg": "rgba(245, 158, 11, 0.08)"
            },
            {
                "name": "EMERGENCY DISPATCH",
                "icon": "🚨",
                "score": "Score: -50",
                "profile": "Maximum Defense",
                "alloc": "Base: G 90% / F 10% (or G 100% / F 0%)",
                "desc": "3-day panic valve breach.",
                "color": "#ef4444",
                "bg": "rgba(239, 68, 68, 0.08)"
            }
        ]

        regime_cols = st.columns(4)
        for idx, info in enumerate(regimes_info):
            with regime_cols[idx]:
                render_regime_card(info, result["regime"] == info["name"])

    with tab2:
        st.markdown("### Factor Scores")
        factor_items = []
        for key, label in [
            ("inflation", "Inflation"),
            ("growth", "Growth"),
            ("liquidity", "Liquidity"),
            ("credit_spreads", "Credit Spreads"),
            ("valuation", "Valuation"),
            ("market_stress", "Market Stress"),
            ("momentum", "Momentum"),
            ("drawdown", "Drawdown"),
        ]:
            val = result["scores"].get(key, 0)
            factor_items.append({
                "label": label,
                "value": str(val),
                "note": "Factor contribution",
                "color": "#16a34a" if val > 0 else "#dc2626" if val < 0 else "#64748b",
                "icon": "▲" if val > 0 else "▼" if val < 0 else "●",
            })
        render_tile_grid(factor_items, columns=4)

        st.markdown("### Market Snapshot")
        st.caption("Editable market inputs with the same card aesthetic.")

        market_edit_items = [
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
            ("DXY Spot", "dxy_spot", st.session_state.get("dxy_spot_source")),
            ("Breadth %", "market_breadth_pct", st.session_state.get("market_breadth_pct_source")),
            ("SPX Spot", "spx_spot", st.session_state.get("spx_spot_source")),
        ]

        cols = st.columns(4)
        for i, (label, key, source) in enumerate(market_edit_items):
            with cols[i % 4]:
                render_editable_metric_tile(
                    label=label,
                    value=st.session_state.get(key, 0.0),
                    source=source,
                    key=key,
                    step=0.1,
                    fmt="%.2f",
                    color="#3b82f6",
                )

        st.markdown("### 🔍 Engine Decision Breakdown")
        with st.expander("📖 Detailed Decision Trace & Factor Attribution", expanded=True):
            st.markdown("#### 1) Decision Summary")

            sum_cols = st.columns(4)
            with sum_cols[0]:
                st.markdown(f"**Regime**  \n{result['regime']}")
            with sum_cols[1]:
                st.markdown(f"**Composite Score**  \n{result['composite_score']:+d}")
            with sum_cols[2]:
                st.markdown(f"**Action**  \n{action}")
            with sum_cols[3]:
                st.markdown(f"**Emergency Trigger**  \n{'Yes' if result['emergency_triggered'] else 'No'}")

            st.caption(f"IFT Decision Reason: {reason}")

            st.markdown("#### 2) Factor Score Detail")
            factor_rules = [
                ("Inflation", "inflation", "Core PCE / Breakevens"),
                ("Growth", "growth", "PMI / Services PMI / Claims"),
                ("Liquidity", "liquidity", "SLOOS / Fed Assets Growth"),
                ("Credit Spreads", "credit_spreads", "HY OAS"),
                ("Valuation", "valuation", "Shiller CAPE / Real Yield"),
                ("Market Stress", "market_stress", "VIX / STLFSI"),
                ("Momentum", "momentum", "200SMA distance / STLFSI"),
                ("Drawdown", "drawdown", "Peak-to-trough decline"),
            ]

            factor_rows = []
            for display_name, score_key, source_text in factor_rules:
                raw_score = int(result["scores"].get(score_key, 0))
                if raw_score >= 3:
                    strength = "Strong Positive"
                elif raw_score > 0:
                    strength = "Mild Positive"
                elif raw_score == 0:
                    strength = "Neutral"
                elif raw_score <= -5:
                    strength = "Strong Negative"
                else:
                    strength = "Negative"

                factor_rows.append({
                    "Factor": display_name,
                    "Raw Score": raw_score,
                    "Interpretation": strength,
                    "Source / Logic": source_text,
                })

            st.dataframe(pd.DataFrame(factor_rows), use_container_width=True, hide_index=True)

            st.markdown("#### 3) Factor Interpretation")
            pos_factors = []
            neg_factors = []
            neu_factors = []

            for key, label in [
                ("inflation", "Inflation"),
                ("growth", "Growth"),
                ("liquidity", "Liquidity"),
                ("credit_spreads", "Credit Spreads"),
                ("valuation", "Valuation"),
                ("market_stress", "Market Stress"),
                ("momentum", "Momentum"),
                ("drawdown", "Drawdown"),
            ]:
                val = result["scores"].get(key, 0)
                if val > 0:
                    pos_factors.append(f"{label} (+{val} pts)")
                elif val < 0:
                    neg_factors.append(f"{label} ({val} pts)")
                else:
                    neu_factors.append(label)

            c1, c2, c3 = st.columns(3)
            with c1:
                st.markdown("**🟢 Positive Drivers**")
                for item in pos_factors or ["None"]:
                    st.markdown(f"- {item}")
            with c2:
                st.markdown("**⚪ Neutral Factors**")
                for item in neu_factors or ["None"]:
                    st.markdown(f"- {item}")
            with c3:
                st.markdown("**🔴 Negative Drags**")
                for item in neg_factors or ["None"]:
                    st.markdown(f"- {item}")

            st.markdown("#### 4) Regime and Allocation Build")

            build_cols = st.columns(2)
            with build_cols[0]:
                st.markdown("**Regime Selection**")
                st.write(f"- Selected regime: `{result['regime']}`")
                st.write(f"- Composite score: `{result['composite_score']:+d}`")
                st.write(f"- Emergency trigger: `{'Yes' if result['emergency_triggered'] else 'No'}`")
                st.write(f"- Base allocation: `{result['base_alloc']}`")

            with build_cols[1]:
                st.markdown("**Adjustment Flags**")
                st.write(f"- F Fund unlocked: `{'Yes' if result['base_alloc'].get('F', 0) > 0 else 'No'}`")
                st.write(f"- Asymmetric volatility trigger: `{'Yes' if result['asymmetric_vol_trigger'] else 'No'}`")
                st.write(f"- Strong DXY adjustment: `{'Yes' if result['dxy_strong'] else 'No'}`")

            st.markdown("**Final Target Allocation**")
            st.dataframe(
                make_alloc_chart(result["allocations"], current_alloc),
                use_container_width=True,
                hide_index=True
            )

            st.markdown("#### 5) IFT Decision Logic")
            ift_cols = st.columns(4)
            with ift_cols[0]:
                st.metric("Monthly IFT Count", str(state["ift_count_this_month"]))
            with ift_cols[1]:
                st.metric("Cooldown", f"{cooldown_days} days")
            with ift_cols[2]:
                st.metric("Confirmation Days", str(confirmation_days))
            with ift_cols[3]:
                st.metric("Allow 2nd IFT", "Yes" if allow_second_ift else "No")

            st.write(f"- Normal drift threshold: `{float(normal_drift_threshold_pct):.2f}%`")
            st.write(f"- Score change threshold: `{int(score_change_threshold)}`")
            st.write(f"- Confirmation rule: requires {confirmation_days} stable days plus 1 prior point for score-change comparison.")
            st.write(f"- Recent regime history: `{state['recent_regimes'][-(confirmation_days + 1):] if state['recent_regimes'] else []}`")
            st.write(f"- Recent score history: `{state['recent_scores'][-(confirmation_days + 1):] if state['recent_scores'] else []}`")
            st.write(f"- Final IFT recommendation: **{action}**")
            st.write(f"- Reason: {reason}")

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
            "G Fund (T-Bills)"
        ]

        for idx, (fund_label, ticker) in enumerate(PROXIES.items()):
            with ytd_cols[idx]:
                ytd_val = fetch_ytd_return(ticker)
                st.metric(label=f"{fund_short_names[idx]} ({ticker})", value=f"{ytd_val:+.2f}%" if ytd_val is not None else "N/A")

        st.markdown("---")
        col_chart_1, col_chart_2 = st.columns([1, 3])
        with col_chart_1:
            fund_selected = st.selectbox("Select TSP Fund to Plot", options=list(PROXIES.keys()))
            timeframe_selected = st.selectbox(
                "Select Performance Chart Timeframe",
                options=["1 Month", "3 Months", "6 Months", "1 Year", "5 Years", "10 Years"],
                index=5
            )

        ticker = PROXIES[fund_selected]
        period_map = {
            "1 Month": "1mo",
            "3 Months": "3mo",
            "6 Months": "6mo",
            "1 Year": "1y",
            "5 Years": "5y",
            "10 Years": "10y"
        }
        proxy_df = get_cached_proxy_df(ticker, period_map[timeframe_selected])

        if not proxy_df.empty:
            with col_chart_2:
                st.line_chart(proxy_df.set_index("Date")["Price"])
        else:
            st.error(f"Failed to fetch market data for proxy ticker: {ticker}.")

    with tab4:
        st.markdown("### Score History")
        score_df = make_score_chart(state)
        if score_df is not None:
            st.line_chart(score_df)
        else:
            st.info("No score history yet.")

        st.markdown("---")
        st.markdown("### Recent State Overview")
        recent_state_cards(state)

        st.markdown("### Run History Log")
        render_history_table(state)

    with tab5:
        st.markdown("### Transaction History (Audit Trail)")
        if TRANSACTION_FILE.exists():
            tx_df = pd.read_csv(TRANSACTION_FILE).tail(25)
            tx_df = tx_df.rename(columns={
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
            })
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
                st.download_button("Download Log CSV", data=log_df.to_csv(index=False).encode("utf-8"), file_name="tsp_daily_log.csv", mime="text/csv")
            with export_col2:
                st.download_button("Download Log JSON", data=log_df.to_json(orient="records", indent=2).encode("utf-8"), file_name="tsp_daily_log.json", mime="application/json")
            with export_col3:
                st.download_button(
                    "Download Latest Snapshot JSON",
                    data=json.dumps({
                        "market_data": market_data,
                        "market_sources": {k: st.session_state.get(f"{k}_source") for k in market_data.keys()},
                        "factor_scores": result["scores"],
                        "regime": result["regime"],
                        "total_score": result["composite_score"],
                        "action": action,
                        "reason": reason,
                        "current_alloc": current_alloc,
                        "target_alloc": result["allocations"],
                        "state": state,
                    }, indent=2).encode("utf-8"),
                    file_name="tsp_snapshot.json",
                    mime="application/json",
                )
        else:
            st.info("No log file yet.")


if __name__ == "__main__":
    main()
