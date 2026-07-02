"""
allocation_age55.py — Age-55 TSP allocation engine with smooth interpolation.

Implements a globally diversified, age-55 target mapping from a scalar 'score'
to target allocations for C, S, I, and G using vectorized numpy interpolation
and strict 100% capital checks.

Score anchors (age-55 targets):
- Score >= +0.5:  C=48%, S=12%, I=20%, G=20%  (Max Growth)
- Score ==  0.0:  C=30%, S= 80%, I=12%, G=50%  (Moderate Balanced)
- Score == -1.0:  C=12%, S= 3%, I= 5%, G=80%  (Defensive Conservative)
- Score <= -1.5:  C= 0%, S= 0%, I= 0%, G=100% (Capital Escape)

Design notes:
- Vectorized with numpy.interp for speed and for use across scalars, Series, or arrays.
- Scores are clamped to [-4.0, +1.0] before interpolation per spec.
- After interpolation, we apply a strict sum-to-one adjustment by adding the
  small residual (1 - sum) to G, preserving the G 'capital preservation' sleeve.
- The 4:1 ratio between C and S is enforced at anchor points and preserved
  along the interpolation segments (48:12, 30:8, 12:3), representing the
  domestic market-weighted intent. I adds global diversification; G scales
  aggressively to protect capital from sequential risk.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Tuple, Union

import numpy as np

try:
    import pandas as pd
except Exception:  # pandas is optional
    pd = None  # type: ignore


Scalar = Union[float, int]
ArrayLike = Union[Scalar, Iterable[float], "np.ndarray", "pd.Series"]


def _as_ndarray(x: ArrayLike) -> np.ndarray:
    if pd is not None and isinstance(x, pd.Series):
        return x.to_numpy(dtype=float)
    return np.asarray(x, dtype=float)


def _is_scalar(x: Any) -> bool:
    if pd is not None and isinstance(x, pd.Series):
        return False
    arr = np.asarray(x)
    return arr.ndim == 0


def age55_target_allocations(score: ArrayLike, return_as: str | None = None) -> Union[Dict[str, float], "pd.DataFrame"]:
    """
    Compute age-55 target allocations from a risk 'score' using vectorized interpolation.

    Inputs:
    - score: float, numpy array, or pandas Series. Values are clamped to [-4.0, +1.0].

    Returns:
    - If score is scalar (and return_as is None): a dict with keys:
        {'C_Fund_Pct', 'S_Fund_Pct', 'I_Fund_Pct', 'G_Fund_Pct}, values in 0..1
    - If score is array-like or return_as == 'dataframe': a pandas DataFrame with those columns.

    Notes:
    - Uses numpy.interp for C, S, I, and G between four anchor scores.
    - Enforces sum(C+S+I+G) == 1.0 by applying a residual correction to G only.
    """
    # Clamp scores to [-4, +1] before interpolation.
    s = _as_ndarray(score)
    s_clipped = np.clip(s, -4.0, 1.0)

    # Interpolation anchors (x: score, y: allocation in fractions).
    xp = np.array([-1.5, -1.0, 0.0, 0.5], dtype=float)

    y_c = np.array([0.00, 0.12, 0.30, 0.48], dtype=float)
    y_s = np.array([0.00, 0.03, 0.08, 0.12], dtype=float)
    y_i = np.array([0.00, 0.05, 0.12, 0.20], dtype=float)
    y_g = np.array([1.00, 0.80, 0.50, 0.20], dtype=float)

    # Vectorized interpolation for each sleeve.
    c = np.interp(s_clipped, xp, y_c)
    sn = np.interp(s_clipped, xp, y_s)  # 'sn' to avoid shadowing builtins
    i = np.interp(s_clipped, xp, y_i)
    g_interp = np.interp(s_clipped, xp, y_g)

    # Strict sum-to-one enforcement: add the residual to G (capital preservation sleeve).
    total = c + sn + i + g_interp
    residual = 1.0 - total
    g = g_interp + residual

    # Clip outputs to [0, 1] range for numerical safety.
    c = np.clip(c, 0.0, 1.0)
    sn = np.clip(sn, 0.0, 1.0)
    i = np.clip(i, 0.0, 1.0)
    g = np.clip(g, 0.0, 1.0)

    # Prepare return type: scalar dict or DataFrame.
    if (return_as == "dataframe") or (not _is_scalar(score)):
        if pd is None:
            raise RuntimeError("pandas is required to return a DataFrame (install pandas).")
        return pd.DataFrame(
            {
                "C_Fund_Pct": c,
                "S_Fund_Pct": sn,
                "I_Fund_Pct": i,
                "G_Fund_Pct": g,
            }
        )

    # Scalar -> return a dict
    return {
        "C_Fund_Pct": float(c),
        "S_Fund_Pct": float(sn),
        "I_Fund_Pct": float(i),
        "G_Fund_Pct": float(g),
    }


def to_percent_0_100(x: Dict[str, float]) -> Dict[str, float]:
    """
    Convert a fraction-based dict (0..1) to TSP-style percentage points (0..100).
    """
    return {k: float(v) * 100.0 for k, v in x.items()}


def should_execute_trade_by_hurdle(
    current_alloc: Dict[str, float],
    target_alloc: Dict[str, float],
    allocation_hurdle: float = 0.05,
) -> Tuple[bool, float]:
    """
    Determine if a trade should be executed given an allocation_hurdle.

    Inputs:
    - current_alloc: mapping of fund -> percent (either 0..1 or 0..100)
    - target_alloc:  mapping of fund -> percent (either 0..1 or 0..100)
    - allocation_hurdle: minimum cumulative change required (0.05 = 5%)

    Returns:
    - (should_trade, cumulative_change) where cumulative_change is measured in the same
      units as allocation_hurdle (fractions).

    Method:
    - Computes half the L1 distance between current and target over the four funds C,S,I,G.
      This corresponds to the minimum turnover if moving directly from current to target.
    - If inputs appear to be 0..100 scale (sum ~100), they are normalized to 0..1 first.
    """
    keys = ("C_Fund_Pct", "S_Fund_Pct", "I_Fund_Pct", "G_Fund_Pct")

    def _grab(d: Dict[str, float]) -> np.ndarray:
        vals = np.array([float(d.get(k, 0.0)) for k in keys], dtype=float)
        total = vals.sum()
        if total > 2.0:  # assume percent 0..100 scale, normalize
            vals = vals / 100.0
        return vals

    cur = _grab(current_alloc)
    tgt = _grab(target_alloc)
    cum_change = float(np.abs(cur - tgt).sum() / 2.0)
    return (cum_change >= float(allocation_hurdle), cum_change)
