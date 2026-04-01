# PROJECT_STATE

## Purpose

This repository is a Streamlit-based 13F research dashboard. It pulls real SEC 13F filings, parses filing XML directly, normalizes holdings into a usable table, and presents portfolio analytics such as:

- quarter-selectable holdings views
- official filing total value
- quarter-over-quarter changes
- multi-quarter history
- multi-manager comparison
- treemap, sector/theme views, and exports

This file is meant to be a high-signal handoff document so a new AI can resume work quickly without relying on old chat context.

## Current Repo Snapshot

- Repo path: `/Users/ruohang/Desktop/13f_dashboard`
- Main branch: `main`
- Remote: `git@github.com:harrishe1999/13F.git`
- Primary app entrypoint: `app.py`
- Main data layer: `data_source.py`
- Curated manager DB: `managers.py`
- Tests: `tests/test_data_source.py`

At the time this file was created:

- the project is already under git
- the app has been pushed to GitHub
- local runtime artifacts such as `.cache/`, `.venv/`, and `__pycache__/` are intentionally gitignored

## Recent Version History

### `06e55f1` - `V1`

This was the first meaningful checkpoint after the app became stable enough to run locally.

Major work that had been completed by this point:

- local Streamlit app bootstrapped and runnable
- SEC-backed 13F holdings loading
- better filing XML discovery for Berkshire and similar managers
- curated preset manager list
- fuzzy investor search path started to become usable

### `bcbdec4` - `docs: improve README`

This commit improved the public-facing documentation and aligned the README with the actual app behavior.

### `e396b87` - `V1.1 treemap label fixes`

This commit reflects the current product baseline.

Major work included:

- treemap label readability improvements
- elimination of `(?)` treemap nodes caused by duplicate leaf labels
- switch from `px.treemap(path=...)` style leaf identity to explicit unique `go.Treemap` node ids

## Current Product Behavior

### Manager selection

The sidebar now has two intentionally separate flows:

1. `Preset investors`
   - curated popular managers
   - selecting a preset updates the current holdings view immediately

2. `Search Investor`
   - fuzzy search by manager name
   - search does not auto-switch the portfolio view while typing
   - user clicks `Search Matches` to load results
   - user clicks `Show Result` to switch the active manager

This separation was an explicit UX decision to avoid constant page refreshes while searching.

### Current active manager state

`app.py` uses Streamlit session state for manager selection:

- `active_manager_name`
- `active_manager_cik`
- `active_manager_source`
- `preset_manager_name`
- `_last_preset_manager_id`
- `search_query`
- `search_candidate_cik`
- `search_results_records`

The rest of the page should read from the active manager state rather than from the search widgets directly.

### Quarter loading

For the selected manager CIK:

- available quarter labels are inferred from recent SEC filings
- selected quarter and comparison quarter load via `load_quarter_portfolio()`
- current quarter and previous quarter are used for the change tab

### Total reported value

The top-line `Total Reported Value` metric is now intentionally based on the official SEC filing cover-page total, not on a naive sum of parsed holdings values.

Important distinction:

- top metric = official SEC filing total
- tables/charts = filtered holdings currently visible under the active UI filters

This was a deliberate product correction after earlier unit mismatches.

## Important Past Bugs And Their Fixes

### 1. Berkshire holdings were not loading correctly

Root cause:

- the app originally over-relied on `primary_doc.xml`
- some filings store the actual holdings in another XML file, often a numerically named XML

Fix:

- `data_source.py` now enumerates filing XML candidates from `index.xml`
- it ranks likely information-table files and tries multiple XML candidates

Relevant functions:

- `list_information_table_candidates()`
- `discover_information_table_filename()`
- `load_information_table()`

### 2. Total reported value was off by `1000x` for some filings

Root cause:

- SEC information-table `value` fields are not always directly in USD
- some filings effectively behave like thousand-dollar units

Fix:

- parse filing cover-page metadata
- capture official `tableValueTotal` and `tableEntryTotal`
- infer whether raw holdings totals align directly or need a `* 1000` scale

Relevant functions:

- `parse_filing_cover_metadata()`
- `get_filing_cover_metadata()`
- `_infer_value_unit_scale()`
- `summarize_portfolio()`

Important output fields now carried through the pipeline:

- `official_total_value_usd`
- `filtered_total_value_usd`
- `table_entry_total`
- `value_unit_scale`

### 3. Search flow used to refresh holdings too aggressively

Root cause:

- search input and displayed manager were too tightly coupled

Fix:

- split preset flow from search flow
- use session state as the source of truth
- search becomes an explicit two-step action

### 4. Treemap labels were either missing or replaced by `(?)`

There were two different problems:

1. Labels missing:
   - too many blocks tried to display long labels
   - small blocks swallowed text

2. `(?)` labels:
   - Plotly treemap path logic collided when multiple leaves in the same sector shared the same label, especially duplicate tickers

Fixes:

- label strategy now favors ticker-first display for smaller cells
- hover still contains richer detail
- treemap now uses explicit unique ids via `go.Treemap`

Relevant functions in `app.py`:

