# Tactical TSP Engine Scoring Guide

This document explains the current scoring logic used by the engine in plain English.

## Overview

The engine evaluates 8 factors:

1. Inflation
2. Growth
3. Liquidity
4. Credit Spreads
5. Valuation
6. Market Stress
7. Momentum
8. Drawdown

These factor scores are added together into a composite score, which helps determine the final regime and allocation. The app also shows these factors in the “Factor Score Detail” table and “Factor Interpretation” section .

---

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

The engine applies these inflation thresholds directly in `score_market_data()` .

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

These rules are visible in the engine scoring block .

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

This is part of the same scoring function in `engine.py` .

---

## 4) Credit Spreads

Credit spreads are scored using HY OAS.

### Rules
- HY OAS < 3.0 → `+3`
- 3.0 to < 4.0 → `+1`
- 4.0 to 5.0 → `0`
- > 5.0 to 6.0 → `-3`
- > 6.0 → `-5`

These thresholds are implemented directly in the engine .

---

## 5) Valuation

Valuation uses Shiller CAPE, with an adjustment based on forward EPS growth and real yields.

### Base CAPE ceiling
- If `fwd_eps >= 15.0` → base ceiling = `35.0`
- Otherwise → base ceiling = `30.0`

### Real yield adjustment
- If 10Y real yield > 2.2% → subtract 5 from the ceiling
- If 10Y real yield < 0.5% → add 3 to the ceiling

### Final valuation score
- CAPE < 20.0 → `+3`
- 20.0 to 25.0 → `0`
- Above 25.0 but below the active ceiling → `-3`
- Above the active ceiling → `-5`

This logic is implemented in `engine.py` and is one of the more important parts of the model .

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

These rules are part of the engine’s stress logic .

---

## 7) Momentum

Momentum is based on SPX distance from its 200-day moving average.

### Rules
- Above +5.0% → `+3`
- 0.0% to +5.0% → `+1`
- -5.0% to < 0.0% → `-3`
- Below -5.0% → `-5`

This is the `pct_dist_200_sma` logic in the engine .

---

## 8) Drawdown

Drawdown is based on the decline from the peak close in the loaded SPX series.

### Rules
- Under 5.0% → `+3`
- 5.0% to < 10.0% → `+1`
- 10.0% to 15.0% → `0`
- 15.0% to 20.0% → `-3`
- Above 20.0% → `-5`

This is the `drawdown_pct` logic in the engine .

---

## How the regime is chosen

The composite score is the sum of the 8 factor scores.

The engine then applies these rules:

### Risk-On Override
- Composite score >= +5
- Core PCE < 2.0
- CAPE < 26.0
- Momentum breaker not active

### Optimized Neutral
- Composite score >= 0

### Defensive Allocation
- Composite score < 0

### Emergency Dispatch
Triggered by panic conditions or override logic.

These regime rules are defined in `determine_allocation()` in `engine.py` .

---

## Plain-English summary

- Inflation tells you whether price pressure is good or bad
- Growth tells you whether the economy is expanding or weakening
- Liquidity tells you whether conditions are easy or tight
- Credit spreads tell you whether credit markets are calm or stressed
- Valuation tells you whether the market is cheap or expensive
- Market stress tells you whether volatility is calm or panicky
- Momentum tells you whether trend is healthy or broken
- Drawdown tells you how much damage has already occurred

---

## Notes

The app displays these factors in the “Factor Score Detail” and “Factor Interpretation” sections, and the regime cards are shown in the UI as well  .

The market snapshot section also shows the inputs used by the engine, including derived metrics like `SPX vs 200SMA %` and `Drawdown %` .
