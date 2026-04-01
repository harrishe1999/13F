# 13F Holdings Intelligence Dashboard

A Streamlit research dashboard that pulls **real SEC 13F filings** and layers on portfolio analytics.

## What this version now includes

- quarter-selectable portfolio treemap based on actual 13F weights
- SEC-backed manager name search to resolve manager name -> CIK
- disk-backed request caching to reduce repeated SEC pulls
- ticker mapping layer using SEC's public company ticker reference file
- sector and theme overlays for portfolio profiling
- quarter-over-quarter adds / trims / new / exited positions
- historical weight line charts, rank-history charts, and weight heatmap
- multi-manager comparison snapshot for the same quarter
- overlap heatmap across managers' top positions
- concentration diagnostics (top 10 concentration, HHI)
- optional price-following return layer using Yahoo Finance
- exportable quarter tables, delta tables, and text report

## Run locally

```bash
cd 13f_dashboard
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export SEC_USER_AGENT="Your Name your_email@example.com"
streamlit run app.py
```

On Windows PowerShell:

```powershell
$env:SEC_USER_AGENT="Your Name your_email@example.com"
streamlit run app.py
```

## Does this require an API key?

No paid API key is required for the SEC data layer.

The app uses:

- SEC public submissions JSON on `data.sec.gov`
- SEC filing archive directories and XML information tables on `sec.gov`
- SEC public ticker reference file `company_tickers_exchange.json`
- optional Yahoo Finance market-price lookup for the convenience return layer

What it **does** need:

- normal internet access
- a proper `User-Agent` header for SEC fair-access compliance

## Architecture notes

- `data_source.py` handles SEC pulls, XML parsing, disk caching, ticker matching, sector/theme tagging, history building, and comparison analytics.
- `app.py` renders the Streamlit UI, charts, diagnostics, exports, and multi-manager views.
- `managers.py` stores popular preloaded 13F managers.
- `.cache/` is created locally at runtime for repeated network responses.

## Important limitations

- 13F is delayed by design. This is for **historical portfolio analysis**, not real-time holdings.
- 13F does **not** fully represent all economic exposure.
- Ticker mapping is best-effort. The raw 13F source is issuer/CUSIP-centric.
- Sector/theme tagging is rules-based, not a commercial taxonomy feed.
- The return layer is a convenience estimate, not audit-grade attribution.

## Suggested next upgrades after this build

- institutional-grade CUSIP/security-master integration
- user-defined watchlists and alerts for major quarter changes
- PDF/PNG report export for deck-ready output
- persistent favorites / saved manager sets
- follow-along strategy backtesting using filing-date availability assumptions