- `shorten_label()`
- `build_treemap_primary_label()`
- `build_treemap_text()`
- `build_treemap_nodes()`

## Architecture Overview

### `app.py`

`app.py` is the full Streamlit UI layer.

Major responsibilities:

- page configuration and styling
- manager picker and sidebar controls
- quarter selection
- metric cards
- overview tab
- change analysis tab
- history tab
- multi-manager compare tab
- diagnostics/export tab

Key top-level UI helpers:

- `metric_card()`
- `manager_picker()`
- `render_overview()`
- `render_changes()`
- `render_history()`
- `render_multi_manager()`
- `render_diagnostics()`
- `main()`

Notable UI/product decisions currently encoded in this file:

- preset dropdown only shows manager names, not CIK
- current view still shows CIK in the metric area
- treemap uses sector color grouping
- charts and tables are opinionated and tuned for research workflow, not raw filing reproduction

### `data_source.py`

This is the application data layer and most of the business logic.

Major responsibilities:

- SEC request execution
- disk-backed response caching
- SEC request throttling
- filing discovery
- cover-page metadata parsing
- information-table XML parsing
- ticker lookup and enrichment
- sector/theme inference
- portfolio summary metrics
- history building
- quarter comparison
- overlap and multi-manager views
- optional Yahoo Finance return estimation

Important patterns:

- network requests are cached under `.cache/`
- many functions are decorated with `@st.cache_data`
- failed SEC requests raise `SecRequestError`

Important dataclasses:

- `FilingRef`
- `CachedResponse`

### `managers.py`

This is the curated manager database plus local fuzzy search layer.

Current notable curated entries include:

- Berkshire Hathaway
- Bridgewater Associates
- Pershing Square Capital
- Scion Asset Management
- H&H International
- Citadel Advisors
- Renaissance Technologies
- Point72 Asset Management
- Viking Global Investors

Important implementation details:

- curated rows have `name`, `display`, `cik`, `aliases`, `popular`
- local search uses normalized text plus staged ranking
- ranking roughly prefers exact match, prefix match, alias hits, substring matches, then fuzzy similarity

Important note:

- `H&H International` was added specifically to support Duan Yongping-related lookup
- it maps to `H&H International Investment, LLC`
- current curated CIK is `1759760`
- aliases include `Duan Yongping`

### `tests/test_data_source.py`

This is intentionally small right now.

It currently covers:

- cover-page metadata parsing
- unit-scale inference for direct USD totals
- unit-scale inference for thousand-USD totals

This is useful but still shallow compared with the app surface area.

## Data Flow Summary

The rough data flow for a quarter view is:

1. user chooses a manager CIK
2. app derives available quarter labels from SEC submissions
3. `find_filing_for_quarter()` locates the filing
4. `load_information_table()` discovers and parses the actual holdings XML
5. cover metadata is read to determine official total and unit scale
6. holdings are enriched with weights, ticker guesses, sectors, and themes
7. `summarize_portfolio()` produces the metrics used by the UI
8. overview, change, history, compare, and export views are built from this normalized dataframe

## Runtime Setup

### Local run

Typical local setup:

```bash
cd /Users/ruohang/Desktop/13f_dashboard
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export SEC_USER_AGENT="Your Name your_email@example.com"
python3 -m streamlit run app.py
```

The app will usually open on `http://localhost:8501`, but in practice alternate ports like `8502`, `8503`, or `8504` may be used if earlier Streamlit processes are still alive.

### Important environment requirement

Set a real `SEC_USER_AGENT`.

The code currently defaults to:

`13F Dashboard for personal research contact@example.com`

That default is only a placeholder and should not be relied on for serious use.

### Local cache behavior

- HTTP responses are cached under `.cache/`
- cache TTL is currently 24 hours for network responses
- Streamlit also caches selected function outputs

This means stale data or stale code/data combinations can happen if the process has not been cleanly restarted.

## Known Operational Lessons

### Restart the Streamlit process cleanly after schema changes

At one point the app hit:

- `KeyError: 'official_total_value_usd'`

Root cause:

- the running process effectively combined new `app.py` expectations with old cached or old-loaded `data_source.py` behavior

Practical lesson:

- after changing output schema between modules, stop old Streamlit processes and relaunch cleanly

### Port collisions are common during iteration

Because multiple Streamlit processes were started during development, ports shifted across runs.

If behavior looks stale:

- check whether an older tab is still open on an older port
- hard refresh
- or stop all old Streamlit processes and relaunch once

## Current UI / Feature Inventory

### Overview tab

- sector-colored treemap
- auto commentary
- top holdings snapshot table
- HHI / concentration note card
- sector breakdown bar chart
- theme breakdown pie chart
- filterable top holdings table

### Quarter Changes tab

- new / exited / added / trimmed metrics
- adds and trims tables
- change bar chart
- full change ledger

### History tab

- multi-quarter holding weight lines
- rank history lines
- holdings heatmap

### Manager Compare tab

- multi-manager snapshot table
- top-10 concentration chart
- positions vs HHI scatter
- overlap heatmap

### Diagnostics & Export tab

- unmapped holdings table
- optional return-following table via Yahoo Finance
- CSV export for current quarter
- CSV export for quarter changes
- text report export

