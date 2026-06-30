# Tactical TSP Engine Scoring Guide

This document explains the scoring logic used by the engine in plain English.

## Overview

The engine now evaluates two layers of signals:

1. Core factor scores
2. Macro overlay scores

The core factor scores are the main inputs to the composite score. The macro overlay scores add additional regime context and act as guards against overly aggressive positioning during hostile macro conditions.

The app shows these factors in the “Factor Score Detail” and “Factor Interpretation” sections, and the engine uses them to select the final regime and allocation  

---

# Core Factor Scores

## 1) Inflation

The inflation score is based on Core PCE YoY and is adjusted by breakeven inflation.

### Rules
- Core PCE < 1.8% → `+3`
- 1.8% to < 2.0% → `+1`
- 2.0% to 2.3% → `0`
- > 2.3% to 3.0% → `-3`
- > 3.0% → `-5`

### Adjustments
- If breakeven inflation > 2.6%, inflation is made worse
- If breakeven inflation < 1.8%, inflation is not allowed to stay too negative

This logic is implemented directly in `score_market_data()` in `engine.py` 

---

## 2) Growth

The growth score uses a weighted PMI blend and initial claims.

### Rules
The engine uses:

- `0.20 * ISM Manufacturing PMI`
- `0.80 * ISM Services PMI`

Then it scores the result:

- > 55.0 → `+3`
- 51.5 to 55.0 → `+1`
- 50.0 to < 51.5 → `0`
- 48.0 to < 50.0 → `-3`
- < 48.0 → `-5`

### Claims adjustment
- If initial claims > 250K → subtract 1
- If initial claims > 280K → stronger negative penalty

These rules are part of the growth scoring block in `engine.py` 

---

## 3) Liquidity

Liquidity is based on SLOOS and Fed assets growth.

### Rules
- SLOOS < -15.0 → `+3`
- SLOOS between -15.0 and 5.0 → `0`
- SLOOS > 5.0 → `-5`

### Fed assets adjustment
- Fed assets growth > 0.0 → add `+2`
- Fed assets growth <= 0.0 → subtract `2`

This is the engine’s existing liquidity logic and remains part of the core score set 

---

## 4) Credit Spreads

Credit spreads are scored using HY OAS.

### Rules
- HY OAS < 3.0 → `+3`
- 3.0 to < 4.0 → `+1`
- 4.0 to 5.0 → `0`
- > 5.0 to 6.0 → `-3`
- > 6.0 → `-5`

These thresholds are implemented directly in `engine.py` 

---

## 5) Valuation

Valuation uses Shiller CAPE, with an adjustment based on forward EPS growth and real yields.

### Base CAPE ceiling
- If `fwd_eps >= 15.0` → base ceiling = `35.0`
- Otherwise → base ceiling = `30.0`

### Real yield adjustment
- If 10Y real yield > 2.2% → subtract 5 from the ceiling
- If 10Y real yield < 0.5% → add 3 to the ceiling
- Otherwise → no change

### Final valuation score
- CAPE < 20.0 → `+3`
- 20.0 to 25.0 → `0`
- Above 25.0 but below the active ceiling → `-3`
- Above the active ceiling → `-5`

This logic is implemented in `engine.py` and is one of the more important parts of the model 

---

## 6) Market Stress

Market stress is based on VIX, then adjusted by STLFSI.

### VIX rules
- VIX < 12.0 → `+3`
- 12.0 to < 15.0 → `+1`
- 15.0 to 22.0 → `0`
- 22.0 to 30.0 → `-3`
- > 30.0 → `-5`

### STLFSI adjustments
- STLFSI between 0.0 and 1.0 → subtract 1 from market stress and momentum
- STLFSI between 1.0 and 2.0 → subtract 3 from market stress and momentum
- STLFSI > 2.0 → force market stress = `-10`, momentum = `-10`, and valuation cannot be better than `-5`

These rules are part of the engine’s stress logic 

---

## 7) Momentum

Momentum is based on SPX distance from its 200-day moving average.

### Rules
- Above +5.0% → `+3`
- 0.0% to +5.0% → `+1`
- -5.0% to < 0.0% → `-3`
- Below -5.0% → `-5`

This is the `pct_dist_200_sma` logic in the engine 

---

## 8) Drawdown

Drawdown is based on the decline from the peak close in the loaded SPX series.

### Rules
- Under 5.0% → `+3`
- 5.0% to < 10.0% → `+1`
- 10.0% to 15.0% → `0`
- 15.0% to 20.0% → `-3`
- Above 20.0% → `-5`

