import pandas as pd
import streamlit as st


def tile_html(label: str, value: str, note: str = "", color: str = "#64748b", icon: str = "●") -> str:
    note_html = f'<div class="small-kpi-note">{note}</div>' if note else ""
    icon_html = f"{icon} " if icon else ""
    return f"""
    <div class="small-kpi" style="border-left: 5px solid {color}; margin-bottom:0.6rem;">
        <div class="small-kpi-title">{label}</div>
        <div class="small-kpi-value" style="color:{color};">{icon_html}{value}</div>
        {note_html}
    </div>
    """


def render_metric_cards(total_score, regime, action, ift_used, reason):
    c1, c2, c3, c4, c5 = st.columns(5)

    with c1:
        st.markdown(
            tile_html("Composite Score", str(total_score), "Higher is more risk-on", "#3b82f6", ""),
            unsafe_allow_html=True,
        )

    with c2:
        action_color = "#dc2626" if regime == "EMERGENCY DISPATCH" else ("#22c55e" if action == "SUBMIT IFT" else "#64748b")
        st.markdown(
            tile_html("Action", action, "Decision recommendation", action_color, ""),
            unsafe_allow_html=True,
        )

    with c3:
        st.markdown(
            tile_html("IFTs Used", f"{ift_used}/2", "Monthly transfer count", "#f59e0b", ""),
            unsafe_allow_html=True,
        )

    with c4:
        st.markdown(
            tile_html("Regime", regime, "Model state", "#a78bfa", ""),
            unsafe_allow_html=True,
        )

    with c5:
        reason_color = "#dc2626" if regime == "EMERGENCY DISPATCH" else ("#16a34a" if action == "SUBMIT IFT" else "#64748b")
        st.markdown(
            tile_html("IFT Reason", reason, "Why this action was chosen", reason_color, ""),
            unsafe_allow_html=True,
        )


def make_score_chart(state):
    if not state.get("recent_scores"):
        return None
    return pd.DataFrame({
        "Run": list(range(1, len(state["recent_scores"]) + 1)),
        "Score": state["recent_scores"],
    }).set_index("Run")


def make_alloc_chart(target_alloc, current_alloc):
    funds = ["G", "C", "I", "S", "F"]
    return pd.DataFrame({
        "Fund": funds,
        "Current": [current_alloc.get(f, 0.0) for f in funds],
        "Target": [target_alloc.get(f, 0.0) for f in funds],
    })


def render_tile_grid(items, columns=4):
    cols = st.columns(columns)
    for i, item in enumerate(items):
        with cols[i % columns]:
            st.markdown(
                tile_html(
                    item["label"],
                    item["value"],
                    item.get("note", ""),
                    item.get("color", "#64748b"),
                    item.get("icon", "●"),
                ),
                unsafe_allow_html=True,
            )


def recent_state_cards(state):
    items = [
        {
            "label": "Current Tracking Month",
            "value": state.get("month", "N/A"),
            "note": "Current cycle",
            "color": "#3b82f6",
            "icon": "🗓️",
        },
        {
            "label": "IFTs Used",
            "value": f"{state.get('ift_count_this_month', 0)} / 2",
            "note": "Monthly count",
            "color": "#f59e0b",
            "icon": "🔁",
        },
        {
            "label": "Last IFT Date",
            "value": state.get("last_ift_date") or "None",
            "note": "Most recent transfer",
            "color": "#a78bfa",
            "icon": "📅",
        },
        {
            "label": "Last Run Date",
            "value": state.get("last_run_date") or "None",
            "note": "Most recent engine run",
            "color": "#10b981",
            "icon": "🕒",
        },
    ]
    render_tile_grid(items, columns=4)


def render_history_table(state):
    history_data = []
    regimes = state.get("recent_regimes", [])
    scores = state.get("recent_scores", [])
    allocations = state.get("recent_allocations", [])

    max_len = max(len(regimes), len(scores), len(allocations))
    for idx in range(max_len):
        regime = regimes[idx] if idx < len(regimes) else "N/A"
        score = scores[idx] if idx < len(scores) else "N/A"
        alloc = allocations[idx] if idx < len(allocations) else {}
        alloc_str = " / ".join([f"{k} {alloc.get(k, 0.0):.1f}%" for k in ["G", "C", "I", "S", "F"]]) if alloc else "N/A"
        history_data.append({
            "Run": idx + 1,
            "Regime": regime,
            "Score": score,
            "Target Allocation": alloc_str,
        })

    if history_data:
        st.dataframe(pd.DataFrame(history_data).iloc[::-1], use_container_width=True, hide_index=True)
    else:
        st.info("No historical runs tracked yet.")
