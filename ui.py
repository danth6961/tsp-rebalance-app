import streamlit as st
import pandas as pd


def _safe_text(value):
    if value is None:
        return ""
    return str(value)


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
        col = cols[idx % columns]
        with col:
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
    Unified editable tile:
    - title
    - current value
    - source pill
    - editable number input
    """

    source_str = str(source).upper()
    pill_class = (
        "pill-live" if "LIVE" in source_str
        else "pill-failed" if ("FAILED" in source_str or "DEFAULT" in source_str or "OFFLINE" in source_str)
        else "pill-default"
    )

    try:
        display_value = float(value)
    except Exception:
        display_value = 0.0

    with st.container(border=True):
        st.markdown(
            f"""
            <div class="editable-kpi-card" style="border-left: 5px solid {color};">
                <div class="editable-kpi-header">
                    <div class="small-kpi-title">{label}</div>
                    <span class="pill {pill_class}">{_safe_text(source)}</span>
                </div>

                <div class="small-kpi-value" style="color:#0f172a; margin-top: 0.35rem;">
                    {display_value:.2f}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.number_input(
            label,
            value=display_value,
            step=step,
            format=fmt,
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
