Project Handoff: TSP Rebalance Engine
What this project is
A Streamlit-based TSP allocation decision-support app that:

fetches live macro/market data with fallbacks
scores market regime conditions
suggests a TSP allocation target
decides whether an IFT should be submitted
logs runs and audit history
renders a polished dashboard with tabs/cards
Current architecture
The project is already split into modules:

app.py — Streamlit UI and orchestration
ui.py — reusable tile/card/table rendering helpers
engine.py — regime scoring and IFT decision logic
data_sources.py — FRED / DBnomics / Yahoo / scraping / snapshot fetches
storage.py — JSON/CSV persistence and backup handling
constants.py — paths, defaults, thresholds
utils.py — parsing and date helpers
models.py — dataclasses / typed structures
The latest work focused heavily on UI polish and tile rendering.

What the user specifically wants
Keep these UI elements:
Strategic Regime Directory cards at the bottom of the Allocation tab
Factor Scores tiles on the Factors tab
Fetch & Run Engine button at the bottom of the sidebar
Recent State Overview summary cards on the History tab
user explicitly said these are awesome and should not be changed
Combine these into one section:
Market Snapshot
Market Snapshot (Fully Editable)
The user wants one single Market Snapshot section that:

has the nice tile aesthetic
shows the current value inside the tile
has the editable number_input associated with the same tile
has the source pill inside the tile
avoids the duplicate “Fully Editable” section
Important visual requirement
The Market Snapshot should feel like:

title
current value
source pill inside the card
editable input
all visually unified
Also important:
The Strategic Regime Directory cards were previously broken by raw HTML leakage. They need to remain safe and rendered correctly.

Current UI status / issue history
Fixed / desired:
sidebar button is at the bottom
History summary cards are good
Factor score tiles look good
Problems encountered:
Strategic Regime cards rendered raw HTML/code in some versions
Market Snapshot leaked stray </div> text in some versions
Market Snapshot was split into two sections, which the user does not want
Market Snapshot values were not visible inside the tile in a version the user didn’t like
source pill should feel like it belongs inside the tile, not floating outside
Latest intended pattern for editable Market Snapshot tiles
The user wants a tile pattern conceptually like this:

python
Copy code

with st.container(border=True):
    st.markdown("""
    <div class="small-kpi">
        <div class="small-kpi-title">Core PCE YoY</div>
        <div class="small-kpi-value">3.40</div>
        <div class="small-kpi-note">LIVE (FRED)</div>
    </div>
    """, unsafe_allow_html=True)
    st.number_input(...)
Then refined so that:

the value is visible in the tile
the source pill is visually inside or attached to the tile
the input remains editable and aligned with the same tile
Current code directions that have been discussed
ui.py
Contains helpers such as:

tile_html(...)
render_metric_cards(...)
render_tile_grid(...)
recent_state_cards(...)
render_history_table(...)
app.py
Contains:

sidebar controls
Fetch & Run Engine button at bottom
Allocation tab with Strategic Regime cards
Factors tab with Factor Scores tiles
Market Snapshot combined section
History tab with summary cards unchanged
Logs & State tab
User preferences to preserve
Do:
keep polished tile/card style
keep layout cohesive
avoid raw JSON dumps where cards are better
keep the History summary cards exactly as they are
keep the regime cards visually clean and safe
Don’t:
reintroduce duplicate Market Snapshot sections
put Fetch & Run Engine elsewhere in the sidebar
change the History summary cards
let HTML leak into visible output
overcomplicate the Market Snapshot with two separate displays
Most recent code state
The latest app.py version included:

render_regime_card(info, is_active)
render_market_snapshot_editor()
Strategy cards in Allocation tab
Factor tiles in Factors tab
editable Market Snapshot section in Factors tab
History cards unchanged
The latest requested tweak was to make the source pill feel more “inside” the tile.

Best next step in the next chat
Start by asking to:

review or patch render_editable_metric_tile(...)
or generate the final combined Market Snapshot section
or produce the final polished app.py with the current desired UI
The user is likely to want a clean final module that:

uses one Market Snapshot section
renders the value inside the tile
keeps the pill visually integrated
preserves the current good History cards and sidebar layout
Suggested opening message for next chat
You can continue with something like:

I have the project handoff. I want to finalize the Market Snapshot as a single editable tile section with the value inside the tile and the pill integrated. Keep the History summary cards unchanged and the Fetch & Run Engine button at the bottom of the sidebar.

Files the user likely already has
constants.py
models.py
utils.py
storage.py
engine.py
data_sources.py
ui.py
app.py
