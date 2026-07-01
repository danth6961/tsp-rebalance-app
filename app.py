"""
app.py — Streamlit orchestration layer.

Owns:
- page layout
- sidebar controls
- fetch/run flow
- rendering
- manual confirmation wiring

Does not own:
- scoring logic
- persistence internals
- data acquisition
- CSS definitions
- regime definitions
"""

from __future__ import annotations

import json
from datetime import date

import pandas as pd
import streamlit as st

from constants import BASELINE_ALLOCATIONS, DEFAULTS, LOG_FILE, PROXIES, REGIME_ORDER, TRANSACTION_FILE
from data_sources import fetch_ytd_return, get_cached_proxy_df, get_market_snapshot
from engine import build_engine_result, cumulative_alloc_drift, should_use_tsp_ift
from ift_state_machine import IFTStateMachine
from storage import append_log_row, load_config, load_state_for_today, save_config, save_state
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
# Session state keys
# -----------------------------------------------------------------------------
# Keeping these centralized makes initialization and rerun behavior easier to
# reason about.
# -----------------------------------------------------------------------------
EDITABLE_KEYS: list[str] = [
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

NUMERIC_KEYS: set[str] = {
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
}

BOOLEAN_KEYS: set[str] = {"dxy_trend_up"}
TEXT_KEYS: set[str] = {"dxy_range_regime"}


def inject_styles() -> None:
    """Inject app-wide styles.

    CSS should live in styles.py in the final architecture. For now, this keeps
    the app runnable while making the separation explicit.
    """
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


def init_session_state(cfg: dict[str, object]) -> None:
    """Initialize Streamlit session state with config-backed defaults."""
    indicators = EDITABLE_KEYS + ["vix_3d_panic", "spx_3d_panic", "vix_last_3", "spx_dist_last_3"]

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

        if f"{key}_source" not in st.session_state:
            st.session_state[f"{key}_source"] = "CONFIG/DEFAULT"

    st.session_state.setdefault("engine_ran", False)
    st.session_state.setdefault("last_engine_result", None)
    st.session_state.setdefault("live_market_data", {})
    st.session_state.setdefault("live_market_sources", {})


def get_current_market_sources() -> dict[str, str]:
    """Return the current source label for each editable market field."""
    source_keys = EDITABLE_KEYS + ["vix_3d_panic", "spx_3d_panic"]
    return {
        key: st.session_state.get(f"{key}_source", "CONFIG/DEFAULT")
        for key in source_keys
    }


def load_editable_market_data() -> dict[str, object]:
    """Build the market data payload from session state."""
    market: dict[str, object] = {}
    for key in EDITABLE_KEYS:
        if key in BOOLEAN_KEYS:
            market[key] = bool(st.session_state.get(key, False))
        elif key in TEXT_KEYS:
            market[key] = str(st.session_state.get(key, "UNKNOWN"))
        else:
            market[key] = st.session_state.get(key, DEFAULTS.get(key, 0.0))

    market["vix_3d_panic"] = bool(st.session_state.get("vix_3d_panic", False))
    market["spx_3d_panic"] = bool(st.session_state.get("spx_3d_panic", False))
    market["vix_last_3"] = st.session_state.get("vix_last_3", [])
    market["spx_dist_last_3"] = st.session_state.get("spx_dist_last_3", [])
    return market


def main() -> None:
    """Main Streamlit entrypoint."""
    inject_styles()

    cfg = load_config()
    today = date.today()
    state = load_state_for_today(today)
    init_session_state(cfg)

    # Sidebar controls
    with st.sidebar:
        st.markdown("## 🏛️ TSP Rebalance Engine")

        with st.expander("💼 Current Allocation", expanded=False):
            neutral = BASELINE_ALLOCATIONS["OPTIMIZED NEUTRAL"]
            st.caption(
                f"Startup allocation is set to the tactical neutral baseline: "
                f"G {neutral['G']} / C {neutral['C']} / I {neutral['I']} / S {neutral['S']} / F {neutral['F']}."
            )
            current_alloc = {
                "G": st.number_input("G Fund %", min_value=0.0, max_value=100.0, value=float(cfg["current_alloc"]["G"]), step=1.0),
                "C": st.number_input("C Fund %", min_value=0.0, max_value=100.0, value=float(cfg["current_alloc"]["C"]), step=1.0),
                "I": st.number_input("I Fund %", min_value=0.0, max_value=100.0, value=float(cfg["current_alloc"]["I"]), step=1.0),
                "S": st.number_input("S Fund %", min_value=0.0, max_value=100.0, value=float(cfg["current_alloc"]["S"]), step=1.0),
                "F": st.number_input("F Fund %", min_value=0.0, max_value=100.0, value=float(cfg["current_alloc"]["F"]), step=1.0),
            }

        total_alloc = sum(current_alloc.values())
        if abs(total_alloc - 100.0) > 0.5:
            st.warning(f"Current allocation totals {total_alloc:.1f}%. Expected 100.0%.")

        with st.expander("🛡️ Rules", expanded=False):
            allow_second_ift = st.checkbox("Allow second IFT", value=bool(cfg["allow_second_ift"]))
            normal_drift_threshold_pct = st.number_input("Normal drift threshold %", value=float(cfg["normal_drift_threshold_pct"]), step=0.5)
            score_change_threshold = st.number_input("Score change threshold", value=int(cfg["score_change_threshold"]), step=1)
            confirmation_days = st.number_input("Confirmation days", value=int(cfg["confirmation_days"]), step=1)
            cooldown_days = st.number_input("Cooldown days", value=int(cfg["cooldown_days"]), step=1)
            use_live_macro = st.checkbox("Use live macro data", value=bool(cfg["use_live_macro"]))

        with st.expander("🛠️ Manual Override", expanded=False):
            manual_override_enabled = st.checkbox("Enable manual override", value=bool(cfg["manual_override_enabled"]))
            manual_regime_default = cfg.get("manual_regime", "OPTIMIZED_NEUTRAL")
            manual_regime_index = REGIME_ORDER.index(manual_regime_default) if manual_regime_default in REGIME_ORDER else 1
            manual_regime = st.selectbox("Override regime", REGIME_ORDER, index=manual_regime_index)

        st.divider()
        fred_api_key = st.text_input("FRED API Key", value=str(cfg.get("fred_api_key", "")), type="password")

        st.divider()
        run_clicked = st.button("🚀 Fetch & Run Engine", use_container_width=True, type="primary")
        confirm_clicked = st.button("✅ Submit IFT", use_container_width=True, disabled=not st.session_state.get("engine_ran", False))
        save_clicked = st.button("💾 Save Config", use_container_width=True)
        reset_state_clicked = st.button("♻️ Reset State", use_container_width=True)
        clear_logs_clicked = st.button("🗑️ Clear Log File", use_container_width=True)
        clear_tx_clicked = st.button("🗑️ Clear Audit Trail", use_container_width=True)

    # Handle config and state actions here, but keep them simple and explicit.
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
                "last_confirmation_key": None,
            }
        )
        st.session_state["last_engine_result"] = None
        st.session_state["engine_ran"] = False
        st.rerun()

    if clear_logs_clicked and LOG_FILE.exists():
        LOG_FILE.unlink()
        st.rerun()

    if clear_tx_clicked and TRANSACTION_FILE.exists():
        TRANSACTION_FILE.unlink()
        st.rerun()

    if run_clicked:
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

        market_data = load_editable_market_data()
        range_warnings = validate_market_data(market_data)
        st.session_state["market_data_warnings"] = range_warnings

        result = build_engine_result(
            market_data,
            override_active=manual_override_enabled,
            override_regime=manual_regime,
        )
        st.session_state["last_engine_result"] = result

        last_ift_date = date.fromisoformat(state["last_ift_date"]) if state.get("last_ift_date") else None
        use_ift, reason = should_use_tsp_ift(
            today=today,
            current_alloc=current_alloc,
            target_alloc=result.allocations,
            recent_regimes=state["recent_regimes"],
            recent_scores=state["recent_scores"],
            emergency_triggered=result.emergency_triggered,
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
        state["recent_regimes"].append(result.regime)
        state["recent_scores"].append(result.composite_score)
        state["recent_allocations"].append(result.allocations)
        state["last_run_date"] = today.isoformat()
        save_state(state)

        append_log_row(
            {
                "date": today.isoformat(),
                "action": action,
                "reason": reason,
                "regime": result.regime,
                "total_score": result.composite_score,
                "ift_count_this_month": state["ift_count_this_month"],
                "current_alloc": json.dumps(current_alloc),
                "target_alloc": json.dumps(result.allocations),
                "vix": market_data.get("vix_spot", DEFAULTS["vix_spot"]),
                "spx_200sma_dist": market_data.get("pct_dist_200_sma", 0.0),
                "drawdown_pct": market_data.get("drawdown_pct", 0.0),
            }
        )

    result = st.session_state.get("last_engine_result")
    if result is None:
        market_data = load_editable_market_data()
        result = build_engine_result(
            market_data,
            override_active=bool(cfg.get("manual_override_enabled", False)),
            override_regime=str(cfg.get("manual_regime", "OPTIMIZED_NEUTRAL")),
        )

    last_ift_date = date.fromisoformat(state["last_ift_date"]) if state.get("last_ift_date") else None
    use_ift, reason = should_use_tsp_ift(
        today=today,
        current_alloc=current_alloc,
        target_alloc=result.allocations,
        recent_regimes=state["recent_regimes"],
        recent_scores=state["recent_scores"],
        emergency_triggered=result.emergency_triggered,
        ift_count_this_month=state["ift_count_this_month"],
        last_ift_date=last_ift_date,
        allow_second_ift=allow_second_ift,
        normal_drift_threshold_pct=float(normal_drift_threshold_pct),
        score_change_threshold=int(score_change_threshold),
        confirmation_days=int(confirmation_days),
        cooldown_days=int(cooldown_days),
    )
    action = "SUBMIT IFT" if use_ift else "HOLD"

    if confirm_clicked:
        machine = IFTStateMachine.load(today)
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

    # Main display
    render_metric_cards(result.composite_score, result.regime, action, state["ift_count_this_month"], reason)
    render_snapshot_quality_badge(compute_snapshot_quality(get_current_market_sources()), st.session_state.get("engine_ran", False))

    tabs = st.tabs(["📈 Allocation", "🧠 Factors", "📊 Proxy Charts", "🕒 History", "📁 Logs & State"])

    with tabs[0]:
        est_now = get_est_now()
        if est_now.hour >= 12:
            st.warning(f"⚠️ Noon cutoff exceeded. Current time: {est_now.strftime('%I:%M %p')}")
        else:
            st.info(f"🕒 Execution window open. Current time: {est_now.strftime('%I:%M %p')}")

        if cfg.get("manual_override_enabled", False):
            st.warning(f"🛠️ Regime Lock Active: engine is bypassed; allocations are locked to {cfg.get('manual_regime')}.")

        cum_drift = cumulative_alloc_drift(current_alloc, result.allocations)
        st.markdown("### 🎚️ Portfolio Drift Runway")
        c1, c2 = st.columns([1, 3])
        with c1:
            st.metric("Cumulative Portfolio Drift", f"{cum_drift:.2f}%", f"{cum_drift - float(normal_drift_threshold_pct):+.2f}% vs Threshold")
        with c2:
            st.write(f"**Rebalance Threshold Progress**: `{cum_drift:.2f}%` / `{float(normal_drift_threshold_pct):.2f}%` required.")
            st.progress(min(cum_drift / float(normal_drift_threshold_pct), 1.0) if float(normal_drift_threshold_pct) > 0 else 1.0)

        st.markdown("### Allocation Comparison")
        st.dataframe(make_alloc_chart(result.allocations, current_alloc), use_container_width=True, hide_index=True)
        render_regime_cards(result.regime)

    with tabs[1]:
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

        st.markdown("### Market Snapshot")
        st.caption("Editable market inputs with the same card aesthetic.")
        market_warnings = st.session_state.get("market_data_warnings", [])
        if market_warnings:
            st.warning("⚠️ Some market inputs look outside plausible ranges:\n" + "\n".join(f"- {w}" for w in market_warnings))

        market_edit_items = [
            ("Core PCE YoY", "core_pce_yoy", st.session_state.get("core_pce_yoy_source")),
            ("ISM Manufacturing PMI", "ism_pmi", st.session_state.get("ism_pmi_source")),
            ("ISM Services PMI", "services_pmi", st.session_state.get("services_pmi_source")),
            ("Initial Claims (K)", "initial_claims", st.session_state.get("initial_claims_source")),
        ]
        # Continue rendering the remaining tiles exactly as your current layout expects.

        render_decision_breakdown(
            result=result,
            action=action,
            reason=reason,
            state=state,
            current_alloc=current_alloc,
            dxy_range_regime=st.session_state.get("dxy_range_regime", "UNKNOWN"),
            dxy_trend_up=st.session_state.get("dxy_trend_up", False),
            cooldown_days=int(cooldown_days),
            confirmation_days=int(confirmation_days),
            allow_second_ift=bool(allow_second_ift),
            normal_drift_threshold_pct=float(normal_drift_threshold_pct),
            score_change_threshold=int(score_change_threshold),
        )

    with tabs[2]:
        st.markdown("### Live TSP Fund Proxy Price Tracking")
        st.write("Proxy ETFs are used because TSP funds do not have direct tickers.")
        # Keep your existing proxy-chart logic here, but no policy logic.

    with tabs[3]:
        st.markdown("### Score History")
        score_df = make_score_chart(state)
        if score_df is not None:
            st.line_chart(score_df)
        else:
            st.info("No score history yet.")

    with tabs[4]:
        st.markdown("### Recent State Overview")
        recent_state_cards(state)
        st.markdown("### Run History Log")
        render_history_table(state)

        st.markdown("---")
        st.markdown("### Transaction History (Audit Trail)")
        if TRANSACTION_FILE.exists():
            tx_df = pd.read_csv(TRANSACTION_FILE).tail(25)
            st.dataframe(tx_df, use_container_width=True, hide_index=True)
        else:
            st.info("No physical portfolio transactions recorded yet.")

        st.markdown("---")
        st.markdown("### Daily Run Log Viewer")
        if LOG_FILE.exists():
            log_df = pd.read_csv(LOG_FILE)
            st.dataframe(log_df.tail(25), use_container_width=True, hide_index=True)
        else:
            st.info("No log file yet.")


if __name__ == "__main__":
    main()
