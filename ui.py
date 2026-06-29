import pandas as pd
import streamlit as st

def source_pill_html(source: str) -> str:
    source_upper = str(source).upper()
    if "FAILED" in source_upper or "DEFAULT" in source_upper or "FALLBACK" in source_upper:
        cls = "pill-failed"
    elif "LIVE" in source_upper:
        cls = "pill-live"
    else:
        cls = "pill-default"
    return f"<span class='pill {cls}'>{source}</span>"

def score_card_html(label: str, value, note: str, color: str, icon: str) -> str:
    return f"""
    <div class="small-kpi" style="border-left: 5px solid {color}; margin-bottom:0.6rem;">
        <div class="small-kpi-title">{label}</div>
        <div class="small-kpi-value" style="color:{color};">{icon} {value}</div>
        <div class="small-kpi-note">{note}</div>
    </div>
    """

def render_metric_cards(total_score, regime, action, ift_used, reason):
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.markdown(f"""
        <div class="small-kpi" style="border-left: 5px solid #3b82f6;">
            <div class="small-kpi-title">Composite Score</div>
            <div class="small-kpi-value">{total_score}</div>
            <div class="small-kpi-note">Higher is more risk-on</div>
        </div>
        """, unsafe_allow_html=True)
    with c2:
        action_color = "#dc2626" if regime == "EMERGENCY DISPATCH" else ("#22c55e" if action == "SUBMIT IFT" else "#64748b")
        st.markdown(f"""
        <div class="small-kpi" style="border-left: 5px solid {action_color};">
            <div class="small-kpi-title">Action</div>
            <div class="small-kpi-value" style="color:{action_color};">{action}</div>
            <div class="small-kpi-note">Decision recommendation</div>
        </div>
        """, unsafe_allow_html=True)
    with c3:
        st.markdown(f"""
        <div class="small-kpi" style="border-left: 5px solid #f59e0b;">
            <div class="small-kpi-title">IFTs Used</div>
            <div class="small-kpi-value">{ift_used}/2</div>
            <div class="small-kpi-note">Monthly transfer count</div>
        </div>
        """, unsafe_allow_html=True)
    with c4:
        st.markdown(f"""
        <div class="small-kpi" style="border-left: 5px solid #a78bfa;">
            <div class="small-kpi-title">Regime</div>
            <div class="small-kpi-value" style="font-size:1.0rem;">{regime}</div>
            <div class="small-kpi-note">Model state</div>
        </div>
        """, unsafe_allow_html=True)
    with c5:
        reason_color = "#dc2626" if regime == "EMERGENCY DISPATCH" else ("#16a34a" if action == "SUBMIT IFT" else "#64748b")
        st.markdown(f"""
        <div class="small-kpi" style="border-left: 5px solid {reason_color};">
            <div class="small-kpi-title">IFT Reason</div>
            <div class="small-kpi-value" style="font-size:0.95rem; color:{reason_color}; line-height:1.2;">
                {reason}
            </div>
            <div class="small-kpi-note">Why this action was chosen</div>
        </div>
        """, unsafe_allow_html=True)

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
