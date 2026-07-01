"""
styles.py — CSS and visual tokens for the Streamlit app.

Owns:
- design tokens (color, type, spacing, radius, shadow)
- layout spacing
- card / KPI tile styling
- pill / badge styling
- header ribbon styling
- Streamlit widget theming (buttons, tabs, expanders, dataframes, metrics)
- reusable visual tokens

Does not own:
- app logic
- rendering logic
- data logic
- regime logic

Design language
----------------
The app reads as an institutional macro/allocation terminal: a quiet,
paper-white workspace with a navy command layer and a restrained brass/gold
accent (a nod to the "Treasury" subject matter — TSP is a federal
retirement plan). Data values are set in a monospace face with tabular
figures so numbers align the way they would on a real trading desk;
everything else uses a clean grotesk so the UI stays legible and current.
"""

from __future__ import annotations

import streamlit as st


# -----------------------------------------------------------------------------
# Central style payload
# -----------------------------------------------------------------------------
# Keep all visual rules here so app.py can stay a thin orchestration layer.
# The UI layer should rely on these class names rather than inlining CSS.
# -----------------------------------------------------------------------------
APP_STYLES: str = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@500;700;800&family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@500;600;700&display=swap');

/* ---------------------------------------------------------------------- */
/* Design tokens                                                          */
/* ---------------------------------------------------------------------- */
:root {
    --tsp-bg: #F6F7FA;
    --tsp-bg-alt: #EEF1F6;
    --tsp-surface: #FFFFFF;
    --tsp-border: #E3E7EE;
    --tsp-border-strong: #CBD3E0;
    --tsp-ink: #0B1526;
    --tsp-ink-soft: #4B5568;
    --tsp-ink-faint: #8A93A6;

    --tsp-navy: #10192E;
    --tsp-navy-soft: #1D2C4E;
    --tsp-navy-wash: rgba(16, 25, 46, 0.04);

    --tsp-gold: #B4893D;
    --tsp-gold-soft: #E7D3A6;
    --tsp-gold-wash: rgba(180, 137, 61, 0.12);

    --tsp-green: #10b981;
    --tsp-blue: #3b82f6;
    --tsp-amber: #f59e0b;
    --tsp-red: #ef4444;

    --tsp-radius-sm: 8px;
    --tsp-radius-md: 12px;
    --tsp-radius-lg: 18px;

    --tsp-shadow-xs: 0 1px 2px rgba(16, 25, 46, 0.05);
    --tsp-shadow-sm: 0 2px 6px -2px rgba(16, 25, 46, 0.08), 0 1px 2px rgba(16, 25, 46, 0.04);
    --tsp-shadow-md: 0 12px 24px -10px rgba(16, 25, 46, 0.16), 0 4px 8px -4px rgba(16, 25, 46, 0.08);
    --tsp-shadow-lg: 0 24px 48px -16px rgba(16, 25, 46, 0.28);

    --tsp-font-display: 'Manrope', 'Inter', -apple-system, sans-serif;
    --tsp-font-body: 'Inter', -apple-system, sans-serif;
    --tsp-font-mono: 'IBM Plex Mono', 'SFMono-Regular', ui-monospace, Menlo, monospace;
}

/* ---------------------------------------------------------------------- */
/* Base canvas                                                            */
/* ---------------------------------------------------------------------- */
[data-testid="stAppViewContainer"] {
    background:
        radial-gradient(1200px 480px at 12% -8%, rgba(180, 137, 61, 0.06), transparent 60%),
        var(--tsp-bg);
}

html, body, [class*="css"] {
    font-family: var(--tsp-font-body);
    color: var(--tsp-ink);
}

.block-container {
    padding-top: 1.6rem;
    padding-bottom: 3rem;
    padding-left: 2.2rem;
    padding-right: 2.2rem;
    max-width: 1500px;
}

h1, h2, h3, h4, h5, [data-testid="stMarkdownContainer"] h1,
[data-testid="stMarkdownContainer"] h2, [data-testid="stMarkdownContainer"] h3 {
    font-family: var(--tsp-font-display) !important;
    font-weight: 800 !important;
    letter-spacing: -0.015em;
    color: var(--tsp-ink) !important;
}

