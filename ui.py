"""
Author: Donald J Anthony
Date: Today's Date

ui.py — Presentation helpers for Streamlit rendering.

Owns:
    - Cards, charts, tables, badges, and detailed breakdown views.
    - Rendering of the market snapshot, regime cards, metric cards, and decision breakdown.
    - Ensures that numbers (including each factor’s score) are displayed rounded to two decimal places for clarity.

Does not own:
    - Business/app logic
    - Data processing/modeling
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from constants import REGIME_DEFINITIONS, REGIME_ORDER
from models import EngineResult

# -----------------------------------------------------------------------------
# Helper Functions for Display
# -----------------------------------------------------------------------------
def _safe_text(value: any) -> str:
    """
    Return a display-safe string for a provided value.

    Parameters
    ----------
    value : any
        The value to be converted.

    Returns
    -------
    str
        String representation of the value, or an empty string if None.
    """
    if value is None:
        return ""
    return str(value)


def _source_pill_class(source: any) -> str:
    """
    Map a source label to a CSS pill class.

    Parameters
    ----------
    source : any
        The source label to be converted.

    Returns
    -------
    str
        CSS class name for the pill based on the source content.
    """
    source_str = _safe_text(source).upper()
    if "LIVE" in source_str:
        return "pill-live"
    if "FAILED" in source_str or "DEFAULT" in source_str or "OFFLINE" in source_str:
        return "pill-failed"
    return "pill-default"


def tile_html(title: str, value: str, note: str = "", icon: str = "", color: str = "#3b82f6", bg: str | None = None) -> str:
    """
    Build HTML for a KPI-style tile.

    Parameters
    ----------
    title : str
        Title for the tile.
    value : str
        Value to display within the tile.
    note : str, optional
        Additional note below the value.
    icon : str, optional
        Icon to prepend to the title.
    color : str, optional
        Color used for border accents and text.
    bg : str | None, optional
        Background color for the tile if provided.

    Returns
    -------
    str
        A string containing the HTML markup for the tile.
    """
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


# -----------------------------------------------------------------------------
# Snapshot Quality Badge
# -----------------------------------------------------------------------------
def render_snapshot_quality_badge(quality: dict[str, any], engine_ran: bool) -> None:
    """
    Render the live-data quality badge.

    If the engine has not run, an informational message is displayed to instruct the user.

    Parameters
    ----------
    quality : dict[str, any]
        Dictionary containing quality metrics (e.g., live_pct, border, color, bg, headline, and counts).
    engine_ran : bool
        Flag indicating whether the engine has executed.
    """
    if not engine_ran:
        st.info("Run **Fetch & Run Engine** to load market data and see how much of the snapshot is live.")
        return

    live_pct = float(quality["live_pct"])
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


# -----------------------------------------------------------------------------
# Metric Cards
# -----------------------------------------------------------------------------
def render_metric_cards(
    composite_score: float,
    regime: str,
    action: str,
    ift_count_this_month: int,
    reason: str,
) -> None:
    """
    Render the top-level metric cards on the dashboard.

    The composite score is displayed with two decimal places for clarity.

    Parameters
    ----------
    composite_score : float
        The engine's composite score.
    regime : str
        The detected market regime.
    action : str
        The recommended action (e.g., "SUBMIT IFT" or "HOLD").
    ift_count_this_month : int
        The count of IFTs executed in the current month.
    reason : str
        The rationale behind the engine's recommendation.
    """
    cols = st.columns(4)
    cards = [
        ("Composite Score", f"{composite_score:+.2f}", "Engine output", "📊", "#3b82f6"),
        ("Regime", regime, "Current market regime", "🧭", "#8b5cf6"),
        ("Action", action, reason, "✅", "#16a34a"),
        ("IFT Count", str(ift_count_this_month), "This month", "📁", "#f59e0b"),
    ]
    # Render each metric card by mapping each card tuple to a column.
    for col, (title, value, note, icon, color) in zip(cols, cards):
        with col:
            st.markdown(tile_html(title, value, note=note, icon=icon, color=color), unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# Grid and Editable Tiles
# -----------------------------------------------------------------------------
def render_tile_grid(items: list[dict[str, any]], columns: int = 4) -> None:
    """
    Render a responsive grid of KPI tiles.

    Parameters
    ----------
    items : list[dict[str, any]]
        List of dictionaries representing individual tile data.
    columns : int, optional
        Number of columns to display in the grid.
    """
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
                    bg=item.get("bg"),
                ),
                unsafe_allow_html=True,
            )


def render_editable_metric_tile(
    label: str,
    value: any,
    source: any,
    key: str,
    step: float = 0.1,
    fmt: str = "%.2f",
    color: str = "#3b82f6",
) -> None:
    """
    Render an editable metric tile for numeric, boolean, or text values.

    Displays a label, the current value (formatted appropriately), and a source indicator (pill).

    Parameters
    ----------
    label : str
        The label for the metric.
    value : any
        The current value of the metric.
    source : any
        The data source, used to select a corresponding CSS styling.
    key : str
        Unique key for the Streamlit widget.
    step : float, optional
        Numeric step increment (for number inputs).
    fmt : str, optional
        Format string for numeric display.
    color : str, optional
        Color used for edging the tile.
    """
    pill_class = _source_pill_class(source)
    label_text = _safe_text(label)
    source_text = _safe_text(source)
    is_bool = isinstance(value, bool)
    is_numeric = False
    display_value: any = value
    if not is_bool:
        try:
            display_value = float(value)
            is_numeric = True
        except Exception:
            is_numeric = False
    with st.container():
        if is_bool:
            shown = "Yes" if value else "No"
        elif is_numeric:
            shown = f"{float(display_value):.2f}"
        else:
            shown = _safe_text(value)
        # Render the tile with the metric information.
        st.markdown(
            f"""
            <div class="small-kpi" style="border-left: 5px solid {color}; margin-bottom: 0.4rem;">
                <div class="small-kpi-title">{label_text}</div>
                <div class="small-kpi-value" style="color:#0f172a; margin-top: 0.15rem;">{shown}</div>
                <div style="margin-top: 0.35rem;">
                    <span class="pill {pill_class}">{source_text}</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        # Render the appropriate Streamlit widget based on value's type.
        if is_bool:
            st.checkbox(label_text, value=bool(value), key=key, label_visibility="collapsed")
        elif is_numeric:
            st.number_input(label_text, value=float(display_value), step=step, format=fmt, key=key, label_visibility="collapsed")
        else:
            st.text_input(label_text, value=_safe_text(value), key=key, label_visibility="collapsed")


