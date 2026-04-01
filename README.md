# 13F Holdings Intelligence Dashboard

A Streamlit dashboard for exploring real SEC 13F filings with portfolio analytics, manager search, quarter comparisons, historical trends, and export tools.

This app is designed for research use: it pulls public SEC filing data, parses the filing XML directly, normalizes holdings into a usable table, and layers on visual analysis for well-known investment managers.

## What It Does

- loads real 13F-HR filings from SEC EDGAR
- shows quarter-selectable holdings for a manager
- displays an enhanced treemap with sector-based color grouping
- shows official SEC filing total value at the top of the page
- compares quarters to identify new, added, trimmed, stable, and exited positions
- builds multi-quarter holding histories and rank trends
- compares multiple managers in the same quarter
- estimates simple follow-along returns with Yahoo Finance when available
- exports current-quarter tables, change tables, and a text summary

## Current UX

The sidebar now has two separate manager-selection flows:

- `Preset investors`
  - curated list of popular managers
  - changing the preset updates the holdings view immediately

- `Search Investor`
  - supports fuzzy search such as `berkshire`, `pershing`, `scion`, or `Duan Yongping`
  - `Search Matches` loads candidate managers into a dropdown
  - `Show Result` switches the current holdings view only when you explicitly click it
  - typing in search no longer causes the holdings page to constantly refresh

The current view still shows the selected manager's CIK in the metric area, but the preset dropdown itself stays clean and name-only.

## Data Sources

The app uses public data only:

- SEC submissions JSON from `data.sec.gov`
- SEC filing archive directories and filing XML from `sec.gov`
- SEC company ticker reference file `company_tickers_exchange.json`
- optional Yahoo Finance prices for the convenience return layer

No paid API key is required.

## Important Data Notes

- 13F is delayed by design, so this is a historical holdings dashboard, not a live portfolio tracker.
- the top `Total Reported Value` metric uses the official SEC filing cover-page total
- holdings tables, charts, and weights are built from the information table after your selected filters are applied
- ticker matching is best-effort and issuer/CUSIP-based filings are not a perfect security master
- sector and theme tagging are rules-based overlays, not vendor-grade classifications
- the return layer is approximate and meant for convenience, not audit-grade attribution

## Featured Managers

The curated preset list currently includes names such as:

- Berkshire Hathaway
- Bridgewater Associates
- Pershing Square Capital
- Scion Asset Management
- H&H International Investment, LLC
- Citadel Advisors
- Renaissance Technologies
- Viking Global Investors
- Point72 Asset Management

You can also search SEC entities outside the curated list and display them through the search flow.

## Project Structure

- `app.py`
  - Streamlit UI
  - manager selection flow
  - charts, tables, diagnostics, and downloads

- `data_source.py`
  - SEC requests and caching
  - filing discovery
  - filing cover-page metadata parsing
  - XML holdings parsing
  - value normalization
  - portfolio analytics and comparison logic

- `managers.py`
  - curated manager database
  - fuzzy local manager search

- `tests/test_data_source.py`
  - basic tests for filing total parsing and unit normalization

## Run Locally

```bash
cd 13f_dashboard
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export SEC_USER_AGENT="Your Name your_email@example.com"
python3 -m streamlit run app.py
```

On Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:SEC_USER_AGENT="Your Name your_email@example.com"
python -m streamlit run app.py
```

Then open the local URL printed by Streamlit, usually `http://localhost:8501`.

## Environment Requirements

- Python 3.11+ recommended
- normal internet access
- a reasonable `SEC_USER_AGENT` string for SEC fair-access compliance

## Development Notes

- network responses are cached locally in `.cache/`
- `.venv/`, `.cache/`, and Python cache files are ignored by git
- the app has been tested against Berkshire Hathaway's latest available filing to verify the official reported-value logic

## Known Limitations

- some SEC search results can include non-investment entities with similar names
- multi-manager overlap is based on visible top positions, not a full security-master-normalized overlap model
- managers that file unusual XML structures may still need edge-case handling
- Streamlit currently emits `use_container_width` deprecation warnings; these do not affect app behavior

## Roadmap Ideas

- cleaner investor search ranking for ambiguous SEC names
- saved manager watchlists
- PDF or image export for presentation-ready reports
- more robust security-master style ticker resolution
- filing-date-aware backtesting workflows