## Current Treemap Implementation Notes

The treemap is one of the more customized parts of the app.

Current behavior:

- colors are assigned primarily by sector
- manager name is the root node
- sectors are the intermediate nodes
- holdings are leaf nodes
- leaf ids are manually generated for uniqueness

Leaf display strategy:

- larger blocks can show ticker plus weight
- medium blocks typically show ticker only
- very small blocks can intentionally show no inline text and rely on hover

Hover currently aims to include:

- full issuer name
- ticker
- weight
- market value
- sector
- themes

If future treemap work happens, preserve the unique-id structure. Reverting to `path=[manager, sector, label]` will likely reintroduce `(?)` nodes for duplicate labels.

## Current Search / Manager Matching Notes

The app now uses a hybrid search strategy:

1. local curated manager search from `managers.py`
2. SEC browse-edgar company search from `data_source.py`
3. combined ranking with curated results generally preferred when stronger

Current assumptions:

- curated names should win for common institutions
- user may type partial names such as `berkshire`
- aliases matter
- ambiguous SEC search results can still include non-target entities

The current local search is useful, but not yet a production-grade entity resolution system.

## Known Limitations

These are not necessarily bugs, but they are active quality constraints:

- ticker mapping is best-effort and may miss or mis-map some securities
- sector/theme tagging is heuristic, not vendor-grade classification
- some managers may file unusual XML structures that still need edge-case handling
- SEC search results can include irrelevant companies with similar names
- overlap analysis is based on visible top names, not a fully normalized security master
- Yahoo Finance follow-along returns are approximate and optional
- Streamlit emits `use_container_width` deprecation warnings in some places

## Validation That Has Already Been Done

Known checks performed during development:

- Python syntax compilation passed for main files
- unit tests in `tests/test_data_source.py` passed
- Berkshire latest filing used to validate official total logic
- Berkshire and Bridgewater were used repeatedly as live sanity-check managers
- treemap duplicate-label issue was checked using Berkshire

## Suggested Commands For The Next AI

If the next AI needs to re-establish context quickly, these commands are the highest-value starting point:

```bash
git log --oneline -5
git status --short
sed -n '1,220p' README.md
sed -n '1,260p' managers.py
sed -n '1,260p' app.py
sed -n '1,320p' data_source.py
```

If the next AI needs to validate the basics:

```bash
python3 -m py_compile app.py data_source.py managers.py tests/test_data_source.py
.venv/bin/python -m unittest discover -s tests
```

If the next AI needs to run the app:

```bash
source .venv/bin/activate
export SEC_USER_AGENT="Your Name your_email@example.com"
python3 -m streamlit run app.py
```

## Deployment Direction Already Discussed

The recommended public deployment path discussed with the user was:

- Streamlit Community Cloud

Planned deployment shape:

- repo: `harrishe1999/13F`
- branch: `main`
- main file: `app.py`
- Python version: `3.11`
- secret:

```toml
SEC_USER_AGENT = "Ruohang He ruohang1025@gmail.com"
```

This deployment was discussed conceptually, but not yet implemented inside the repo.

## User Preferences And Collaboration Notes

Useful behavioral context for future AI handoff:

- the user is iterating quickly and likes shipping in named versions such as `V1`, `V1.1`
- the user values direct execution over long planning-only responses
- the user often wants the app actually run, verified, committed, and pushed
- the user is comfortable with Chinese and has been communicating primarily in Chinese
- the user cares about product feel, especially UI polish and practical usability
- when a change is working well, the user may ask to commit immediately

## Recommended Next Improvements

These are reasonable next-step candidates, based on the current codebase:

- expand test coverage beyond unit-scale logic
- add a dedicated `PROJECT_STATE.md` update step after each meaningful version
- reduce Streamlit deprecation warnings
- improve ticker resolution and entity disambiguation
- improve search ranking for ambiguous SEC results
- add deployment config notes or helper files for Streamlit Cloud
- refine chart readability and mobile behavior further

## Handoff Checklist For The Next AI

When picking up this repo, the next AI should:

1. read this file first
2. read `README.md`
3. inspect `git log --oneline -5`
4. confirm current git status
5. run tests before changing core data logic
6. restart Streamlit cleanly if touching cross-module schemas
7. preserve treemap unique-id behavior
8. preserve the separation between preset selection and explicit search result display

## Files Most Likely To Change In Future Iterations

- `app.py`
  - UI tweaks, treemap behavior, layout, interactions

- `data_source.py`
  - filing parsing, manager lookup, ticker mapping, stats, caching

- `managers.py`
  - curated presets, aliases, ranking tweaks

- `README.md`
  - public project documentation

- `tests/test_data_source.py`
  - regression coverage for data-layer fixes

## Final Mental Model

This app is no longer a toy script. It is a small but real product with:

- a custom SEC ingestion layer
- a curated search layer
- a multi-tab research UI
- a versioned git history
- a public GitHub repo

The two areas where regressions are most likely are:

1. SEC data ingestion and normalization
2. UI interaction coupling in Streamlit session state

Any future AI should treat those two areas with extra care.