# -----------------------------------------------------------------------------
# State Display
# -----------------------------------------------------------------------------
def recent_state_cards(state: dict[str, any]) -> None:
    """
    Render a compact state summary card showing the last engine run timestamp.

    Parameters
    ----------
    state : dict[str, any]
        The current application state.
    """
    last_run = state.get("last_run_date") or "—"
    st.markdown(
        tile_html("Last Run", last_run, note="Most recent engine execution", icon="🕒", color="#3b82f6"),
        unsafe_allow_html=True,
    )


def render_history_table(state: dict[str, any]) -> None:
    """
    Render a table of recent run history from the state.

    Parameters
    ----------
    state : dict[str, any]
        The current application state containing recent history.
    """
    recent_regimes = state.get("recent_regimes", [])
    recent_scores = state.get("recent_scores", [])
    recent_allocations = state.get("recent_allocations", [])
    recent_run_dates = state.get("recent_run_dates", [])
    rows: list[dict[str, any]] = []
    n = max(len(recent_regimes), len(recent_scores), len(recent_allocations), len(recent_run_dates))
    for i in range(n):
        rows.append({
            "Index": i + 1,
            "Date": recent_run_dates[i] if i < len(recent_run_dates) else None,
            "Regime": recent_regimes[i] if i < len(recent_regimes) else None,
            "Score": recent_scores[i] if i < len(recent_scores) else None,
            "Allocation": recent_allocations[i] if i < len(recent_allocations) else None,
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)


def make_score_chart(state: dict[str, any]) -> pd.DataFrame | None:
    """
    Build a score history DataFrame with dates on the x-axis.

    Parameters
    ----------
    state : dict[str, any]
        The application state containing recent scores and run dates.

    Returns
    -------
    pd.DataFrame | None
        A DataFrame with Date as the index and Score values, or None if empty.
    """
    scores = state.get("recent_scores", [])
    dates = state.get("recent_run_dates", [])
    if not scores:
        return None
    if len(dates) != len(scores):
        return pd.DataFrame({"Score": scores})
    df = pd.DataFrame({
        "Date": pd.to_datetime(dates, errors="coerce"),
        "Score": scores,
    }).dropna(subset=["Date"])
    if df.empty:
        return pd.DataFrame({"Score": scores})
    return df.set_index("Date")


def make_alloc_chart(target_alloc: dict[str, float], current_alloc: dict[str, float]) -> pd.DataFrame:
    """
    Build a fund allocation comparison DataFrame.

    Parameters
    ----------
    target_alloc : dict[str, float]
        The target allocation percentages.
    current_alloc : dict[str, float]
        The current allocation percentages.

    Returns
    -------
    pd.DataFrame
        A DataFrame comparing current and target allocations along with the delta.
    """
    rows: list[dict[str, any]] = []
    for fund in ["G", "C", "I", "S", "F"]:
        rows.append({
            "Fund": fund,
            "Current %": float(current_alloc.get(fund, 0.0)),
            "Target %": float(target_alloc.get(fund, 0.0)),
            "Delta %": float(target_alloc.get(fund, 0.0)) - float(current_alloc.get(fund, 0.0))
        })
    return pd.DataFrame(rows)


# -----------------------------------------------------------------------------
# Regime Cards
# -----------------------------------------------------------------------------
def _regime_alloc_display(name: str, info: dict[str, any]) -> str:
    """
    Format a regime allocation for display purposes.

    Parameters
    ----------
    name : str
        The regime name.
    info : dict[str, any]
        Information dictionary containing allocation and display settings.

    Returns
    -------
    str
        A formatted string representing the allocation.
    """
    if "alloc_display" in info:
        return str(info["alloc_display"])
    alloc = info.get("allocation", {})
    fund_order = ["G", "C", "I", "S", "F"]
    return " / ".join(f"{fund} {alloc.get(fund, 0)}%" for fund in fund_order)


def _render_single_regime_card(name: str, info: dict[str, any], is_active: bool) -> None:
    """
    Render a single regime card with styling based on active status.

    Parameters
    ----------
    name : str
        The regime name.
    info : dict[str, any]
        The regime metadata including icon, color, and description.
    is_active : bool
        Flag indicating whether this regime is currently active.
    """
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


def render_regime_cards(active_regime: str) -> None:
    """
    Render the strategic regime directory cards.

    Parameters
    ----------
    active_regime : str
        Name of the currently active regime.
    """
    st.markdown("### 🧭 Strategic Regime Directory")
    st.caption("The engine maps composite score to one of the policy regimes below.")
    cols = st.columns(len(REGIME_ORDER))
    for col, name in zip(cols, REGIME_ORDER):
        info = REGIME_DEFINITIONS[name]
        with col:
            _render_single_regime_card(name, info, active_regime == name)


# -----------------------------------------------------------------------------
# Decision Breakdown
# -----------------------------------------------------------------------------
# FACTOR_ROWS contains tuples mapping display names to score keys and source descriptions.
FACTOR_ROWS: list[tuple[str, str, str]] = [
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
    result: EngineResult,
    action: str,
    reason: str,
    state: dict[str, any],
    current_alloc: dict[str, float],
    dxy_range_regime: str,
    dxy_trend_up: bool,
    cooldown_days: int,
    confirmation_days: int,
    allow_second_ift: bool,
    normal_drift_threshold_pct: float,
    score_change_threshold: int,
) -> None:
    """
    Render a detailed breakdown of the engine's decision.

    This breakdown includes a summary of core metrics, factor score details, and
    interpretations that lead to the final IFT recommendation.

    Parameters
    ----------
    result : EngineResult
        Engine output containing allocations, scores, and decision flags.
    action : str
        Final recommended action (e.g., "SUBMIT IFT").
    reason : str
        Explanation for the decision.
    state : dict[str, any]
        Application state containing IFT counts and history.
    current_alloc : dict[str, float]
        Current portfolio allocation.
    dxy_range_regime : str
        The qualitative DXY regime.
    dxy_trend_up : bool
        Flag indicating if the DXY is trending upward.
    cooldown_days : int
        The number of days enforced as a cooldown period.
    confirmation_days : int
        The required number of stable days for confirmation.
    allow_second_ift : bool
        Flag indicating if a second IFT is permitted.
    normal_drift_threshold_pct : float
        The threshold percentage for acceptable portfolio drift.
    score_change_threshold : int
        The minimum score change required to trigger rebalancing.
    """
    st.markdown("### 🔍 Engine Decision Breakdown")
    with st.expander("📖 Detailed Decision Trace & Factor Attribution", expanded=False):
        st.markdown("#### 1) Decision Summary")
        sum_cols = st.columns(4)
        with sum_cols[0]:
            st.markdown(f"**Regime**  \n{result.regime}")
        with sum_cols[1]:
            st.markdown(f"**Composite Score**  \n{result.composite_score:+.2f}")
        with sum_cols[2]:
            st.markdown(f"**Action**  \n{action}")
        with sum_cols[3]:
            st.markdown(f"**Emergency Trigger**  \n{'Yes' if result.emergency_triggered else 'No'}")
        st.caption(f"IFT Decision Reason: {reason}")

        st.markdown("#### 2) Factor Score Detail")
        factor_rows: list[dict[str, any]] = []
        for display_name, score_key, source_text in FACTOR_ROWS:
            raw_score = result.scores.get(score_key, 0)
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
                "Raw Score": f"{raw_score:.2f}",
                "Interpretation": strength,
                "Source / Logic": source_text,
            })
        st.dataframe(pd.DataFrame(factor_rows), use_container_width=True, hide_index=True)

        st.markdown("#### 3) Factor Interpretation")
        pos_factors: list[str] = []
        neg_factors: list[str] = []
        neu_factors: list[str] = []
        for display_name, score_key, _ in FACTOR_ROWS:
            val = result.scores.get(score_key, 0)
            if val > 0:
                pos_factors.append(f"{display_name} (+{val:.2f} pts)")
            elif val < 0:
                neg_factors.append(f"{display_name} ({val:.2f} pts)")
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
            st.write(f"- Selected regime: `{result.regime}`")
            st.write(f"- Composite score: `{result.composite_score:+.2f}`")
            st.write(f"- Emergency trigger: `{'Yes' if result.emergency_triggered else 'No'}`")
            st.write(f"- Base allocation: `{result.base_alloc}`")
        with build_cols[1]:
            st.markdown("**Adjustment Flags**")
            st.write(f"- F Fund unlocked: `{'Yes' if result.base_alloc.get('F', 0) > 0 else 'No'}`")
            st.write(f"- Asymmetric volatility trigger: `{'Yes' if result.asymmetric_vol_trigger else 'No'}`")
            st.write(f"- DXY regime: `{dxy_range_regime}`")
            st.write(f"- DXY trend up: `{'Yes' if dxy_trend_up else 'No'}`")
            st.write(f"- Strong DXY adjustment: `{'Yes' if result.dxy_strong else 'No'}`")
            st.write(f"- Macro overlays active: `{'Yes' if any(result.scores.get(k, 0) != 0 for k in ['yield_curve','inflation_shock','central_bank','liquidity_pressure']) else 'No'}`")
        st.markdown("**Final Target Allocation**")
        st.dataframe(make_alloc_chart(result.allocations, current_alloc),
                     use_container_width=True,
                     hide_index=True)

        st.markdown("#### 5) IFT Decision Logic")
        ift_cols = st.columns(4)
        with ift_cols[0]:
            st.metric("Monthly IFT Count", str(state.get("ift_count_this_month", 0)))
        with ift_cols[1]:
            st.metric("Cooldown", f"{cooldown_days} days")
        with ift_cols[2]:
            st.metric("Confirmation Days", str(confirmation_days))
        with ift_cols[3]:
            st.metric("Allow 2nd IFT", "Yes" if allow_second_ift else "No")
        st.write(f"- Normal drift threshold: `{float(normal_drift_threshold_pct):.2f}%`")
        st.write(f"- Score change threshold: `{int(score_change_threshold)}`")
        st.write(f"- Confirmation rule: requires {confirmation_days} stable days plus 1 prior point for score-change comparison.")
        st.write(f"- Recent regime history: `{state.get('recent_regimes', [])[-(confirmation_days + 1):]}`")
        st.write(f"- Recent score history: `{state.get('recent_scores', [])[-(confirmation_days + 1):]}`")
        st.write(f"- Final IFT recommendation: **{action}**")
        st.write(f"- Reason: {reason}")


# -----------------------------------------------------------------------------
# __all__ Declaration
# -----------------------------------------------------------------------------
__all__ = [
    "_safe_text",
    "_source_pill_class",
    "tile_html",
    "render_snapshot_quality_badge",
    "render_metric_cards",
    "render_tile_grid",
    "render_editable_metric_tile",
    "recent_state_cards",
    "render_history_table",
    "make_score_chart",
    "make_alloc_chart",
    "render_regime_cards",
    "render_decision_breakdown",
]
