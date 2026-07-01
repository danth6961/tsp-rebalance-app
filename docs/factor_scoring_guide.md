# Tactical TSP Engine Scoring Guide

This document explains how the engine scores the current macro and market environment in plain English.

The goal of the scoring system is not to predict every market move. The goal is to identify broad tactical regimes that are good enough to support a disciplined TSP allocation process, with a strong emphasis on transparency, manual confirmation, and risk control.

---

## Overview

The engine evaluates two layers of signals:

1. Core factor scores
2. Macro overlay scores

The core factor scores are the main inputs to the composite score. The macro overlay scores add regime context and act as guards against overly aggressive positioning during hostile macro conditions.

The app shows these factors in the “Factor Score Detail” and “Factor Interpretation” sections, and the engine uses them to select the final regime and allocation.

---

## How to read this guide

- Positive scores generally support risk-taking.
- Negative scores generally support defense.
- Extreme negatives can force defensive or emergency behavior.
- Some factors are intentionally lagging macro variables.
- The engine is rule-based, so the same input will always produce the same score.

This is deliberate: the model is designed to be explainable and auditable rather than opaque.

---

# Core Factor Scores

## 1) Inflation

The inflation score is based on Core PCE YoY and is adjusted by breakeven inflation.

### Core PCE rules
- Core PCE < 1.8% → `+3`
- 1.8% to < 2.0% → `+1`
- 2.0% to 2.3% → `0`
- > 2.3% to 3.0% → `-3`
- > 3.0% → `-5`

### Adjustments
- If breakeven inflation > 2.6%, inflation is made worse
- If breakeven inflation < 1.8%, inflation is not allowed to stay too negative

### Interpretation
Low and stable inflation is friendly to equities and multiple expansion. Rising breakeven inflation usually indicates the market is becoming less comfortable with future price pressure.

This logic is implemented in `engine.py` in the market scoring path.

---

## 2) Growth

The growth score uses a weighted PMI blend and initial claims.

### PMI blend
The engine uses:
- `0.20 * ISM Manufacturing PMI`
- `0.80 * ISM Services PMI`

### PMI score bands
- > 55.0 → `+3`
- 51.5 to 55.0 → `+1`
- 50.0 to < 51.5 → `0`
- 48.0 to < 50.0 → `-3`
- < 48.0 → `-5`

### Claims adjustment
- If initial claims > 250K → subtract 1
- If initial claims > 280K → stronger negative penalty

### Interpretation
PMI captures broad business momentum, while claims help validate labor-market softness. When both weaken together, the growth score should fall quickly.

---

## 3) Liquidity

Liquidity is based on SLOOS and Fed assets growth.

### SLOOS rules
- SLOOS < -15.0 → `+3`
- SLOOS between -15.0 and 5.0 → `0`
- SLOOS > 5.0 → `-5`

### Fed assets adjustment
- Fed assets growth > 0.0 → add `+2`
- Fed assets growth <= 0.0 → subtract `2`

### Interpretation
Easier bank lending conditions and balance-sheet expansion are supportive of risk assets. Tight lending conditions and balance-sheet contraction are typically defensive signals.

---

## 4) Credit Spreads

Credit spreads are scored using HY OAS.

### Rules
- HY OAS < 3.0 → `+3`
- 3.0 to < 4.0 → `+1`
- 4.0 to 5.0 → `0`
- > 5.0 to 6.0 → `-3`
- > 6.0 → `-5`

### Interpretation
Widening high-yield spreads usually indicate deteriorating credit appetite, rising default concern, or a broader risk-off regime.

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

### Interpretation
High valuation is not automatically bearish, but it becomes more restrictive when growth expectations are weak or real yields are high. This helps avoid paying a premium for slow-growth or tightening-liquidity regimes.

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

### Interpretation
VIX captures broad market fear. STLFSI is used as a higher-level system stress gauge, and it can override otherwise constructive readings when financial conditions are clearly unstable.

---

## 7) Momentum

Momentum is based on SPX distance from its 200-day moving average.

### Rules
- Above +5.0% → `+3`
- 0.0% to +5.0% → `+1`
- -5.0% to < 0.0% → `-3`
- Below -5.0% → `-5`

