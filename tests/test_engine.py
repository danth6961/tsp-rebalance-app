from engine import score_market_data, build_engine_result

def test_risk_on_regime_possible():
    data = {
        "core_pce_yoy": 1.7,
        "ism_pmi": 56.0,
        "services_pmi": 57.0,
        "initial_claims": 200,
        "breakeven_inflation": 2.0,
        "fed_assets_growth_yoy": 2.0,
        "real_yield_10y": 1.0,
        "move_index": 100.0,
        "sloos_net_pct": -20.0,
        "hy_oas": 2.5,
        "shiller_cape": 22.0,
        "fwd_eps_growth_yoy": 18.0,
        "vix_spot": 12.0,
        "pct_dist_200_sma": 6.0,
        "drawdown_pct": 2.0,
        "stlfsi_index": -1.0,
        "bond_yield_10y": 4.5,
        "dxy_spot": 100.0,
        "market_breadth_pct": 70.0,
        "spx_spot": 5000.0,
    }
    scores = score_market_data(data)
    assert isinstance(scores, dict)
    assert "inflation" in scores
    result = build_engine_result(data)
    assert "regime" in result
