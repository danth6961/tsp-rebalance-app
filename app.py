import streamlit as st
from datetime import date

from constants import DEFAULTS, PROXIES
from storage import load_state, load_config, save_config, save_state, append_log_row
from engine import build_engine_result, should_use_tsp_ift, cumulative_alloc_drift
from utils import get_est_now

st.set_page_config(page_title="TSP Rebalance Engine", page_icon="🏛️", layout="wide")

def main():
    cfg = load_config()
    state = load_state()
    today = date.today()

    st.title("TSP Rebalance Engine")

    with st.sidebar:
        current_alloc = {
            "G": st.number_input("G Fund %", value=float(cfg["current_alloc"]["G"])),
            "C": st.number_input("C Fund %", value=float(cfg["current_alloc"]["C"])),
            "I": st.number_input("I Fund %", value=float(cfg["current_alloc"]["I"])),
            "S": st.number_input("S Fund %", value=float(cfg["current_alloc"]["S"])),
            "F": st.number_input("F Fund %", value=float(cfg["current_alloc"]["F"])),
        }

        allow_second_ift = st.checkbox("Allow second IFT", value=cfg["allow_second_ift"])
        use_live_macro = st.checkbox("Use Live Macro Data", value=cfg["use_live_macro"])
        manual_override_enabled = st.checkbox("Enable Manual Override", value=cfg["manual_override_enabled"])
        manual_regime = st.selectbox(
            "Manual Regime",
            ["RISK-ON OVERRIDE", "OPTIMIZED NEUTRAL", "DEFENSIVE ALLOCATION", "EMERGENCY DISPATCH"],
            index=["RISK-ON OVERRIDE", "OPTIMIZED NEUTRAL", "DEFENSIVE ALLOCATION", "EMERGENCY DISPATCH"].index(cfg["manual_regime"]),
        )

        run = st.button("Fetch & Run Engine", type="primary")
        save_cfg = st.button("Save Config")

    if save_cfg:
        cfg["current_alloc"] = current_alloc
        cfg["allow_second_ift"] = allow_second_ift
        cfg["use_live_macro"] = use_live_macro
        cfg["manual_override_enabled"] = manual_override_enabled
        cfg["manual_regime"] = manual_regime
        save_config(cfg)
        st.sidebar.success("Saved.")
        st.stop()

    if not run:
        st.info("Set inputs in the sidebar and click **Fetch & Run Engine**.")
        return

    st.write(f"Current EST time: {get_est_now().strftime('%I:%M %p')}")

    # Placeholder: replace with real snapshot fetch
    market_data = {
        "core_pce_yoy": DEFAULTS["core_pce_yoy"],
        "ism_pmi": DEFAULTS["ism_pmi"],
        "services_pmi": DEFAULTS["services_pmi"],
        "initial_claims": DEFAULTS["initial_claims"],
        "breakeven_inflation": DEFAULTS["breakeven_inflation"],
        "fed_assets_growth_yoy": DEFAULTS["fed_assets_growth_yoy"],
        "real_yield_10y": DEFAULTS["real_yield_10y"],
        "move_index": DEFAULTS["move_index"],
        "sloos_net_pct": DEFAULTS["sloos_net_pct"],
        "hy_oas": DEFAULTS["hy_oas"],
        "shiller_cape": DEFAULTS["shiller_cape"],
        "fwd_eps_growth_yoy": DEFAULTS["fwd_eps_growth_yoy"],
        "vix_spot": DEFAULTS["vix_spot"],
        "pct_dist_200_sma": 0.0,
        "drawdown_pct": 0.0,
        "stlfsi_index": DEFAULTS["stlfsi_index"],
        "bond_yield_10y": DEFAULTS["bond_yield_10y"],
        "dxy_spot": DEFAULTS["dxy_spot"],
        "market_breadth_pct": DEFAULTS["market_breadth_pct"],
        "spx_spot": DEFAULTS["spx_spot"],
        "vix_3d_panic": False,
        "spx_3d_panic": False,
    }

    result = build_engine_result(
        market_data,
        override_active=manual_override_enabled,
        override_regime=manual_regime,
    )

    use_ift, reason = should_use_tsp_ift(
        today=today,
        current_alloc=current_alloc,
        target_alloc=result["allocations"],
        recent_regimes=state["recent_regimes"],
        recent_scores=state["recent_scores"],
        emergency_triggered=result["emergency_triggered"],
        ift_count_this_month=state["ift_count_this_month"],
        last_ift_date=None,
        allow_second_ift=allow_second_ift,
        normal_drift_threshold_pct=cfg["normal_drift_threshold_pct"],
        score_change_threshold=cfg["score_change_threshold"],
        confirmation_days=cfg["confirmation_days"],
        cooldown_days=cfg["cooldown_days"],
    )

    st.subheader("Decision")
    st.write("Regime:", result["regime"])
    st.write("Composite Score:", result["composite_score"])
    st.write("Target Allocation:", result["allocations"])
    st.write("IFT Decision:", "SUBMIT IFT" if use_ift else "HOLD")
    st.write("Reason:", reason)

if __name__ == "__main__":
    main()
