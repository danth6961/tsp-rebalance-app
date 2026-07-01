import pandas as pd
import streamlit as st

from constants import REGIME_DEFINITIONS, REGIME_ORDER


def _safe_text(value):
    if value is None:
        return ""
    return str(value)


def _source_pill_class(source):
    source_str = _safe_text(source).upper()
    if "LIVE" in source_str:
        return "pill-live"
    if "FAILED" in source_str or "DEFAULT" in source_str or "OFFLINE" in source_str:
        return "pill-failed"
    return "pill-default"


def tile_html(title, value, note=None, icon=None, color="#3b82f6", bg=None):
    title = _safe_text(title)
    value = _safe_text(value)
    note = _safe_text(note)

    bg_style = f"background-color: {bg};" if bg else ""
    icon_html = f"{icon} " if icon else ""
    note_html = f"<div class='small-kpi-note'>{note}</div>" if note else ""

    return f"""
    <div class="small-kpi" style="border-left: 5px solid {color}; {bg_style}">
        <div class="small-kpi-title">{icon_html}{title}</div>
        <div class="small-kpi-value" style="color:#0f172a;">{value}</div>
        {note_html}
    </div>
    """


def render_snapshot_quality_badge(quality: dict, engine_ran: bool):
    if not engine_ran:
        st.info("Run **Fetch & Run Engine** to load market data and see how much of the snapshot is live.")
        return

    live_pct = quality["live_pct"]
    st.markdown(
        f"""
        <div class="small-kpi" style="border: 1px solid {quality['border']}; border-left: 5px solid {quality['color']}; background-color: {quality['bg']}; margin-bottom: 1rem;">
            <div style="display:flex; justify-content:space-between; gap:1rem; align-items:center; flex-wrap:wrap;">
                <div>
                    <div class="small-kpi-title">Live Data Quality</div>
                    <div class="small-kpi-value" style="color:{quality['color']};">{live_pct:.1f}% live</div>
                    <div class="small-kpi-note">{quality['headline']}</div>
                </div>
                <div style="font-size:0.85rem; color:#475569; line-height:1.6;">
                    <div><strong>{quality['live_count']}</strong> live</div>
                    <div><strong>{quality['derived_count']}</strong> derived</div>
                    <div><strong>{quality['fallback_count']}</strong> placeholder</div>
                    <div><strong>{quality['total_count']}</strong> total inputs</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if quality["fallback_fields"]:
        with st.expander(
            f"Placeholder inputs ({quality['fallback_count']}) — using saved defaults, not fresh market data",
            expanded=quality["level"] == "low",
        ):
            for _, label, source in quality["fallback_fields"]:
                st.markdown(f"- **{label}** — `{source}`")

    if quality["derived_fields"]:
        with st.expander(f"Derived inputs ({quality['derived_count']}) — calculated from other fields"):
            for _, label, source in quality["derived_fields"]:
                st.markdown(f"- **{label}** — `{source}`")


def render_metric_cards(composite_score, regime, action, ift_count_this_month, reason):
    cols = st.columns(4)

    cards = [
        ("Composite Score", f"{composite_score:+.2f}", "Engine output", "📊", "#3b82f6"),
        ("Regime", regime, "Current market regime", "🧭", "#8b5cf6"),
        ("Action", action, reason, "✅", "#16a34a" if action == "SUBMIT IFT" else "#64748b"),
        ("IFT Count", str(ift_count_this_month), "This month", "📁", "#f59e0b"),
    ]

    for col, (title, value, note, icon, color) in zip(cols, cards):
        with col:
            st.markdown(tile_html(title, value, note=note, icon=icon, color=color), unsafe_allow_html=True)


def render_tile_grid(items, columns=4):
    if not items:
        return

    cols = st.columns(columns)
    for idx, item in enumerate(items):
        with cols[idx % columns]:
            st.markdown(
                tile_html(
                    item.get("label", ""),
                    item.get("value", ""),
                    note=item.get("note", ""),
                    icon=item.get("icon", ""),
                    color=item.get("color", "#3b82f6"),
                    bg=item.get("bg", None),
                ),
                unsafe_allow_html=True,
            )


def render_editable_metric_tile(label, value, source, key, step=0.1, fmt="%.2f", color="#3b82f6"):
    """
    Streamlit-safe metric tile that supports numeric, boolean, and text values.
    - numeric values: editable via number_input
    - booleans: editable via checkbox
    - strings: editable via text_input only when non-numeric
    """
    pill_class = _source_pill_class(source)
    label_text = _safe_text(label)
    source_text = _safe_text(source)

    # Determine value type
    is_bool = isinstance(value, bool)
    is_numeric = False
    display_value = value

    if not is_bool:
        try:
            display_value = float(value)
            is_numeric = True
        except Exception:
            is_numeric = False

    with st.container(border=True):
        if is_bool:
            shown = "Yes" if value else "No"
        elif is_numeric:
            shown = f"{float(display_value):.2f}"
        else:
            shown = _safe_text(value)

        st.markdown(
            f"""
            <div class="small-kpi" style="border-left: 5px solid {color}; margin-bottom: 0.4rem;">
                <div class="small-kpi-title">{label_text}</div>
                <div class="small-kpi-value" style="color:#0f172a; margin-top: 0.15rem;">
                    {shown}
                </div>
                <div style="margin-top: 0.35rem;">
                    <span class="pill {pill_class}">{source_text}</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if is_bool:
            st.checkbox(
                label_text,
                value=bool(value),
                key=key,
                label_visibility="collapsed",
            )
        elif is_numeric:
            st.number_input(
                label_text,
                value=float(display_value),
                step=step,
                format=fmt,
                key=key,
                label_visibility="collapsed",
            )
        else:
            st.text_input(
                label_text,
                value=_safe_text(value),
                key=key,
                label_visibility="collapsed",
            )


def recent_state_cards(state):
    cols = st.columns(3)

    last_run = state.get("last_run_date") or "—"
    last_ift = state.get("last_ift_date") or "—"
    ift_count = state.get("ift_count_this_month", 0)

    items = [
        ("Last Run", last_run, "Most recent engine execution", "🕒", "#3b82f6"),
        ("Last IFT", last_ift, "Most recent submission", "📨", "#10b981"),
        ("IFT Count", str(ift_count), "This month", "📌", "#f59e0b"),
    ]

    for col, (title, value, note, icon, color) in zip(cols, items):
        with col:
            st.markdown(tile_html(title, value, note=note, icon=icon, color=color), unsafe_allow_html=True)


def render_history_table(state):
    recent_regimes = state.get("recent_regimes", [])
    recent_scores = state.get("recent_scores", [])
    recent_allocations = state.get("recent_allocations", [])

    rows = []
    n = max(len(recent_regimes), len(recent_scores), len(recent_allocations))
    for i in range(n):
        rows.append({
            "Index": i + 1,
            "Regime": recent_regimes[i] if i < len(recent_regimes) else None,
            "Score": recent_scores[i] if i < len(recent_scores) else None,
            "Allocation": recent_allocations[i] if i < len(recent_allocations) else None,
        })

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)


