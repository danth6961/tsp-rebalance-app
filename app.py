from datetime import date
import json

import pandas as pd
import streamlit as st

from constants import DEFAULTS, PROXIES
from data_sources import get_market_snapshot, get_cached_proxy_df, fetch_ytd_return
from engine import build_engine_result, should_use_tsp_ift, cumulative_alloc_drift
from storage import load_state, load_config, save_config, save_state, append_log_row, append_transaction_row
from ui import render_metric_cards, make_score_chart, make_alloc_chart, source_pill_html, score_card_html
from utils import get_est_now

st.set_page_config(
    page_title="TSP Rebalance Engine",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
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
""", unsafe_allow_html=True)

def default_market_state():
    return {k: float(v) for k, v in DEFAULTS.items()}

def init_session(cfg):
    indicators = [
        "core_pce_yoy", "ism_pmi", "services_pmi", "initial_claims",
        "breakeven_inflation", "fed_assets_growth_yoy", "real_yield_10y",
        "move_index", "sloos_net_pct", "hy_oas", "shiller_cape",
        "fwd_eps_growth_yoy", "stlfsi_index", "bond_yield_10y",
        "market_breadth_pct", "vix_spot", "dxy_spot", "spx_spot",
        "pct_dist_200_sma", "drawdown_pct", "vix_3d_panic", "spx_3d_panic",
        "vix_last_3", "spx_dist_last_3"
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

        save_cfg = st.button("💾 Save Config", use_container_width=True)
        run = st.button("🚀 Fetch & Run Engine", use_container_width=True, type="primary")
        mark_ift = st.button("✅ Mark IFT Used Today", use_container_width=True)
        reset_state_btn = st.button("♻️ Reset State", use_container_width=True)
        clear_logs_btn = st.button("🗑️ Clear Log File", use_container_width=True)
        clear_tx_btn = st.button("🗑️ Clear Audit Trail", use_container_width=True)

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
        for key in ["core_pce_yoy", "ism_pmi", "services_pmi", "initial_claims", "breakeven_inflation",
                    "fed_assets_growth_yoy", "real_yield_10y", "move_index", "sloos_net_pct", "hy_oas",
                    "shiller_cape", "fwd_eps_growth_yoy", "stlfsi_index", "bond_yield_10y",
                    "market_breadth_pct", "vix_spot", "dxy_spot", "spx_spot"]:
            cfg[key] = float(st.session_state.get(key, DEFAULTS.get(key, 0.0)))
        save_config(cfg)
        st.sidebar.success("Config saved.")

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
        from constants import LOG_FILE
        if LOG_FILE.exists():
            LOG_FILE.unlink()
        st.rerun()

    if clear_tx_btn:
        from constants import TRANSACTION_FILE
        if TRANSACTION_FILE.exists():
            TRANSACTION_FILE.unlink()
        st.rerun()

    if mark_ift:
        temp_snapshot = {k: st.session_state[k] for k in [
            "core_pce_yoy", "ism_pmi", "services_pmi", "initial_claims", "breakeven_inflation",
            "fed_assets_growth_yoy", "real_yield_10y", "move_index", "sloos_net_pct", "hy_oas",
            "shiller_cape", "fwd_eps_growth_yoy", "stlfsi_index", "bond_yield_10y",
            "market_breadth_pct", "vix_spot", "dxy_spot", "spx_spot",
            "pct_dist_200_sma", "drawdown_pct", "vix_3d_panic", "spx_3d_panic"
        ]}
        temp_snapshot["vix_last_3"] = st.session_state.get("vix_last_3", [])
        temp_snapshot["spx_dist_last_3"] = st.session_state.get("spx_dist_last_3", [])
        result = build_engine_result(
            temp_snapshot,
            override_active=cfg.get("manual_override_enabled", False),
            override_regime=cfg.get("manual_regime", "OPTIMIZED NEUTRAL")
        )
        append_transaction_row(today.isoformat(), current_alloc, result["allocations"], result["regime"])
        st.sidebar.success("Audit entry added.")

    current_sum = sum(current_alloc.values())
    if not abs(current_sum - 100.0) < 1e-6:
        st.error(f"Current allocation must sum to 100%. Right now it sums to {current_sum:.1f}%.")
        return

    if not run and not st.session_state["engine_ran"]:
        st.info("Set inputs in the sidebar and click **Fetch & Run Engine**.")
        return

    if run:
        with st.spinner("Connecting to live feeds..."):
            try:
                snapshot = get_market_snapshot(fred_api_key if use_live_macro else "")
                fetched_data = snapshot["market_data"]
                fetched_sources = snapshot["market_sources"]
            except Exception:
                fetched_data = default_market_state()
                fetched_data["pct_dist_200_sma"] = 0.0
                fetched_data["drawdown_pct"] = 0.0
                fetched_data["vix_3d_panic"] = False
                fetched_data["spx_3d_panic"] = False
                fetched_data["vix_last_3"] = []
                fetched_data["spx_dist_last_3"] = []
                fetched_sources = {k: "CONFIG/DEFAULT" for k in fetched_data.keys()}

        for key in ["core_pce_yoy", "ism_pmi", "services_pmi", "initial_claims", "breakeven_inflation",
                    "fed_assets_growth_yoy", "real_yield_10y", "move_index", "sloos_net_pct", "hy_oas",
                    "shiller_cape", "fwd_eps_growth_yoy", "stlfsi_index", "bond_yield_10y",
                    "market_breadth_pct", "vix_spot", "dxy_spot", "spx_spot"]:
            st.session_state[key] = float(fetched_data.get(key, DEFAULTS.get(key, 0.0)))
            st.session_state[f"{key}_source"] = fetched_sources.get(key, "CONFIG/DEFAULT")
        st.session_state["pct_dist_200_sma"] = float(fetched_data.get("pct_dist_200_sma", 0.0))
        st.session_state["drawdown_pct"] = float(fetched_data.get("drawdown_pct", 0.0))
        st.session_state["vix_3d_panic"] = bool(fetched_data.get("vix_3d_panic", False))
        st.session_state["spx_3d_panic"] = bool(fetched_data.get("spx_3d_panic", False))
        st.session_state["vix_last_3"] = fetched_data.get("vix_last_3", [])
        st.session_state["spx_dist_last_3"] = fetched_data.get("spx_dist_last_3", [])
        st.session_state["engine_ran"] = True

        state = load_state()
        if state.get("month") != today.strftime("%Y-%m"):
            state["month"] = today.strftime("%Y-%m")
            state["ift_count_this_month"] = 0

        result = build_engine_result(
            fetched_data,
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
        state["recent_regimes"].append(result["regime"])
        state["recent_scores"].append(result["composite_score"])
        state["recent_allocations"].append(result["allocations"])
        state["recent_regimes"] = state["recent_regimes"][-30:]
        state["recent_scores"] = state["recent_scores"][-30:]
        state["recent_allocations"] = state["recent_allocations"][-30:]
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
            "vix": fetched_data.get("vix_spot", DEFAULTS["vix_spot"]),
            "spx_200sma_dist": fetched_data.get("pct_dist_200_sma", 0.0),
            "drawdown_pct": fetched_data.get("drawdown_pct", 0.0),
        })

        st.session_state["engine_ran"] = True

    market_data = {k: st.session_state[k] for k in [
        "core_pce_yoy", "ism_pmi", "services_pmi", "initial_claims", "breakeven_inflation",
        "fed_assets_growth_yoy", "real_yield_10y", "move_index", "sloos_net_pct", "hy_oas",
        "shiller_cape", "fwd_eps_growth_yoy", "vix_spot", "pct_dist_200_sma", "drawdown_pct",
        "stlfsi_index", "bond_yield_10y", "dxy_spot", "market_breadth_pct", "spx_spot",
        "vix_3d_panic", "spx_3d_panic"
    ]}
    market_data["vix_last_3"] = st.session_state.get("vix_last_3", [])
    market_data["spx_dist_last_3"] = st.session_state.get("spx_dist_last_3", [])

    result = build_engine_result(
        market_data,
        override_active=cfg.get("manual_override_enabled", False),
        override_regime=cfg.get("manual_regime", "OPTIMIZED NEUTRAL")
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

        cum_drift = cumulative_alloc_drift(current_alloc, result["allocations"])
        st.metric("Cumulative Portfolio Drift", f"{cum_drift:.2f}%")
        st.progress(min(cum_drift / float(normal_drift_threshold_pct), 1.0) if normal_drift_threshold_pct > 0 else 1.0)

        st.markdown("### Allocation Comparison")
        alloc_df = make_alloc_chart(result["allocations"], current_alloc)
        st.dataframe(alloc_df, use_container_width=True, hide_index=True)

        if action == "SUBMIT IFT":
            st.success("IFT should be submitted based on current rules.")

        st.markdown("### Strategic Regime")
        st.write(result["regime"])
        st.write("Composite score:", result["composite_score"])

    with tab2:
        st.markdown("### Factor Scores")
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
            color = "#16a34a" if val > 0 else "#dc2626" if val < 0 else "#64748b"
            icon = "▲" if val > 0 else "▼" if val < 0 else "●"
            st.markdown(score_card_html(label, val, "Factor contribution", color, icon), unsafe_allow_html=True)

        st.markdown("### Market Snapshot")
        for key in ["core_pce_yoy", "ism_pmi", "services_pmi", "initial_claims", "breakeven_inflation", "fed_assets_growth_yoy",
                    "real_yield_10y", "move_index", "sloos_net_pct", "hy_oas", "shiller_cape", "fwd_eps_growth_yoy",
                    "vix_spot", "pct_dist_200_sma", "drawdown_pct", "stlfsi_index", "bond_yield_10y", "dxy_spot", "market_breadth_pct", "spx_spot"]:
            st.write(f"**{key}**:", st.session_state[key], "| source:", st.session_state.get(f"{key}_source", "N/A"))

    with tab3:
        st.markdown("### Proxy Fund YTD Performance")
        cols = st.columns(5)
        for idx, (fund_label, ticker) in enumerate(PROXIES.items()):
            with cols[idx]:
                ytd_val = fetch_ytd_return(ticker)
                if ytd_val is not None:
                    st.metric(label=f"{fund_label} ({ticker})", value=f"{ytd_val:+.2f}%")
                else:
                    st.metric(label=f"{fund_label} ({ticker})", value="N/A")

        st.markdown("---")
        fund_selected = st.selectbox("Select TSP Fund to Plot", options=list(PROXIES.keys()))
        timeframe_selected = st.selectbox("Select Timeframe", ["1 Month", "3 Months", "6 Months", "1 Year", "5 Years", "10 Years"], index=3)
        period_map = {"1 Month": "1mo", "3 Months": "3mo", "6 Months": "6mo", "1 Year": "1y", "5 Years": "5y", "10 Years": "10y"}
        ticker = PROXIES[fund_selected]
        proxy_df = get_cached_proxy_df(ticker, period_map[timeframe_selected])

        if not proxy_df.empty:
            st.line_chart(proxy_df.set_index("Date")["Price"])
        else:
            st.error(f"Failed to fetch {ticker} data.")

    with tab4:
        score_df = make_score_chart(state)
        if score_df is not None:
            st.line_chart(score_df)
        else:
            st.info("No score history yet.")
        st.markdown("### Recent State")
        st.json(state)

    with tab5:
        from constants import TRANSACTION_FILE, LOG_FILE
        st.markdown("### Transaction History")
        if TRANSACTION_FILE.exists():
            st.dataframe(pd.read_csv(TRANSACTION_FILE).tail(25), use_container_width=True, hide_index=True)
        else:
            st.info("No transaction file yet.")
        st.markdown("### Daily Log")
        if LOG_FILE.exists():
            st.dataframe(pd.read_csv(LOG_FILE).tail(25), use_container_width=True, hide_index=True)
        else:
            st.info("No log file yet.")

if __name__ == "__main__":
    main()
