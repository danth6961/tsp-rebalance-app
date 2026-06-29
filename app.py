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

        st.markdown("---")
        allow_second_ift = st.checkbox("Allow second IFT this month", value=bool(cfg.get("allow_second_ift", False)))
        use_live_macro = st.checkbox("Use live macro feeds", value=bool(cfg.get("use_live_macro", True)))
        manual_override_enabled = st.checkbox("Manual override regime", value=bool(cfg.get("manual_override_enabled", False)))
        manual_regime = st.selectbox("Manual regime", ["OPTIMIZED NEUTRAL", "RISK-OFF", "RISK-ON"], index=0)

        save_cfg = st.button("Save Config")
        reset_state_btn = st.button("Reset State")
        clear_logs_btn = st.button("Clear Logs")
        clear_tx_btn = st.button("Clear Transactions")
        run = st.button("Fetch and run")

    if save_cfg:
        cfg["current_alloc"] = current_alloc
        cfg["allow_second_ift"] = allow_second_ift
        cfg["normal_drift_threshold_pct"] = float(cfg.get("normal_drift_threshold_pct", 3.0))
        cfg["score_change_threshold"] = int(cfg.get("score_change_threshold", 4))
        cfg["confirmation_days"] = int(cfg.get("confirmation_days", 2))
        cfg["cooldown_days"] = int(cfg.get("cooldown_days", 2))
        cfg["use_live_macro"] = bool(use_live_macro)
        cfg["manual_override_enabled"] = bool(manual_override_enabled)
        cfg["manual_regime"] = manual_regime
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

    if run:
        with st.spinner("Connecting to live feeds..."):
            try:
                snapshot = get_market_snapshot(
                    cfg.get("fred_api_key", "") if use_live_macro else "",
                    force_refresh=True,
                )
                fetched_data = snapshot["market_data"]
                fetched_sources = snapshot["market_sources"]
                st.success(f"Live market snapshot refreshed at {fetched_data.get('timestamp', 'unknown time')}")
            except Exception as e:
                st.error(f"Live market fetch failed: {e}")
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
        normal_drift_threshold_pct=float(cfg.get("normal_drift_threshold_pct", 3.0)),
        score_change_threshold=int(cfg.get("score_change_threshold", 4)),
        confirmation_days=int(cfg.get("confirmation_days", 2)),
        cooldown_days=int(cfg.get("cooldown_days", 2)),
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
        st.caption(f"Last refreshed: {st.session_state.get('live_market_data', {}).get('timestamp', 'Never')}")
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