This is the `drawdown_pct` logic in the engine 

---

# Macro Overlay Scores

These are additional macro context signals added on top of the core factors.

They are used to improve regime discipline and prevent aggressive allocations during hostile macro conditions.

---

## 9) Yield Curve

The yield curve uses the 10Y minus 3M Treasury spread.

### Rules
- Spread > 1.0% → `+2`
- 0.5% to 1.0% → `+1`
- 0.0% to 0.5% → `0`
- -0.5% to 0.0% → `-2`
- Below -0.5% → `-4`

### Interpretation
- Positive and steep curve = healthier macro backdrop
- Flat or inverted curve = slowdown / recession warning

This signal is derived from the live or fallback 10Y and 3M Treasury series in `data_sources.py`, then scored in `engine.py`.

---

## 10) Inflation Shock

This is a surprise-style inflation feature, not just the inflation level.

### Rules
- Shock <= -0.2 → `+2`
- -0.2 to 0.0 → `0`
- 0.0 to 0.2 → `-1`
- 0.2 to 0.3 → `-3`
- Above 0.3 → `-4`

### Interpretation
- Negative shock = inflation is cooling faster than expected
- Positive shock = inflation is re-accelerating or surprising to the upside

This helps the engine react to bad inflation prints even if the level is not yet extreme.

---

## 11) Central Bank Stance

This is a normalized policy posture score derived from liquidity, real yields, and curve shape.

### Rules
- `+2` or higher → `+2`
- `+1` → `+1`
- `0` → `0`
- `-1` → `-1`
- `-2` → `-3`
- `-3` or lower → `-4`

### Interpretation
- Positive values mean the policy backdrop is supportive
- Negative values mean policy is restrictive or tightening

This helps distinguish a supportive market from one that is only stable on the surface.

---

## 12) Liquidity Pressure

This is a derived “tightness” measure. Higher values mean conditions are more restrictive.

### Scoring
- Pressure <= 0.5 → `+1`
- 0.5 to 1.5 → `0`
- 1.5 to 2.5 → `-1`
- 2.5 to 3.5 → `-3`
- Above 3.5 → `-5`

### Interpretation
This signal rises when multiple liquidity conditions are tight, such as:
- SLOOS is elevated
- Fed assets are shrinking
- STLFSI is elevated
- real yields are high
- MOVE is elevated

---

# How the regime is chosen

The composite score is the sum of the core factor scores plus the macro overlay scores.

The engine then applies guardrails and regime rules.

## Risk-On Override
The engine only allows Risk-On when all of the following are true:
- Composite score is strong
- Core PCE is under 2.0
- CAPE is below 26.0
- Momentum breaker is not active
- Yield curve is not inverted
- Inflation shock is not positive enough to matter
- Policy is not restrictive
- Liquidity is not tight

## Optimized Neutral
This is the default balanced state when signals are constructive but mixed.

It is only allowed when the composite is non-negative and the macro backdrop is not deeply hostile.

## Defensive Allocation
This is the safe fallback when:
- the composite turns negative
- the curve is inverted
- inflation shock is adverse
- policy is restrictive
- liquidity is tight

It is also used when the engine sees a clear macro-hostile combination even if the composite is not deeply negative.

## Emergency Dispatch
Triggered by panic conditions or override logic.

The existing panic valve logic remains intact and can force maximum defense when short-term market stress is severe.

These regime rules are defined in `determine_allocation()` in `engine.py` and reflected in the app’s regime cards and decision breakdown  

---

# Plain-English summary

### Core factors
- Inflation: is price pressure favorable or hostile?
- Growth: is the economy expanding or weakening?
- Liquidity: are financial conditions easy or tight?
- Credit spreads: is credit calm or stressed?
- Valuation: is the market cheap or expensive?
- Market stress: is volatility calm or panicky?
- Momentum: is trend healthy or broken?
- Drawdown: how much damage has already happened?

### Macro overlays
- Yield curve: is the economy still signaling expansion or recession risk?
- Inflation shock: did inflation surprise the market?
- Central bank stance: is policy supportive or restrictive?
- Liquidity pressure: are conditions tightening across multiple channels?

---

# Important note

The app’s factor tables and decision breakdown currently show the original 8 factor categories, so if you want the UI to display the new macro overlay scores explicitly, the app should be updated to include those rows too  

If you want, I can do the next step and generate the updated `app.py` changes so the UI shows:
- yield curve
- inflation shock
- central bank stance
- liquidity pressure

in the factor score table, interpretation panel, and market snapshot.