### Interpretation
This is the engine’s trend confirmation measure. It helps prevent aggressive positioning when price action is already deteriorating.

---

## 8) Drawdown

Drawdown penalizes the engine when equity markets have already suffered meaningful losses.

### Conceptual use
- shallow drawdowns are tolerated
- deep drawdowns push the model toward defense
- very large drawdowns can contribute to emergency behavior

### Interpretation
This prevents the engine from ignoring market damage simply because other inputs are still moderate.

---

## 9) Yield Curve

The yield curve block captures recession and policy pressure.

### Conceptual use
- steeper or healthier curves support risk
- flatter or inverted curves are defensive
- worsening curve dynamics reduce the composite score

### Interpretation
This helps the engine avoid strong risk-on behavior during late-cycle or recession-prone environments.

---

## 10) DXY Overlay

The DXY overlay is a dollar-strength risk adjustment.

### Conceptual use
- strong dollar conditions are usually restrictive for risk assets
- dollar momentum can be used to reduce aggressiveness
- the engine uses a documented DXY tilt threshold in `constants.py` to avoid drift between code and documentation 

### Interpretation
A rising dollar often reflects tighter global liquidity, weaker non-U.S. risk appetite, or a more defensive macro regime.

---

# Macro Overlay Scores

Macro overlays are not the core regime score, but they are important regime guards.

They include themes such as:
- yield curve pressure
- inflation shock
- central bank stance
- liquidity pressure

These overlays can reduce the composite score or reinforce defensive decisions even when the core score looks acceptable.

### Why overlays matter
A core score alone can look fine while the broader macro backdrop is deteriorating. Overlays help avoid premature risk-on positioning.

---

# Composite Score Logic

The composite score is the sum of the core factor scores and overlay adjustments.

The engine then uses the composite score, plus selected guardrails, to choose a regime:

- strong positive composite → Risk-On Override
- moderate or mixed composite → Optimized Neutral
- negative composite → Defensive Allocation
- extreme stress / panic → Emergency Dispatch

The exact regime mapping is implemented in `engine.py`, while the allocation definitions live in `constants.py` so the UI and engine remain synchronized .

---

# Regime Interpretation

## Risk-On Override
Used when the environment is broadly supportive:
- growth is healthy
- inflation is manageable
- liquidity is adequate
- stress is low
- price trend is constructive

## Optimized Neutral
Used when signals are mixed but not clearly dangerous:
- moderate macro backdrop
- some support from trend or liquidity
- no need to force major defense

## Defensive Allocation
Used when risk is rising or the composite turns negative:
- tighter liquidity
- weaker growth
- worse stress
- more fragile trend or valuation backdrop

## Emergency Dispatch
Used when panic, stress, or emergency conditions dominate:
- maximum defense
- G-heavy allocation
- designed for rapid de-risking

The current tactical baseline allocations, including the emergency variants, are documented in the handoff file and centralized in `constants.py`  .

---

# Important Modeling Notes

## 1) This is a rule-based model
The system is intentionally deterministic and explainable. It does not try to learn thresholds live.

## 2) Many inputs are lagging
Macro inputs such as inflation, claims, SLOOS, and valuation are often delayed relative to market movement. This is acceptable, but it means the engine should be interpreted as a tactical macro overlay rather than a high-frequency timing model.

## 3) Thresholds should be treated as parameters
The current thresholds are sensible starting points, but they are still hand-chosen. They should be reviewed and backtested before being treated as permanently optimal.

## 4) Avoid double counting
Several signals can reflect the same underlying macro theme. Be careful when adding new indicators that already overlap heavily with existing ones.

---

# Practical Usage

The scoring system is meant to support a clean workflow:

1. Load the latest market snapshot
2. Score the environment
3. Select a regime
4. Build the target allocation
5. Review the explanation
6. Manually confirm any actual IFT action

That separation is important. The score should guide the user, not silently execute transactions.

---

# Summary

This scoring framework is designed to be:
- transparent
- tactical
- conservative enough for real-world usage
- easy to inspect in the UI
- compatible with manual IFT confirmation

If you change any scoring rule, make sure the following stay synchronized:
- `engine.py`
- `constants.py`
- `app.py`
- the regime consistency tests
