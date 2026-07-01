"""
app.py — Streamlit orchestration layer.

Owns page layout, sidebar controls, fetch/run flow, rendering, and
manual confirmation wiring.

Does not own scoring, persistence internals, or data acquisition.
"""
from datetime import date
import json

import pandas as pd
import streamlit as st

from constants import (
    DEFAULTS,
    PROXIES,
    LOG_FILE,
    TRANSACTION_FILE,
    REGIME_ORDER,
    BASELINE_ALLOCATIONS,
)
from data_sources import get_market_snapshot, get_cached_proxy_df, fetch_ytd_return
from engine import build_engine_result, should_use_tsp_ift, cumulative_alloc_drift
from storage import load_state_for_today, load_config, save_config, save_state, append_log_row
from ui import (
    render_metric_cards,
    render_snapshot_quality_badge,
    make_score_chart,
    make_alloc_chart,
    render_tile_grid,
    recent_state_cards,
    render_history_table,
    render_editable_metric_tile,
    render_regime_cards,
    render_decision_breakdown,
)
from utils import compute_snapshot_quality, get_est_now
from validation import validate_market_data
from ift_state_machine import IFTStateMachine

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
    "bond_yield_3m",
    "market_breadth_pct", "vix_spot", "dxy_spot", "spx_spot",
    "pct_dist_200_sma", "drawdown_pct",
    "treasury_10y_3m_spread", "inflation_shock", "central_bank_stance", "liquidity_pressure",
    "dxy_sma_5", "dxy_sma_20", "dxy_trend_up", "dxy_range_regime",
]

NUMERIC_KEYS = {
    "core_pce_yoy", "ism_pmi", "services_pmi", "initial_claims",
    "breakeven_inflation", "fed_assets_growth_yoy", "real_yield_10y",
    "move_index", "sloos_net_pct", "hy_oas", "shiller_cape",
    "fwd_eps_growth_yoy", "stlfsi_index", "bond_yield_10y",
    "bond_yield_3m", "market_breadth_pct", "vix_spot", "dxy_spot", "spx_spot",
    "pct_dist_200_sma", "drawdown_pct",
    "treasury_10y_3m_spread", "inflation_shock", "central_bank_stance", "liquidity_pressure",
    "dxy_sma_5", "dxy_sma_20",
}

BOOLEAN_KEYS = {"dxy_trend_up"}
TEXT_KEYS = {"dxy_range_regime"}


def init_session(cfg):
    indicators = EDITABLE_KEYS + ["vix_3d_panic", "spx_3d_panic", "vix_last_3", "spx_dist_last_3"]
    for key in indicators:
        if key not in st.session_state:
            if key in ["vix_3d_panic", "spx_3d_panic"]:
                st.session_state[key] = False
            elif key in ["vix_last_3", "spx_dist_last_3"]:
                st.session_state[key] = []
            elif key in BOOLEAN_KEYS:
                st.session_state[key] = bool(cfg.get(key, False))
            elif key in TEXT_KEYS:
                st.session_state[key] = str(cfg.get(key, "UNKNOWN"))
            else:
                st.session_state[key] = float(cfg.get(key, DEFAULTS.get(key, 0.0)))
        if f"{key}_source" not in st.session_state:
            st.session_state[f"{key}_source"] = "CONFIG/DEFAULT"

    if "engine_ran" not in st.session_state:
        st.session_state["engine_ran"] = False
    if "last_engine_result" not in st.session_state:
        st.session_state["last_engine_result"] = None
    if "live_market_data" not in st.session_state:
        st.session_state["live_market_data"] = {}
    if "live_market_sources" not in st.session_state:
        st.session_state["live_market_sources"] = {}


def get_current_market_sources():
    source_keys = EDITABLE_KEYS + ["vix_3d_panic", "spx_3d_panic"]
    return {
        key: st.session_state.get(f"{key}_source", "CONFIG/DEFAULT")
        for key in source_keys
    }


def load_editable_market_data():
    market = {}
    for k in EDITABLE_KEYS:
        if k in BOOLEAN_KEYS:
            market[k] = bool(st.session_state.get(k, False))
        elif k in TEXT_KEYS:
            market[k] = str(st.session_state.get(k, "UNKNOWN"))
        else:
            market[k] = st.session_state.get(k, DEFAULTS.get(k, 0.0))
    market["vix_3d_panic"] = bool(st.session_state.get("vix_3d_panic", False))
    market["spx_3d_panic"] = bool(st.session_state.get("spx_3d_panic", False))
    market["vix_last_3"] = st.session_state.get("vix_last_3", [])
    market["spx_dist_last_3"] = st.session_state.get("spx_dist_last_3", [])
    return market