[data-testid="stMarkdownContainer"] h3 {
    font-size: 1.1rem !important;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    font-weight: 800 !important;
    color: var(--tsp-navy) !important;
    border-left: 3px solid var(--tsp-gold);
    padding-left: 0.6rem;
    margin-top: 0.4rem !important;
}

[data-testid="stCaptionContainer"], .stCaption, small {
    color: var(--tsp-ink-faint) !important;
}

hr {
    border: none;
    border-top: 1px solid var(--tsp-border);
    margin: 1.4rem 0;
}

::selection {
    background: var(--tsp-gold-soft);
}

*::-webkit-scrollbar {
    width: 10px;
    height: 10px;
}
*::-webkit-scrollbar-track {
    background: transparent;
}
*::-webkit-scrollbar-thumb {
    background: var(--tsp-border-strong);
    border-radius: 999px;
    border: 2px solid var(--tsp-bg);
}
*::-webkit-scrollbar-thumb:hover {
    background: var(--tsp-ink-faint);
}

/* ---------------------------------------------------------------------- */
/* Sidebar / control panel                                                */
/* ---------------------------------------------------------------------- */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, var(--tsp-navy) 0%, var(--tsp-navy-soft) 100%);
    border-right: 1px solid rgba(255, 255, 255, 0.06);
}

[data-testid="stSidebar"] * {
    color: rgba(255, 255, 255, 0.92);
}

