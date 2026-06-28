TSP Rebalance Engine — Master Project Handoff

1) Purpose & Scope
This project is an interactive, browser-hosted Streamlit application designed as a decision-support dashboard for TSP (Thrift Savings Plan) allocation management and Interfund Transfer (IFT) discipline. It bridges the gap between active macroeconomic/stress-factor analysis and the strict mechanical limits of the federal retirement system.

This engine is not an automated trading bot; it is a tactical risk-management dashboard designed to be run daily by the user to manage portfolio drift and confirm structural market transitions before executing changes manually on TSP.gov.

2) System Architecture & Data Storage
The application utilizes a localized state management model requiring zero external databases. It persists settings, logs, and transaction states directly to the local file system.

A. Gated Files & Resilient Storage
To prevent data corruption during write interrupts (which could otherwise result in blank configuration files and system-launch crashes), the engine implements an atomic write-and-replace mechanism coupled with automated backups:

Main Config (tsp_config.json) & Backup Config (tsp_config.json.bak): Stores current holdings, user-defined thresholds, safety rules, and fallback indicators.

Active State (tsp_state.json) & Backup State (tsp_state.json.bak): Maintains the active tracking month, current monthly IFT count, last executed transfer date, and signal histories.

Secure Recovery File I/O (safe_load_json / safe_save_json): Before writing config or state updates, the engine copies the valid file on disk to a .bak backup. If the primary JSON file fails to parse on launch, the engine automatically heals itself by restoring the environment from the latest backup.

Daily Log (tsp_daily_log.csv): Appends an immutable, flat-file chronological history of every generated signal run for archiving and auditing.

B. Credentials & Streamlit Secrets Gating
API keys are handled via a prioritized fallback sequence to ensure seamless local execution and cloud portability:

Streamlit Secrets: The engine natively checks for encrypted keys under fred_api_key or FRED_API_KEY within the hosting platform's secrets console (or local .streamlit/secrets.toml).

Local Configuration File: If system secrets are absent, it reads the user-entered key from tsp_config.json.

Dynamic UI Input: A masked text field in the sidebar allows users to update keys live. If system secrets are actively running, this field indicates that secure platform secrets are overriding manual entry.

3) Live Macro & Market Data Pipeline
To maximize stability, the data collection pipeline uses a highly resilient, multi-tiered fallback architecture. If primary APIs are restricted, throttled, or offline, the engine falls back to alternative data nodes or user-defined configuration defaults.

A. Data Retrieval Hierarchy
Primary Tier (FRED API JSON): Directly queries the official Federal Reserve Economic Data (FRED) API using the secure API key, retrieving JSON payloads for raw indicators [2].

Secondary Tier (DBnomics API Mirror): If no FRED key is available or the connection fails, the system automatically redirects requests to the unblocked DBnomics public FRED mirror API, parsing the respective endpoint data.

Third Tier (Dynamic Web Scraping & CSV Fallbacks):

Composite PMIs: Parsed from Trading Economics (80% services / 20% manufacturing).

Shiller CAPE: Scraped dynamically from Multpl.com.

Market Breadth: Pulled from Yahoo Finance (^S5TH) or scraped via Barchart as a backup.

Public CSVs: Falls back to public fredgraph.csv download paths.

Fourth Tier (Config/Default Fallbacks): Uses local, user-customizable hardcoded overrides.

B. High-Efficiency Caching Policy
The data pipeline is governed by a 1-hour caching policy (ttl=3600 seconds). This optimizes API performance, limits call volume to protect the user's private FRED API key from rate limits, and ensures rapid reload times during manual threshold adjustments.

4) Strategic Allocation Engine Logic
The engine evaluates eight core risk dimensions. Scores are tallied dynamically to assign one of four primary allocation regimes.

A. Scored Factors
Inflation: Evaluated via Core PCE YoY. Compressed or supported based on 10Y Breakeven Inflation trends.

Growth: Calculated via Composite PMI. Penalized under heavy Initial Jobless Claims trends.

Liquidity: Governed by the Net Quarterly Senior Loan Officer Opinion Survey (SLOOS). Supported by Fed Asset expansion or penalized by Quantitative Tightening (WALCL YoY).

Credit Spreads: Scored via the Option-Adjusted Spread (OAS) of High Yield Corporate Bonds.

Valuation: Evaluated using Shiller CAPE. Valuation ceilings are dynamically expanded or compressed based on 10Y Real Yield levels.

Market Stress: Measured via the VIX Spot index.

Momentum: Assessed by the S&P 500's distance from its 200-day Simple Moving Average (SMA).

Drawdown: Scored based on the current S&P 500 peak-to-trough drop.

Additional Stress Modifier: The St. Louis Fed Financial Stress Index (STLFSI) applies direct point penalties to Stress and Momentum categories, occasionally locking the system into maximum-defense postures under systemic stress.

B. The Four Policy Regimes
RISK-ON OVERRIDE (Score 
≥
+
5
≥+5
, PCE 
<
2
%
<2%
, CAPE 
<
26
<26
, Momentum stable)

Base Targets: G: 35% | C: 45% | I: 15% | S: 5% | F: 0%

OPTIMIZED NEUTRAL (Score 
≥
0
≥0
)

