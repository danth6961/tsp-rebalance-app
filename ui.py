import pandas as pd
import streamlit as st


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
