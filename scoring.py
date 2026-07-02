"""
scoring.py — Factor scoring and composite score calculation.

Author: Donald J Anthony
Date: Today's Date

This module provides two public functions:
    • score_all_factors(data: dict) -> dict
    • composite_score(scores: dict) -> float

The scoring logic normalizes each factor’s score (assumed to be on a standard scale) and calculates
a weighted composite score where:
    - Growth weighs 2.0
    - Liquidity weighs 2.0
    - Credit weighs 2.0
    - Stress weighs 2.0
    - Inflation weighs 1.5
    - Momentum weighs 1.5
    - Valuation weighs 1.0
    - Drawdown weighs 1.0

This file is a drop-in module that satisfies the engine.py dependency.
"""

def score_all_factors(data: dict) -> dict:
    """
    Compute normalized scores for each factor.

    Parameters:
        data (dict): Dictionary containing raw indicator values keyed by factor names.
                     Expected keys include 'growth', 'liquidity', 'credit', 'stress',
                     'inflation', 'momentum', 'valuation', and 'drawdown'.

    Returns:
        dict: A dictionary of normalized factor scores.
    """
    # In a production system each factor would be normalized using its own domain knowledge.
    # For this implementation, we assume raw values are already appropriately normalized.
    scores = {
        'growth': float(data.get('growth', 0.0)),
        'liquidity': float(data.get('liquidity', 0.0)),
        'credit': float(data.get('credit', 0.0)),
        'stress': float(data.get('stress', 0.0)),
        'inflation': float(data.get('inflation', 0.0)),
        'momentum': float(data.get('momentum', 0.0)),
        'valuation': float(data.get('valuation', 0.0)),
        'drawdown': float(data.get('drawdown', 0.0))
    }
    return scores

def composite_score(scores: dict) -> float:
    """
    Compute the weighted composite score from individual factor scores.

    The weights applied are:
        - Growth: 2.0
        - Liquidity: 2.0
        - Credit: 2.0
        - Stress: 2.0
        - Inflation: 1.5
        - Momentum: 1.5
        - Valuation: 1.0
        - Drawdown: 1.0

    Parameters:
        scores (dict): Dictionary of factor scores as returned by score_all_factors.

    Returns:
        float: The composite score.
    """
    weights = {
        'growth': 2.0,
        'liquidity': 2.0,
        'credit': 2.0,
        'stress': 2.0,
        'inflation': 1.5,
        'momentum': 1.5,
        'valuation': 1.0,
        'drawdown': 1.0,
    }
    total = 0.0
    for factor, weight in weights.items():
        total += scores.get(factor, 0.0) * weight
    return total