def make_score_chart(state):
    scores = state.get("recent_scores", [])
    if not scores:
        return None
    return pd.DataFrame({"Score": scores})


def make_alloc_chart(target_alloc, current_alloc):
    rows = []
    for fund in ["G", "C", "I", "S", "F"]:
        rows.append({
            "Fund": fund,
            "Current %": float(current_alloc.get(fund, 0.0)),
            "Target %": float(target_alloc.get(fund, 0.0)),
            "Delta %": float(target_alloc.get(fund, 0.0)) - float(current_alloc.get(fund, 0.0)),
        })
    return pd.DataFrame(rows)


def _regime_alloc_display(name: str, info: dict) -> str:
    if "alloc_display" in info:
        return info["alloc_display"]
    alloc = info["allocation"]
    fund_order = ["G", "C", "I", "S", "F"]
    return " / ".join(f"{fund} {alloc.get(fund, 0)}%" for fund in fund_order)


def _render_single_regime_card(name: str, info: dict, is_active: bool):
    border = info["color"] if is_active else "rgba(148,163,184,0.18)"
    bg = info["bg"] if is_active else "rgba(248, 250, 252, 0.5)"
    badge = "★ ACTIVE ENVIRONMENT" if is_active else ""
    badge_color = info["color"] if is_active else "#64748b"
    alloc_text = _regime_alloc_display(name, info)

    st.markdown(
        f"""
        <div class="small-kpi" style="border-left: 5px solid {border}; background-color: {bg}; min-height: 250px;">
            <div style="color: {badge_color}; font-weight: 800; font-size: 0.72rem; text-transform: uppercase; margin-bottom: 0.35rem;">{badge}</div>
            <div style="font-weight: 800; font-size: 0.95rem; color: {info['color']};">{info['icon']} {name}</div>
            <div style="font-size: 0.75rem; font-weight: 600; color: #64748b; margin-bottom: 0.6rem;">{info['profile']} • {info['score_label']}</div>
            <div style="font-size: 0.8rem; font-weight: 700; margin-bottom: 0.6rem; color: {info['color']};">Base: {alloc_text}</div>
            <div style="font-size: 0.78rem; color: #64748b; line-height: 1.35;">{info['description']}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_regime_cards(active_regime: str):
    """Render the strategic regime directory cards.

    Regime metadata (name, allocation, description, color) comes from
    constants.REGIME_DEFINITIONS, the single source of truth, so these
    cards can never drift from what engine.py actually computes.
    """
    st.markdown("### 🧭 Strategic Regime Directory")
    st.caption("The engine maps the overall composite score to one of the four policy regimes below to determine baseline targets:")

    cols = st.columns(len(REGIME_ORDER))
    for col, name in zip(cols, REGIME_ORDER):
        info = REGIME_DEFINITIONS[name]
        with col:
            _render_single_regime_card(name, info, active_regime == name)


FACTOR_ROWS = [
    ("Inflation", "inflation", "Core PCE / Breakevens"),
    ("Growth", "growth", "PMI / Services PMI / Claims"),
    ("Liquidity", "liquidity", "SLOOS / Fed Assets Growth"),
    ("Credit Spreads", "credit_spreads", "HY OAS"),
    ("Valuation", "valuation", "Shiller CAPE / Real Yield"),
    ("Market Stress", "market_stress", "VIX / STLFSI"),
    ("Momentum", "momentum", "200SMA distance / STLFSI"),
    ("Drawdown", "drawdown", "Peak-to-trough decline"),
    ("Yield Curve", "yield_curve", "10Y - 3M Treasury Spread"),
    ("Inflation Shock", "inflation_shock", "Inflation surprise vs anchor"),
    ("Central Bank", "central_bank", "Fed stance / real yields / curve"),
    ("Liquidity Pressure", "liquidity_pressure", "SLOOS / Fed assets / STLFSI / MOVE"),
]


def render_decision_breakdown(
    result: dict,
    action: str,
    reason: str,
    state: dict,
    current_alloc: dict,
    dxy_range_regime: str,
    dxy_trend_up: bool,
    cooldown_days: int,
    confirmation_days: int,
    allow_second_ift: bool,
    normal_drift_threshold_pct: float,
    score_change_threshold: int,
):
    """Render the full 'Engine Decision Breakdown' expander.

    This is a pure rendering function: all decision logic (scores, regime,
    IFT gating) is computed upstream by engine.py and passed in. ui.py never
    makes tactical decisions, it only presents them.
    """
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
        factor_rows = []
        for display_name, score_key, source_text in FACTOR_ROWS:
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
        pos_factors, neg_factors, neu_factors = [], [], []
        for display_name, score_key, _ in FACTOR_ROWS:
            val = result["scores"].get(score_key, 0)
            if val > 0:
                pos_factors.append(f"{display_name} (+{val} pts)")
            elif val < 0:
                neg_factors.append(f"{display_name} ({val} pts)")
            else:
                neu_factors.append(display_name)

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
            st.write(f"- DXY regime: `{dxy_range_regime}`")
            st.write(f"- DXY trend up: `{'Yes' if dxy_trend_up else 'No'}`")
            st.write(f"- Strong DXY adjustment: `{'Yes' if result['dxy_strong'] else 'No'}`")
            st.write(f"- Macro overlays active: `{'Yes' if any(result['scores'].get(k, 0) != 0 for k in ['yield_curve', 'inflation_shock', 'central_bank', 'liquidity_pressure']) else 'No'}`")

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