[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h2 {
    font-size: 1.02rem !important;
    letter-spacing: 0.02em;
    padding-bottom: 0.6rem;
    margin-bottom: 0.6rem;
    border-bottom: 1px solid rgba(255, 255, 255, 0.12);
}

[data-testid="stSidebar"] [data-testid="stExpander"] {
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: var(--tsp-radius-md);
    margin-bottom: 0.55rem;
}

[data-testid="stSidebar"] [data-testid="stExpander"] summary {
    font-family: var(--tsp-font-display);
    font-weight: 700;
    font-size: 0.86rem;
}

[data-testid="stSidebar"] label,
[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p {
    color: rgba(255, 255, 255, 0.78) !important;
    font-size: 0.82rem !important;
    font-weight: 500 !important;
}

[data-testid="stSidebar"] input,
[data-testid="stSidebar"] [data-testid="stNumberInput"] input,
[data-testid="stSidebar"] [data-testid="stTextInput"] input {
    background: rgba(255, 255, 255, 0.94) !important;
    color: var(--tsp-ink) !important;
    border-radius: var(--tsp-radius-sm) !important;
    font-family: var(--tsp-font-mono) !important;
}

[data-testid="stSidebar"] [data-baseweb="select"] > div {
    background: rgba(255, 255, 255, 0.94) !important;
    border-radius: var(--tsp-radius-sm) !important;
    color: var(--tsp-ink) !important;
}

[data-testid="stSidebar"] hr {
    border-top: 1px solid rgba(255, 255, 255, 0.12);
    margin: 1rem 0;
}

/* ---------------------------------------------------------------------- */
/* Buttons                                                                */
/* ---------------------------------------------------------------------- */
.stButton > button, [data-testid="baseButton-secondary"] {
    border-radius: var(--tsp-radius-sm) !important;
    font-family: var(--tsp-font-display) !important;
    font-weight: 700 !important;
    font-size: 0.84rem !important;
    letter-spacing: 0.01em;
    border: 1px solid var(--tsp-border-strong) !important;
    background: var(--tsp-surface) !important;
    color: var(--tsp-navy) !important;
    padding: 0.55rem 0.9rem !important;
    transition: transform 0.12s ease, box-shadow 0.15s ease, border-color 0.15s ease;
}

.stButton > button:hover {
    border-color: var(--tsp-gold) !important;
    box-shadow: 0 0 0 3px var(--tsp-gold-wash);
    transform: translateY(-1px);
}

[data-testid="stSidebar"] .stButton > button {
    background: rgba(255, 255, 255, 0.06) !important;
    color: #fff !important;
    border: 1px solid rgba(255, 255, 255, 0.18) !important;
}

[data-testid="stSidebar"] .stButton > button:hover {
    background: rgba(255, 255, 255, 0.12) !important;
    border-color: var(--tsp-gold) !important;
}

.stButton > button[kind="primary"],
[data-testid="baseButton-primary"] {
    background: linear-gradient(135deg, var(--tsp-gold) 0%, #96702C 100%) !important;
    border: 1px solid #8C6A2E !important;
    color: #1A1305 !important;
    box-shadow: var(--tsp-shadow-sm);
}

.stButton > button[kind="primary"]:hover,
[data-testid="baseButton-primary"]:hover {
    box-shadow: 0 0 0 4px var(--tsp-gold-wash), var(--tsp-shadow-md);
    transform: translateY(-1px);
}

.stButton > button:disabled {
    opacity: 0.45 !important;
    box-shadow: none !important;
    transform: none !important;
}

/* ---------------------------------------------------------------------- */
/* Tabs                                                                    */
/* ---------------------------------------------------------------------- */
[data-testid="stTabs"] [data-baseweb="tab-list"] {
    gap: 1.6rem;
    border-bottom: 1px solid var(--tsp-border);
}

[data-testid="stTabs"] button[role="tab"] {
    font-family: var(--tsp-font-display);
    font-weight: 700;
    font-size: 0.86rem;
    letter-spacing: 0.01em;
    color: var(--tsp-ink-faint);
    padding-bottom: 0.7rem;
}

[data-testid="stTabs"] button[aria-selected="true"] {
    color: var(--tsp-navy) !important;
    border-bottom: 2.5px solid var(--tsp-gold) !important;
}

/* ---------------------------------------------------------------------- */
/* Expanders / containers / metrics / dataframes                          */
/* ---------------------------------------------------------------------- */
[data-testid="stExpander"] {
    border: 1px solid var(--tsp-border) !important;
    border-radius: var(--tsp-radius-md) !important;
    background: var(--tsp-surface);
    box-shadow: var(--tsp-shadow-xs);
}

[data-testid="stExpander"] summary {
    font-family: var(--tsp-font-display);
    font-weight: 700;
    color: var(--tsp-navy);
}

[data-testid="stVerticalBlockBorderWrapper"] {
    border-radius: var(--tsp-radius-md) !important;
}

[data-testid="stMetric"] {
    background: var(--tsp-surface);
    border: 1px solid var(--tsp-border);
    border-radius: var(--tsp-radius-md);
    padding: 0.85rem 1rem;
    box-shadow: var(--tsp-shadow-xs);
}

[data-testid="stMetricLabel"] {
    font-family: var(--tsp-font-body);
    font-size: 0.72rem !important;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--tsp-ink-faint) !important;
    font-weight: 700 !important;
}

[data-testid="stMetricValue"] {
    font-family: var(--tsp-font-mono) !important;
    font-variant-numeric: tabular-nums;
    color: var(--tsp-ink) !important;
}

[data-testid="stDataFrame"] {
    border: 1px solid var(--tsp-border);
    border-radius: var(--tsp-radius-md);
    overflow: hidden;
    box-shadow: var(--tsp-shadow-xs);
}

[data-testid="stDataFrame"] * {
    font-family: var(--tsp-font-mono) !important;
    font-variant-numeric: tabular-nums;
    font-size: 0.83rem !important;
}

/* Alerts */
[data-testid="stAlert"] {
    border-radius: var(--tsp-radius-md);
    border: 1px solid var(--tsp-border);
    font-family: var(--tsp-font-body);
}

/* Progress bar */
[data-testid="stProgress"] > div > div {
    background: linear-gradient(90deg, var(--tsp-navy), var(--tsp-gold)) !important;
}

/* ---------------------------------------------------------------------- */
/* Status ribbon (page header, signature element)                         */
/* ---------------------------------------------------------------------- */
.status-ribbon {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 0.9rem;
    background: linear-gradient(120deg, var(--tsp-navy) 0%, var(--tsp-navy-soft) 100%);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-bottom: 2.5px solid var(--tsp-gold);
    border-radius: var(--tsp-radius-lg);
    padding: 1.05rem 1.5rem;
    margin-bottom: 1.4rem;
    box-shadow: var(--tsp-shadow-md);
}

.status-ribbon-brand {
    display: flex;
    align-items: center;
    gap: 0.85rem;
}

.status-ribbon-seal {
    font-size: 1.7rem;
    line-height: 1;
    filter: drop-shadow(0 2px 4px rgba(0, 0, 0, 0.35));
}

.status-ribbon-title {
    font-family: var(--tsp-font-display);
    font-weight: 800;
    font-size: 1.05rem;
    letter-spacing: 0.02em;
    color: #FFFFFF;
    text-transform: uppercase;
}

.status-ribbon-sub {
    font-family: var(--tsp-font-body);
    font-size: 0.78rem;
    color: rgba(255, 255, 255, 0.55);
    margin-top: 0.1rem;
}

.status-ribbon-meta {
    display: flex;
    align-items: center;
    gap: 0.55rem;
    flex-wrap: wrap;
}

.status-chip {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    background: rgba(255, 255, 255, 0.07);
    border: 1px solid rgba(255, 255, 255, 0.14);
    border-radius: 999px;
    padding: 0.32rem 0.75rem;
    font-family: var(--tsp-font-body);
    font-size: 0.74rem;
    font-weight: 600;
    color: rgba(255, 255, 255, 0.92);
}

.status-chip.mono {
    font-family: var(--tsp-font-mono);
    font-variant-numeric: tabular-nums;
    color: rgba(255, 255, 255, 0.65);
}

.status-dot {
    width: 8px;
    height: 8px;
    border-radius: 999px;
    display: inline-block;
    box-shadow: 0 0 0 3px currentColor;
    opacity: 0.9;
}

/* ---------------------------------------------------------------------- */
/* KPI tiles                                                              */
/* ---------------------------------------------------------------------- */
.kpi-tile {
    position: relative;
    background: var(--tsp-surface);
    border: 1px solid var(--tsp-border);
    border-radius: var(--tsp-radius-md);
    padding: 1rem 1.1rem 0.9rem 1.3rem;
    margin-top: 4px;
    margin-bottom: 0.65rem;
    box-shadow: var(--tsp-shadow-xs);
    transition: transform 0.16s ease, box-shadow 0.16s ease, border-color 0.16s ease;
    overflow: hidden;
}

.kpi-tile::before {
    content: "";
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    width: 4px;
    background: var(--tile-accent, var(--tsp-navy));
}

.kpi-tile:hover {
    transform: translateY(-2px);
    box-shadow: var(--tsp-shadow-sm);
    border-color: var(--tsp-border-strong);
}

.kpi-eyebrow {
    font-family: var(--tsp-font-body);
    font-size: 0.68rem;
    font-weight: 700;
    letter-spacing: 0.07em;
    text-transform: uppercase;
    color: var(--tsp-ink-faint);
    margin-bottom: 0.35rem;
    display: flex;
    align-items: center;
    gap: 0.35rem;
}

.kpi-value {
    font-family: var(--tsp-font-mono);
    font-variant-numeric: tabular-nums;
    font-size: 1.28rem;
    font-weight: 700;
    color: var(--tsp-ink);
    line-height: 1.2;
    letter-spacing: -0.01em;
    word-break: break-word;
}

.kpi-note {
    font-family: var(--tsp-font-body);
    font-size: 0.78rem;
    color: var(--tsp-ink-soft);
    margin-top: 0.25rem;
    line-height: 1.4;
}

/* Legacy aliases so any older markup keeps working */
.small-kpi { background: var(--tsp-surface); border-radius: var(--tsp-radius-md); padding: 1rem; box-shadow: var(--tsp-shadow-xs); }
.small-kpi-title { font-size: 0.75rem; color: var(--tsp-ink-faint); text-transform: uppercase; letter-spacing: 0.06em; font-weight: 700; }
.small-kpi-value { font-family: var(--tsp-font-mono); font-size: 1.2rem; font-weight: 800; }
.small-kpi-note { font-size: 0.8rem; color: var(--tsp-ink-soft); margin-top: 0.15rem; }

/* ---------------------------------------------------------------------- */
/* Pills / badges                                                         */
/* ---------------------------------------------------------------------- */
.pill {
    display: inline-flex;
    align-items: center;
    gap: 0.32rem;
    padding: 0.22rem 0.62rem;
    border-radius: 999px;
    font-family: var(--tsp-font-body);
    font-size: 0.66rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    border: 1px solid transparent;
    white-space: nowrap;
}

.pill-live {
    background: rgba(16, 185, 129, 0.12);
    color: #0D7A5F;
    border-color: rgba(16, 185, 129, 0.28);
}

.pill-default {
    background: rgba(148, 163, 184, 0.16);
    color: #475569;
    border-color: rgba(148, 163, 184, 0.30);
}

.pill-failed {
    background: rgba(239, 68, 68, 0.12);
    color: #B91C1C;
    border-color: rgba(239, 68, 68, 0.28);
}

/* ---------------------------------------------------------------------- */
/* Regime directory cards                                                 */
/* ---------------------------------------------------------------------- */
.regime-card {
    position: relative;
    background: var(--tsp-surface);
    border: 1px solid var(--tsp-border);
    border-radius: var(--tsp-radius-lg);
    padding: 1.15rem 1.15rem 1rem;
    min-height: 250px;
    box-shadow: var(--tsp-shadow-xs);
    transition: transform 0.16s ease, box-shadow 0.16s ease;
}

.regime-card:hover {
    transform: translateY(-2px);
    box-shadow: var(--tsp-shadow-sm);
}

.regime-card.is-active {
    border: 1.5px solid var(--regime-color, var(--tsp-navy));
    background:
        linear-gradient(180deg, var(--regime-bg, transparent) 0%, var(--tsp-surface) 65%);
    box-shadow: var(--tsp-shadow-md);
}

.regime-card-badge {
    position: absolute;
    top: 0.75rem;
    right: 0.75rem;
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    font-family: var(--tsp-font-body);
    font-size: 0.6rem;
    font-weight: 800;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: #fff;
    background: var(--regime-color, var(--tsp-navy));
    padding: 0.22rem 0.5rem;
    border-radius: 999px;
}

.regime-card-icon {
    font-size: 1.5rem;
    line-height: 1;
    margin-bottom: 0.45rem;
}

.regime-card-name {
    font-family: var(--tsp-font-display);
    font-weight: 800;
    font-size: 0.92rem;
    color: var(--regime-color, var(--tsp-ink));
    letter-spacing: 0.01em;
}

.regime-card-meta {
    font-family: var(--tsp-font-body);
    font-size: 0.74rem;
    font-weight: 600;
    color: var(--tsp-ink-faint);
    margin: 0.3rem 0 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.03em;
}

.regime-card-alloc {
    font-family: var(--tsp-font-mono);
    font-variant-numeric: tabular-nums;
    font-size: 0.78rem;
    font-weight: 700;
    color: var(--regime-color, var(--tsp-ink));
    background: var(--tsp-navy-wash);
    border-radius: var(--tsp-radius-sm);
    padding: 0.4rem 0.55rem;
    margin-bottom: 0.65rem;
}

.regime-card-desc {
    font-family: var(--tsp-font-body);
    font-size: 0.79rem;
    color: var(--tsp-ink-soft);
    line-height: 1.4;
}

/* ---------------------------------------------------------------------- */
/* Editable metric tiles                                                  */
/* ---------------------------------------------------------------------- */
.editable-tile {
    border-left: 4px solid var(--tile-accent, var(--tsp-navy));
    border-radius: var(--tsp-radius-md);
    padding: 0.85rem 0.95rem 0.5rem;
    background: var(--tsp-surface);
}

.editable-tile-title {
    font-family: var(--tsp-font-body);
    font-size: 0.7rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--tsp-ink-faint);
}

.editable-tile-value {
    font-family: var(--tsp-font-mono);
    font-variant-numeric: tabular-nums;
    font-size: 1.05rem;
    font-weight: 700;
    color: var(--tsp-ink);
    margin-top: 0.2rem;
}

.editable-tile-foot {
    margin-top: 0.5rem;
}
</style>
"""


def inject_styles() -> None:
    """Inject the app-wide CSS into Streamlit.

    This should be called once near the top of app.py.
    """
    st.markdown(APP_STYLES, unsafe_allow_html=True)


__all__: list[str] = [
    "APP_STYLES",
    "inject_styles",
]
