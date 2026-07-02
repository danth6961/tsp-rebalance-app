"""
Author: Donald J Anthony
Date: Today's Date

scoring.py — Factor scoring and composite score calculation.

Public API:
    • score_all_factors(data: dict) -> dict[str, float]
    • composite_score(scores: dict[str, float]) -> float
    • score_valuation_continuous(cape, fwd_eps_growth_yoy, real_yield_10y)

Notes
-----
- score_valuation_continuous implements a continuous, vectorized valuation score
  using dynamic ceilings and piecewise linear interpolation per the project spec.
- The function accepts a single float or array-like (numpy array or pandas Series)
  and returns a float, numpy array, or pandas Series respectively.
"""

from __future__ import annotations

from typing import Any, Dict

import numpy as np

try:
    import pandas as pd
except Exception:  # pandas is optional for runtime
    pd = None  # type: ignore

from constants import (
    DEFAULTS,
    FACTOR_WEIGHTS,
    VALUATION_BREAKPOINTS,
    BASE_CAPE_CEILING,
    HIGH_EPS_CAPE_CEILING,
    REAL_YIELD_THRESHOLD,
)

# ----------------------------------------------------------------------
# Valuation: Continuous, vectorized scoring function
# ----------------------------------------------------------------------
def score_valuation_continuous(
    cape: Any,
    fwd_eps_growth_yoy: Any,
    real_yield_10y: Any,
) -> Any:
    """
    Compute a continuous valuation score based on CAPE, with a dynamic ceiling.

    Boundary rules (inclusive):
    - If cape <= 20.0: Score = 1.0.
    - If 20.0 < cape <= 25.0: Linearly interpolate from 1.0 down to 0.0.
      Formula: 1.0 - ((cape - 20.0) / (25.0 - 20.0)) * 1.0
    - If 25.0 < cape <= chosen_ceiling: Linearly interpolate from 0.0 down to -1.0.
      Formula: 0.0 - ((cape - 25.0) / (chosen_ceiling - 25.0)) * 1.0
    - If chosen_ceiling < cape <= (chosen_ceiling + 5.0): Linearly interpolate from -1.0 down to -3.0.
      Formula: -1.0 - ((cape - chosen_ceiling) / 5.0) * 2.0
    - If cape > (chosen_ceiling + 5.0): Score = -3.0 (hard floor for extreme overvaluation)

    Dynamic ceiling:
    - chosen_ceiling = 35.0 when fwd_eps_growth_yoy >= 5.0 AND real_yield_10y <= 2.2
    - otherwise chosen_ceiling = 30.0

    Vectorization:
    - Operates on float, numpy arrays, or pandas Series using numpy broadcasting.
    - Returns the same type as the cape input (float, numpy array, or pandas Series).

    Missing/NaN handling:
    - If any of cape, fwd_eps_growth_yoy, or real_yield_10y are NaN for an element,
      the corresponding score is set to 0.0 (neutral).
    """
    # Resolve breakpoints once
    bp_low, bp_mid = float(VALUATION_BREAKPOINTS[0]), float(VALUATION_BREAKPOINTS[1])
    base_ceiling = float(BASE_CAPE_CEILING)
    high_ceiling = float(HIGH_EPS_CAPE_CEILING)
    ry_thresh = float(REAL_YIELD_THRESHOLD)

    # Capture original input type to shape the return type.
    is_pd_series = pd is not None and isinstance(cape, pd.Series)
    cape_index = cape.index if is_pd_series else None

    # Convert to arrays for vectorized math.
    c_arr = np.asarray(cape, dtype=float)
    f_arr = np.asarray(fwd_eps_growth_yoy, dtype=float)
    r_arr = np.asarray(real_yield_10y, dtype=float)

    # Broadcast to compatible shapes if any are scalars.
    c_arr, f_arr, r_arr = np.broadcast_arrays(c_arr, f_arr, r_arr)

    # Choose dynamic ceiling per element based on EPS growth and real yields.
    ceiling = np.where(
        (f_arr >= 5.0) & (r_arr <= ry_thresh),
        high_ceiling,
        base_ceiling,
    )

    # Precompute segment values with linear interpolation where applicable.
    # Segment 1: c <= 20 -> 1.0
    seg1_val = np.full_like(c_arr, 1.0, dtype=float)

    # Segment 2: 20 < c <= 25 -> interpolate 1.0 -> 0.0
    seg2_val = 1.0 - ((c_arr - bp_low) / (bp_mid - bp_low)) * 1.0

    # Segment 3: 25 < c <= ceiling -> interpolate 0.0 -> -1.0
    denom = np.maximum(ceiling - bp_mid, 1e-9)  # numeric safety
    seg3_val = 0.0 - ((c_arr - bp_mid) / denom) * 1.0

    # Segment 4: ceiling < c <= ceiling + 5 -> interpolate -1.0 -> -3.0
    seg4_val = -1.0 - ((c_arr - ceiling) / 5.0) * 2.0

    # Conditions for the piecewise selection (inclusive boundaries per spec).
    cond1 = (c_arr <= bp_low)
    cond2 = (c_arr > bp_low) & (c_arr <= bp_mid)
    cond3 = (c_arr > bp_mid) & (c_arr <= ceiling)
    cond4 = (c_arr > ceiling) & (c_arr <= (ceiling + 5.0))

    score_arr = np.select(
        [cond1, cond2, cond3, cond4],
        [seg1_val, seg2_val, seg3_val, seg4_val],
        default=-3.0,
    )

    # Neutralize any positions with NaNs in required inputs.
    invalid_mask = np.isnan(c_arr) | np.isnan(f_arr) | np.isnan(r_arr)
    if invalid_mask.any():
        score_arr = np.where(invalid_mask, 0.0, score_arr)

    # Return with the same type as the input.
    if is_pd_series:
        return pd.Series(score_arr, index=cape_index, name="valuation_score")  # type: ignore
    # If the input was a scalar, squeeze to float.
    if score_arr.ndim == 0:
        return float(score_arr)  # type: ignore
    return score_arr


