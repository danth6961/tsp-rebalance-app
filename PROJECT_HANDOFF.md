# PROJECT_HANDOFF.md  
# TSP Rebalance Engine — Master Project Handoff

## 1) Purpose

This project is a **Streamlit-based TSP allocation rebalance engine**.  
It fetches live macro/market data, computes factor scores, determines a regime, outputs a target TSP allocation, and decides whether the user should **HOLD** or **SUBMIT IFT**.

The design goals are:

- browser-hosted usage
- no local software installation required for the end user
- lightweight and maintainable Python code
- manual control over TSP IFT usage
- clear logs, exports, and state persistence
- fast enough for daily monitoring
- conservative enough to respect TSP transfer limits

---

## 2) Core project philosophy

This app is **not** meant to be a fully automated trading system.

It is meant to be a **decision support tool** for TSP allocation management.

Key principles:

- run the model daily
- preserve IFT discipline
- track monthly IFT usage manually
- keep the logic transparent
- allow emergency defense when conditions deteriorate
- make the output easy to understand and audit

---

## 3) Data sources

### Live FRED inputs
The app uses the official FRED CSV endpoint for:

- `DRTSCIS` → SLOOS proxy
- `BAMLH0A0HYM2` → High Yield OAS
- `STLFSI4` → St. Louis Fed Financial Stress Index
- `DGS10` → 10-year Treasury yield

### Live Yahoo Finance inputs
The app uses `yfinance` for:

- `^VIX` → VIX spot/history
- `DX-Y.NYB` → DXY spot/history
- `^GSPC` → S&P 500 history

### Default / placeholder inputs
The following are still defaulted in the current version:

- Core PCE YoY
- ISM PMI
- Shiller CAPE
- Forward EPS growth YoY
- Market breadth

These can be replaced later with live feeds if desired.

---

## 4) Engine logic

The engine computes a set of factor scores and then assigns a regime.

### Scored factors
The engine evaluates:

1. Inflation
2. Growth
3. Liquidity
4. Credit spreads
5. Valuation
6. Market stress
7. Momentum
8. Drawdown

### Typical scoring range
Each factor generally receives a score from:

- `+3` = strongly positive
- `+1` = mildly positive
- `0` = neutral
- `-3` = mildly negative
- `-5` = strongly negative

### Additional stress adjustment
The STLFSI factor can impose extra penalties on stress and momentum, and in severe cases force a much more defensive posture.

---

## 5) Regime logic

The engine classifies the environment into one of four regimes.

### A) RISK-ON OVERRIDE
Conditions:
- composite score `>= 5`
- inflation < 2.0
- CAPE < 26.0
- momentum is not breaking down

Base allocation:
- `G: 35`
- `C: 45`
- `I: 15`
- `S: 5`
- `F: 0`

This is the most aggressive regime.

---

### B) OPTIMIZED NEUTRAL
Conditions:
- composite score `>= 0`

Base allocation:
- `G: 45`
- `C: 35`
- `I: 10`
- `S: 10`
- `F: 0`

This is the default balanced regime.

---

### C) DEFENSIVE ALLOCATION
Conditions:
- composite score `< 0`

Base allocation:
- `G: 65`
- `C: 20`
- `I: 10`
- `S: 5`
- `F: 0`

If valuation is very poor and volatility is elevated, it can become even more defensive:
- `G: 70`
- `C: 20`
- `I: 5`
- `S: 5`
- `F: 0`

---

### D) EMERGENCY DISPATCH
Triggered when the 3-day panic valve breaches.

Emergency allocation:
- `G: 90`
- `F: 10`

If the F Fund is not unlocked:
- `G: 100`
- `F: 0`

This is the maximum-defense mode.

---

## 6) Panic valve logic

The engine checks for multi-day market stress.

### Trigger conditions
A panic valve activates if:

- VIX is `>= 30` for 3 consecutive days, or
- SPX is `<= -5%` below its 200-day SMA for 3 consecutive days

### Breadth override
If market breadth is above `60`, the valve can be overridden.

### Result
If the valve is not overridden, the engine returns:
- `total_score = -50`
- `EMERGENCY DISPATCH`

---

## 7) Overlays and modifiers

### Asymmetric volatility overlay
If market stress or momentum is weak:

- remove the S Fund allocation
- redistribute it:
  - to G if regime is nonnegative
  - to I if regime is negative

### Strong DXY overlay
If DXY is strong:
- shift 5% from I to C

### F Fund unlock
If:

```text
10Y yield - Core PCE >= 1.5
