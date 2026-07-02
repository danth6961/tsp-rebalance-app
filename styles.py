"""
Author: Donald J Anthony
Date: Today's Date

styles.py — CSS and visual tokens for the Streamlit app.

Owns:
    - Layout spacing
    - Card styling
    - Pill styling
    - KPI / metric tile styling
    - Badge colors
    - Chart container styling
    - Reusable visual tokens

Does not own:
    - App logic
    - Rendering logic
    - Data logic
    - Regime logic
"""

from __future__ import annotations

import streamlit as st

# -----------------------------------------------------------------------------
# Central style payload
# -----------------------------------------------------------------------------
# Keep all visual rules here so app.py can remain a thin orchestration layer.
# The UI layer should refer to these class names rather than inlining CSS.
# -----------------------------------------------------------------------------
APP_STYLES: str = """
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

.pill-live {
    background: #dcfce7;
    color: #15803d;
    border-color: #bbf7d0;
}

.pill-default {
    background: #f3f4f6;
    color: #4b5563;
    border-color: #e5e7eb;
}

.pill-failed {
    background: #fee2e2;
    color: #991b1b;
    border-color: #fca5a5;
}

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
"""


def inject_styles() -> None:
    """
    Inject the application-wide CSS into the Streamlit app.

    This function should be called once near the top of app.py so that all
    subsequent components render with the provided visual tokens and layout styles.
    """
    st.markdown(APP_STYLES, unsafe_allow_html=True)


__all__: list[str] = [
    "APP_STYLES",
    "inject_styles",
]
