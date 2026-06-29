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


def get_market_snapshot_value(key, default=None):
    live_data = st.session_state.get("live_market_data", {})
    live_sources = st.session_state.get("live_market_sources", {})

    value = live_data.get(key, st.session_state.get(key, default))
    source = live_sources.get(key, st.session_state.get(f"{key}_source", "CONFIG/DEFAULT"))
    return value, source


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

        with st.expander("🛠️ Manual Override", expanded=False):
            manual_override_enabled = st.checkbox("Enable manual override", value=bool(cfg["manual_override_enabled"]))
            manual_regime = st.selectbox(
                "Override regime",
                ["RISK-ON OVERRIDE", "OPTIMIZED NEUTRAL", "DEFENSIVE ALLOCATION", "EMERGENCY DISPATCH"],
                index=["RISK-ON OVERRIDE", "OPTIMIZED NEUTRAL", "DEFENSIVE ALLOCATION", "EMERGENCY DISPATCH"].index(cfg["manual_regime"])
            )

        fred_api_key = st.text_input("FRED API Key", value=str(cfg.get("fred_api_key", "")), type="password")

        st.divider()
        save_cfg = st.button("💾 Save Config", use_container_width=True)
        reset_state_btn = st.button("♻️ Reset State", use_container_width=True)
        clear_logs_btn = st.button("🗑️ Clear Log File", use_container_width=True)
        clear_tx_btn = st.button("🗑️ Clear Audit Trail", use_container_width=True)
        update_ift_btn = st.button("📌 Update IFT Count", use_container_width=True)
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
        st.stop()

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

    if update_ift_btn:
        state = load_state()
        if state.get("month") != today.strftime("%Y-%m"):
            state["month"] = today.strftime("%Y-%m")
            state["ift_count_this_month"] = 0
        state["ift_count_this_month"] = int(state.get("ift_count_this_month", 0)) + 1
        save_state(state)
        st.sidebar.success("IFT Count updated.")
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
                if key not in st.session_state:
                    st.session_state[key] = float(fetched_data.get(key, DEFAULTS.get(key, 0.0)))
                if f"{key}_source" not in st.session_state:
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
        if use_ift:
            state["ift_count_this_month"] += 1
            state["last_ift_date"] = today.isoformat()

            try:
                append_transaction_row(
                    today.isoformat(),
                    current_alloc,
                    result["allocations"],
                    result["regime"],
                )
            except Exception as e:
                st.warning(f"IFT transaction log write failed: {e}")

        state["recent_regimes"].append(result["regime"])
        state["recent_scores"].append(result["composite_score"])
        state["recent_allocations"].append(result["allocations"])
        state["recent_regimes"] = state["recent_regimes"][-30:]
        state["recent_scores"] = state["recent_scores"][-30:]
        state["recent_allocations"] = state["recent_allocations"][-30:]
        state["last_run_date"] = today.isoformat()
        save_state(state)

        append_log_row(
            today.isoformat(),
            result["regime"],
            result["composite_score"],
            action,
            reason,
            current_alloc,
            result["allocations"],
            state["ift_count_this_month"],
        )

    market_data = load_editable_market_data()

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "Allocation",
        "Factors",
        "Fund Tracking",
        "History",
        "Logs & State",
    ])

    with tab1:
        result = build_engine_result(
            market_data,
            override_active=manual_override_enabled,
            override_regime=manual_regime
        )
        render_metric_cards(
            result["composite_score"],
            result["regime"],
            "SUBMIT IFT" if result["emergency_triggered"] else "HOLD",
            state.get("ift_count_this_month", 0),
            "Latest engine view",
        )

        st.markdown("### Strategic Regime Directory")
        regime_rows = [
            {"name": "Risk-On", "profile": "Growth leadership", "score": "High momentum", "alloc": "C / S tilt", "desc": "Favorable macro and breadth conditions.", "icon": "🟢", "color": "#16a34a", "bg": "rgba(220,252,231,0.55)"},
            {"name": "Neutral", "profile": "Balanced stance", "score": "Mixed signal", "alloc": "Balanced allocation", "desc": "Conditions are neither strongly risk-on nor defensive.", "icon": "⚪", "color": "#64748b", "bg": "rgba(248,250,252,0.55)"},
            {"name": "Defensive", "profile": "Capital preservation", "score": "Weak breadth", "alloc": "G / F tilt", "desc": "Macro stress and downside risks are elevated.", "icon": "🟠", "color": "#ea580c", "bg": "rgba(255,247,237,0.65)"},
            {"name": "Emergency", "profile": "Preservation first", "score": "High stress", "alloc": "G heavy", "desc": "Risk controls dominate, use maximum defensiveness.", "icon": "🔴", "color": "#dc2626", "bg": "rgba(254,226,226,0.65)"},
        ]
        regime_cols = st.columns(4)
        for idx, info in enumerate(regime_rows):
            with regime_cols[idx]:
                render_regime_card(info, is_active=(idx == 0))

        st.markdown("---")
        col_chart_1, col_chart_2 = st.columns([1, 3])
        with col_chart_1:
            fund_selected = st.selectbox("Select TSP Fund to Plot", options=list(PROXIES.keys()))
            timeframe_selected = st.selectbox("Select Performance Chart Timeframe", options=["1 Month", "3 Months", "6 Months", "1 Year", "5 Years", "10 Years"], index=3)

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
            ("Core PCE YoY", "core_pce_yoy"),
            ("ISM Manufacturing PMI", "ism_pmi"),
            ("ISM Services PMI", "services_pmi"),
            ("Initial Claims (K)", "initial_claims"),
            ("10Y Breakeven Inflation", "breakeven_inflation"),
            ("Fed Assets Growth YoY", "fed_assets_growth_yoy"),
            ("10Y Real Yield", "real_yield_10y"),
            ("MOVE Volatility", "move_index"),
            ("SLOOS Net %", "sloos_net_pct"),
            ("HY OAS", "hy_oas"),
            ("Shiller CAPE", "shiller_cape"),
            ("Fwd EPS Growth YoY", "fwd_eps_growth_yoy"),
            ("VIX Spot", "vix_spot"),
            ("SPX vs 200SMA %", "pct_dist_200_sma"),
            ("Drawdown %", "drawdown_pct"),
            ("STLFSI", "stlfsi_index"),
            ("10Y Yield", "bond_yield_10y"),
            ("DXY Spot", "dxy_spot"),
            ("Breadth %", "market_breadth_pct"),
            ("SPX Spot", "spx_spot"),
        ]

        cols = st.columns(4)
        for i, (label, key) in enumerate(market_edit_items):
            value, source = get_market_snapshot_value(key, DEFAULTS.get(key, 0.0))
            with cols[i % 4]:
                render_editable_metric_tile(
                    label=label,
                    value=value,
                    source=source,
                    key=key,
                    step=0.1,
                    fmt="%.2f",
                    color="#3b82f6",
                )

        st.markdown("### 🔍 Engine Decision Breakdown")
        with st.expander("📖 Detailed Decision Trace & Factor Attribution", expanded=True):
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
            st.dataframe(pd.read_csv(TRANSACTION_FILE).tail(25), use_container_width=True, hide_index=True)
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
                        "action": "SUBMIT IFT" if result["emergency_triggered"] else "HOLD",
                        "reason": "Latest view",
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