def main():
    cfg = load_config()
    today = date.today()
    state = load_state_for_today(today)
    init_session(cfg)

    with st.sidebar:
        st.markdown("## 🏛️ TSP Rebalance Engine")

        with st.expander("💼 Current Allocation", expanded=True):
            neutral = BASELINE_ALLOCATIONS["OPTIMIZED NEUTRAL"]
            st.caption(
                f"Startup allocation is set to the tactical neutral baseline: "
                f"G {neutral['G']} / C {neutral['C']} / I {neutral['I']} / S {neutral['S']} / F {neutral['F']}."
            )
            current_alloc = {
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

        total_alloc = sum(current_alloc.values())
        if abs(total_alloc - 100.0) > 0.5:
            st.warning(f"Current allocation totals {total_alloc:.1f}%. Expected 100.0%.")

        with st.expander("🛡️ Rules", expanded=False):
            allow_second_ift = st.checkbox("Allow second IFT", value=bool(cfg["allow_second_ift"]))
            normal_drift_threshold_pct = st.number_input(
                "Normal drift threshold %",
                value=float(cfg["normal_drift_threshold_pct"]),
                step=0.5,
            )
            score_change_threshold = st.number_input(
                "Score change threshold",
                value=int(cfg["score_change_threshold"]),
                step=1,
            )
            confirmation_days = st.number_input(
                "Confirmation days",
                value=int(cfg["confirmation_days"]),
                step=1,
            )
            cooldown_days = st.number_input(
                "Cooldown days",
                value=int(cfg["cooldown_days"]),
                step=1,
            )
            use_live_macro = st.checkbox("Use live macro data", value=bool(cfg["use_live_macro"]))

        with st.expander("🛠️ Manual Override", expanded=False):
            manual_override_enabled = st.checkbox(
                "Enable manual override",
                value=bool(cfg["manual_override_enabled"]),
            )
            manual_regime_default = cfg.get("manual_regime", "OPTIMIZED NEUTRAL")
            manual_regime_index = REGIME_ORDER.index(manual_regime_default) if manual_regime_default in REGIME_ORDER else 1

            manual_regime = st.selectbox(
                "Override regime",
                REGIME_ORDER,
                index=manual_regime_index,
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
        confirm_ift_btn = st.button(
            "✅ Submit IFT",
            use_container_width=True,
            disabled=not st.session_state.get("engine_ran", False),
        )
        st.caption("Submit is enabled only after an engine run. A pure G move is treated as a safety action.")

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
            cfg[key] = st.session_state.get(key, DEFAULTS.get(key, 0.0))
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
        st.session_state["last_engine_result"] = None
        st.session_state["engine_ran"] = False
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
        latest_result = st.session_state.get("last_engine_result")
        if latest_result is None:
            st.sidebar.warning("Run the engine first before submitting an IFT.")
        else:
            target_alloc = latest_result["allocations"]
            machine = IFTStateMachine.load(today)
            decision = machine.confirm(current_alloc, target_alloc, latest_result["regime"])
            if decision.allowed:
                st.sidebar.success(decision.reason)
            else:
                st.sidebar.warning(decision.reason)
        st.rerun()

    if run:
        with st.spinner("Connecting to live feeds..."):
            try:
                snapshot = get_market_snapshot(fred_api_key if use_live_macro else "")
                fetched_data = snapshot["market_data"]
                fetched_sources = snapshot["market_sources"]
            except Exception:
                fetched_data = {k: DEFAULTS.get(k, 0.0) for k in DEFAULTS.keys()}
                fetched_data["vix_3d_panic"] = False
                fetched_data["spx_3d_panic"] = False
                fetched_data["vix_last_3"] = []
                fetched_data["spx_dist_last_3"] = []
                fetched_sources = {k: "CONFIG/DEFAULT" for k in fetched_data.keys()}

            st.session_state["live_market_data"] = fetched_data
            st.session_state["live_market_sources"] = fetched_sources

            for key in EDITABLE_KEYS:
                if key in BOOLEAN_KEYS:
                    st.session_state[key] = bool(fetched_data.get(key, False))
                elif key in TEXT_KEYS:
                    st.session_state[key] = str(fetched_data.get(key, "UNKNOWN"))
                else:
                    st.session_state[key] = float(fetched_data.get(key, DEFAULTS.get(key, 0.0)))
                st.session_state[f"{key}_source"] = fetched_sources.get(key, "CONFIG/DEFAULT")

            st.session_state["vix_3d_panic"] = bool(fetched_data.get("vix_3d_panic", False))
            st.session_state["spx_3d_panic"] = bool(fetched_data.get("spx_3d_panic", False))
            st.session_state["vix_last_3"] = fetched_data.get("vix_last_3", [])
            st.session_state["spx_dist_last_3"] = fetched_data.get("spx_dist_last_3", [])
            st.session_state["engine_ran"] = True

        state = load_state_for_today(today)

        market_data = load_editable_market_data()
        range_warnings = validate_market_data(market_data)
        st.session_state["market_data_warnings"] = range_warnings if range_warnings else []

        result = build_engine_result(
            market_data,
            override_active=manual_override_enabled,
            override_regime=manual_regime,
        )
        st.session_state["last_engine_result"] = result

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

        state.setdefault("recent_regimes", [])
        state.setdefault("recent_scores", [])
        state.setdefault("recent_allocations", [])

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
    result = st.session_state.get("last_engine_result")
    if result is None:
        result = build_engine_result(
            market_data,
            override_active=cfg.get("manual_override_enabled", False),
            override_regime=cfg.get("manual_regime", "OPTIMIZED_NEUTRAL"),
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

    market_data_warnings = st.session_state.get("market_data_warnings", [])
    if market_data_warnings:
        st.warning(
            "⚠️ Some market inputs look outside plausible ranges — verify before trusting the recommendation:\n"
            + "\n".join(f"- {w}" for w in market_data_warnings)
        )

    snapshot_quality = compute_snapshot_quality(get_current_market_sources())

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
            st.metric(
                "Cumulative Portfolio Drift",
                f"{cum_drift:.2f}%",
                f"{cum_drift - float(normal_drift_threshold_pct):+.2f}% vs Threshold",
            )
        with c2:
            st.write(
                f"**Rebalance Threshold Progress**: `{cum_drift:.2f}%` / `{float(normal_drift_threshold_pct):.2f}%` required."
            )
            st.progress(min(cum_drift / float(normal_drift_threshold_pct), 1.0) if float(normal_drift_threshold_pct) > 0 else 1.0)

        st.markdown("### Allocation Comparison")
        alloc_df = make_alloc_chart(result["allocations"], current_alloc)
        st.dataframe(alloc_df, use_container_width=True, hide_index=True)

        render_regime_cards(result["regime"])

    with tab2:
        render_snapshot_quality_badge(snapshot_quality, st.session_state.get("engine_ran", False))

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
            ("yield_curve", "Yield Curve"),
            ("inflation_shock", "Inflation Shock"),
            ("central_bank", "Central Bank"),
            ("liquidity_pressure", "Liquidity Pressure"),
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

        cols = st.columns(4)
        for i, (label, key, source) in enumerate(market_edit_items):
            with cols[i % 4]:
                if key in BOOLEAN_KEYS:
                    fmt = "%s"
                    step = 1.0
                elif key in TEXT_KEYS:
                    fmt = "%s"
                    step = 0.1
                else:
                    fmt = "%.2f"
                    step = 0.1
                render_editable_metric_tile(
                    label=label,
                    value=st.session_state.get(key, False if key in BOOLEAN_KEYS else "UNKNOWN" if key in TEXT_KEYS else 0.0),
                    source=source,
                    key=key,
                    step=step,
                    fmt=fmt,
                    color="#3b82f6",
                )

        render_decision_breakdown(
            result=result,
            action=action,
            reason=reason,
            state=state,
            current_alloc=current_alloc,
            dxy_range_regime=st.session_state.get("dxy_range_regime", "UNKNOWN"),
            dxy_trend_up=st.session_state.get("dxy_trend_up", False),
            cooldown_days=cooldown_days,
            confirmation_days=confirmation_days,
            allow_second_ift=allow_second_ift,
            normal_drift_threshold_pct=normal_drift_threshold_pct,
            score_change_threshold=score_change_threshold,
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
            "G Fund (T-Bills)",
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
                index=5,
            )

        ticker = PROXIES[fund_selected]
        period_map = {
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