# ----------------------------------------------------------------------
# Factor aggregation utilities
# ----------------------------------------------------------------------
def _to_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return float(default)
        return float(x)
    except (TypeError, ValueError):
        return float(default)


def score_all_factors(data: Dict[str, Any]) -> Dict[str, float]:
    """
    Compute factor scores for the engine and UI.

    Notes
    -----
    - Most factors below are still pass-through to preserve current behavior
      until their full models are specified. The 'valuation' factor, however,
      is now computed from raw inputs using score_valuation_continuous.
    - Naming is aligned to UI expectations where applicable (credit_spreads, market_stress).

    Parameters
    ----------
    data : Dict[str, Any]
        Raw market snapshot.

    Returns
    -------
    Dict[str, float]
        Factor scores keyed by factor name.
    """
    # Pull valuation inputs with safe defaults.
    cape = _to_float(data.get("shiller_cape"), DEFAULTS.get("shiller_cape", 25.0))
    fwd_eps = _to_float(
        data.get("fwd_eps_growth_yoy"), DEFAULTS.get("fwd_eps_growth_yoy", 0.0)
    )
    real_yield = _to_float(
        data.get("real_yield_10y"), DEFAULTS.get("real_yield_10y", 0.0)
    )

    valuation = score_valuation_continuous(cape, fwd_eps, real_yield)
    # Ensure scalar output for the typical (float) case.
    if isinstance(valuation, np.ndarray):
        valuation = float(np.asarray(valuation).item())

    # Pass-through (or zero) for other factors unless supplied by caller.
    scores: Dict[str, float] = {
        # Core factors used by the composite score
        "growth": _to_float(data.get("growth"), 0.0),
        "liquidity": _to_float(data.get("liquidity"), 0.0),
        "credit_spreads": _to_float(data.get("credit_spreads", data.get("credit")), 0.0),
        "market_stress": _to_float(data.get("market_stress", data.get("stress")), 0.0),
        "inflation": _to_float(data.get("inflation"), 0.0),
        "momentum": _to_float(data.get("momentum"), 0.0),
        "valuation": float(valuation),
        "drawdown": _to_float(data.get("drawdown", data.get("drawdown_pct")), 0.0),
    }

    # Optional overlay-style metrics for UI display (ignored by composite_score)
    for extra_key in ("yield_curve", "inflation_shock", "central_bank", "liquidity_pressure"):
        val = data.get(extra_key)
        if val is not None:
            try:
                scores[extra_key] = float(val)
            except (TypeError, ValueError):
                scores[extra_key] = 0.0

    return scores


def composite_score(scores: Dict[str, float]) -> float:
    """
    Compute the weighted composite score using centralized weights (constants.FACTOR_WEIGHTS).

    Any factors not present in `scores` default to 0.0. Extra keys in `scores`
    (e.g., overlay diagnostics) are ignored by design.

    Parameters
    ----------
    scores : Dict[str, float]
        Factor scores returned by score_all_factors.

    Returns
    -------
    float
        Weighted sum of factors.
    """
    total = 0.0
    for factor, w in FACTOR_WEIGHTS.items():
        total += float(scores.get(factor, 0.0)) * float(w)
    return total