Base Targets: G: 45% | C: 35% | I: 10% | S: 10% | F: 0%

DEFENSIVE ALLOCATION (Score 
<
0
<0
)

Base Targets: G: 65% | C: 20% | I: 10% | S: 5% | F: 0%

High Risk Valuation Sub-posture: G: 70% | C: 20% | I: 5% | S: 5% | F: 0%

EMERGENCY DISPATCH (Score 
−
50
−50
, triggered by panic valve)

Base Targets: G: 100% | F: 0% (Or G: 90% | F: 10% if bond yield is unlocked)

5) Modifiers, Overlays, and Safety Gates

A. Policy Overlays
Asymmetric Volatility Filter: If Market Stress or Momentum indicators score 
≤
−
3
≤−3
, the S Fund (Small Cap) allocation is removed entirely and redistributed (to G Fund if in a nonnegative regime, or to I Fund if in a negative regime).

Strong USD Modifier: If the US Dollar Index (DXY) registers 
≥
103.5
≥103.5
, the engine shifts 5% from the International Stock Index (I Fund) to domestic large-caps (C Fund) to hedge currency headwind.

F Fund Yield Unlock: If the real yield (10Y Yield - Core PCE YoY) 
≥
1.5
%
≥1.5%
 and sovereign bond volatility (MOVE Index) 
<
120
<120
, the F Fund is unlocked, shifting 10% of G Fund cash into bonds.

B. 3-Day Panic Valve
The engine shifts immediately to EMERGENCY DISPATCH (Composite Score 
−
50
−50
) if:

VIX registers 
≥
30
≥30
 for 3 consecutive days, or

SPX closes 
≤
−
5
%
≤−5%
 below its 200-day SMA for 3 consecutive days.

Breadth Override: If market breadth remains 
>
60
%
>60%
 (S&P 500 stocks above their 200 SMA), the panic valve is overridden, allowing standard regime calculations to continue.

6) IFT Gating and Decision Logic
code
Code
[ Run Signal ]
         |
         v
   [ 1. IFT remaining? (< 2) ] ---> NO ---> [ HOLD: No IFTs remaining ]
         | YES
         v
   [ 2. Cooldown active? ] -------> YES ---> [ HOLD: Cooldown active ]
         | NO
         v
   [ 3. Emergency Posture? ] ------> YES ---> [ SUBMIT IFT: Emergency Trigger ]
         | NO
         v
   [ 4. Target already met? ] -----> YES ---> [ HOLD: Target met ]
         | NO
         v
   [ 5. Consistent Regime? ] ------> NO ---> [ HOLD: Regime not confirmed ]
     (Last X consecutive days)
         | YES
         v
   [ 6. Boundary Score Shift? ] ---> NO ---> [ HOLD: Score change not strong enough ]
     (|Current - Prior window|)
         | YES
         v
   [ 7. Max Asset Drift met? ] ----> NO ---> [ HOLD: Allocation drift too small ]
         | YES
         v
  [ ACTION: SUBMIT IFT ]
A. Boundary Transition Gating (Fix)
To prevent stable regime shifts from being blocked, the engine calculates the difference between the current confirmed score (recent_scores[-1]) and the score recorded immediately prior to the confirmation window (recent_scores[-confirmation_days - 1]). If the difference is less than the Score change threshold, the transaction is blocked.

B. Max Single-Asset Drift Gating
The drift check compares your current portfolio against targeted targets using:
Drift
=
max
⁡
f
∈
{
G,C,I,S,F
}
∣
Current
f
−
Target
f
∣
Drift= 
f∈{G,C,I,S,F}
max
​	
 ∣Current 
f
​	
 −Target 
f
​	
 ∣

If the maximum deviation of any single fund is less than the Normal drift threshold %, the transaction is blocked.

C. Intraday Multi-Run Safeguard (Fix)
To protect confirmation history from database inflation via repeated manual button clicks within a single day, the engine checks last_run_date. Runs executed on the same calendar day update the latest log index in place rather than appending a new historical entry.

7) Output & Visual Engine

A. Interactive Step-by-Step IFT Order Guide
When the safety gates authorize a transaction (SUBMIT IFT), the engine generates an action plan card on Tab 1. It isolates only the funds undergoing adjustment and builds clear instructions for logging into the TSP.gov portal:
Delta
f
=
Target
f
−
Current
f
Delta 
f
​	
 =Target 
f
​	
 −Current 
f
​	
 

For each adjusted asset, it displays instructions like: Set C Fund to 35.0% (Adjustment: +5.0%).

B. Visual Gaps & Alignment Engine
To keep the dashboard compact and readable:

CSS :has() Pseudo-Selector: Removed dynamic in-loop <style> generation. The global stylesheet uses modern :has(.card-live) and :has(.card-failed) selectors to style container blocks.

Zero-Height Markers: Inserted markers as hidden, display-less <div style="display:none;"></div> tags. This eliminates invisible container heights and vertical gaps.

Card Styling Alignment: Explicitly declared padding: 1rem !important;, margin-top: 6px !important;, margin-bottom: 0.6rem !important;, and transition timings on container wrappers. This ensures the editable Market Snapshot cards align perfectly with the static Factor Scores cards.
