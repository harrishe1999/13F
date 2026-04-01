from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from data_source import (
    SecRequestError,
    available_quarter_labels,
    build_history,
    build_multi_manager_snapshot,
    compare_quarters,
    estimate_following_returns,
    load_quarter_portfolio,
    overlap_matrix,
    recent_manager_activity_summary,
    search_manager_matches,
    sector_breakdown,
    summarize_portfolio,
    theme_breakdown,
)
from managers import MANAGER_BY_ID, POPULAR_MANAGER_IDS, get_manager_record, popular_manager_options

DEFAULT_MANAGER_ID = "berkshire_hathaway"
SECTOR_COLOR_MAP = {
    "Financials": "#0f766e",
    "Consumer": "#d97706",
    "Software & Internet": "#2563eb",
    "Semiconductors": "#7c3aed",
    "Healthcare": "#dc2626",
    "Energy & Materials": "#15803d",
    "Other": "#475569",
}

st.set_page_config(
    page_title="13F Holdings Intelligence Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .block-container {padding-top: 1rem; padding-bottom: 1rem; max-width: 1550px;}
    .hero {
        background: linear-gradient(135deg, #0f172a 0%, #1e293b 55%, #334155 100%);
        color: white; border-radius: 20px; padding: 22px 24px; margin-bottom: 14px;
        border: 1px solid rgba(255,255,255,0.08);
    }
    .hero h1 {font-size: 1.9rem; margin: 0 0 0.35rem 0;}
    .hero p {margin: 0; color: rgba(255,255,255,0.82);}
    .metric-card {
        background: #ffffff; border: 1px solid #e7ebf0; border-radius: 18px;
        padding: 16px 18px; min-height: 108px; box-shadow: 0 1px 2px rgba(15, 23, 42, 0.03);
    }
    .metric-label {color:#64748b; font-size:0.88rem; margin-bottom: 8px;}
    .metric-value {font-size:1.55rem; font-weight:700; color:#0f172a;}
    .metric-sub {color:#475569; font-size:0.88rem; margin-top: 8px;}
    .note-card {
        background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 16px; padding: 16px 18px;
    }
    .small-note {color:#64748b; font-size:0.92rem;}
    </style>
    """,
    unsafe_allow_html=True,
)


def fmt_pct(x: float | None) -> str:
    if x is None or pd.isna(x):
        return ""
    return f"{x * 100:.2f}%"


def fmt_pct_pt(x: float | None) -> str:
    if x is None or pd.isna(x):
        return ""
    sign = "+" if x > 0 else ""
    return f"{sign}{x:.2f} pt"


def fmt_money(x: float | None) -> str:
    if x is None or pd.isna(x):
        return ""
    if abs(x) >= 1_000_000_000:
        return f"${x/1_000_000_000:.2f}B"
    if abs(x) >= 1_000_000:
        return f"${x/1_000_000:.2f}M"
    if abs(x) >= 1_000:
        return f"${x/1_000:.2f}K"
    return f"${x:,.0f}"


def metric_card(label: str, value: str, sub: str = "") -> None:
    st.markdown(
        f"""
        <div class='metric-card'>
            <div class='metric-label'>{label}</div>
            <div class='metric-value'>{value}</div>
            <div class='metric-sub'>{sub}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _set_active_manager(name: str, cik: str, source: str) -> None:
    st.session_state["active_manager_name"] = name
    st.session_state["active_manager_cik"] = cik
    st.session_state["active_manager_source"] = source


def _default_manager() -> dict:
    manager = get_manager_record(DEFAULT_MANAGER_ID)
    if manager is None:
        raise RuntimeError(f"Default manager {DEFAULT_MANAGER_ID} is missing from the manager database.")
    return manager


def _manager_id_by_cik(cik: str) -> str:
    for manager_id in POPULAR_MANAGER_IDS:
        manager = MANAGER_BY_ID[manager_id]
        if manager["cik"] == str(cik):
            return manager_id
    return ""


def _initialize_manager_state() -> None:
    default = _default_manager()
    if "active_manager_name" not in st.session_state:
        _set_active_manager(default["display"], default["cik"], "preset")
    if "preset_manager_name" not in st.session_state:
        st.session_state["preset_manager_name"] = default["name"]
    if "_last_preset_manager_id" not in st.session_state:
        st.session_state["_last_preset_manager_id"] = default["id"]
    if "search_query" not in st.session_state:
        st.session_state["search_query"] = ""
    if "search_candidate_cik" not in st.session_state:
        st.session_state["search_candidate_cik"] = ""
    if "search_results_records" not in st.session_state:
        st.session_state["search_results_records"] = []


def _format_search_option(row: pd.Series) -> str:
    source_label = "Curated" if row.get("source") == "curated" else "SEC"
    location = f" | {row['location']}" if str(row.get("location") or "").strip() else ""
    return f"{row['name']} | CIK {row['cik']} | {source_label}{location}"


def manager_picker() -> tuple[str, str, list[str]]:
    _initialize_manager_state()
    st.header("Manager Selection")
    preset_name_to_id = {MANAGER_BY_ID[manager_id]["name"]: manager_id for manager_id in POPULAR_MANAGER_IDS}
    preset_options = list(preset_name_to_id.keys())
    current_preset_name = st.session_state.get("preset_manager_name", _default_manager()["name"])
    preset_index = preset_options.index(current_preset_name) if current_preset_name in preset_options else 0
    selected_preset_name = st.selectbox("Preset investors", options=preset_options, index=preset_index, key="preset_manager_name")
    selected_preset_id = preset_name_to_id[selected_preset_name]
    if st.session_state.get("_last_preset_manager_id") != selected_preset_id:
        preset_manager = MANAGER_BY_ID[selected_preset_id]
        _set_active_manager(preset_manager["display"], preset_manager["cik"], "preset")
        st.session_state["_last_preset_manager_id"] = selected_preset_id

    st.markdown("### Search Investor")
    search_results = pd.DataFrame(st.session_state.get("search_results_records", []))
    search_options = [_format_search_option(row) for _, row in search_results.iterrows()] if not search_results.empty else []
    default_search_option = search_options[0] if search_options else "No matches yet"
    current_candidate_cik = str(st.session_state.get("search_candidate_cik", "") or "")
    if search_options:
        for option, (_, row) in zip(search_options, search_results.iterrows()):
            if str(row["cik"]) == current_candidate_cik:
                default_search_option = option
                break

    with st.form("search_investor_form", clear_on_submit=False):
        search_query = st.text_input(
            "Find investor by name",
            value=st.session_state.get("search_query", ""),
            key="search_query",
            placeholder="Type part of a manager name, e.g. Berkshire, Pershing, Scion",
            help="Search loads candidate investors only. Your current holdings view changes only after you click Show Result.",
        )
        chosen_search_option = st.selectbox(
            "Search results",
            options=search_options if search_options else ["No matches yet"],
            index=(search_options.index(default_search_option) if search_options else 0),
            disabled=not search_options,
        )
        c1, c2 = st.columns(2)
        search_matches = c1.form_submit_button("Search Matches", use_container_width=True)
        show_result = c2.form_submit_button("Show Result", use_container_width=True, disabled=not search_options)

    if search_matches:
        fresh_results = pd.DataFrame()
        if search_query.strip():
            try:
                fresh_results = search_manager_matches(search_query.strip(), limit=20)
            except Exception as e:
                st.caption(f"Live SEC search is unavailable right now: {e}")
        st.session_state["search_results_records"] = fresh_results.to_dict("records")
        st.session_state["search_candidate_cik"] = str(fresh_results.iloc[0]["cik"]) if not fresh_results.empty else ""
        st.rerun()

    if show_result and search_options:
        picked_row = search_results.iloc[search_options.index(chosen_search_option)]
        _set_active_manager(str(picked_row.get("display_name") or picked_row["name"]), str(picked_row["cik"]), "search")
        st.session_state["search_candidate_cik"] = str(picked_row["cik"])

    if search_query.strip() and search_results.empty:
        st.caption("No matching investors loaded yet. Click Search Matches to populate the dropdown.")

    selected_name = str(st.session_state["active_manager_name"])
    selected_cik = str(st.session_state["active_manager_cik"])
    selected_manager_id = _manager_id_by_cik(selected_cik)
    st.caption(f"Current view: {selected_name} | CIK {selected_cik}")

    compare_options = []
    compare_label_to_id = {}
    for manager_id in POPULAR_MANAGER_IDS:
        manager = MANAGER_BY_ID[manager_id]
        if manager["cik"] == selected_cik:
            continue
        label = manager["name"]
        compare_options.append(label)
        compare_label_to_id[label] = manager_id

    default_compare_ids = [manager_id for manager_id in ["pershing_square_capital", "scion_asset_management"] if manager_id in compare_label_to_id.values()]
    if selected_manager_id == "pershing_square_capital":
        default_compare_ids = [manager_id for manager_id in ["berkshire_hathaway", "scion_asset_management"] if manager_id in compare_label_to_id.values()]
    elif selected_manager_id == "scion_asset_management":
        default_compare_ids = [manager_id for manager_id in ["berkshire_hathaway", "pershing_square_capital"] if manager_id in compare_label_to_id.values()]

    default_compare_labels = [label for label, manager_id in compare_label_to_id.items() if manager_id in default_compare_ids]
    compare_labels = st.multiselect("Compare against other managers", options=compare_options, default=default_compare_labels)
    compare_managers = [compare_label_to_id[label] for label in compare_labels]
    return selected_name, selected_cik, compare_managers


def build_insight_summary(manager_name: str, portfolio: pd.DataFrame, stats: dict, delta: pd.DataFrame | None = None) -> list[str]:
    if portfolio.empty:
        return ["No portfolio rows were available for this view."]
    largest = portfolio.iloc[0]
    top_name = largest.get("ticker") or largest["issuer_clean"]
    points = [f"{manager_name} is led by {top_name} at {largest['weight']*100:.2f}% of reported long exposure."]

    if largest["weight"] >= 0.30:
        points.append("Single-name concentration is extreme. One thesis can dominate reported performance.")
    elif largest["weight"] >= 0.15:
        points.append("Top-name concentration is meaningful. This is still a conviction book.")
    else:
        points.append("Top position size is controlled relative to many concentrated hedge-fund books.")

    points.append(
        f"Top 10 holdings make up {stats['top10_weight']*100:.1f}% of the portfolio; HHI is {stats['hhi']:.3f}; leading sector is {stats['top_sector']} at {stats['top_sector_weight']*100:.1f}%."
    )
    points.append(
        f"Ticker mapping coverage is {stats['ticker_coverage']*100:.1f}%. Unmapped rows are mostly issuer-label or security-master noise, not fake data."
    )

    if delta is not None and not delta.empty:
        points.append(recent_manager_activity_summary(delta))
    return points


def render_overview(manager_name: str, portfolio: pd.DataFrame, stats: dict, delta: pd.DataFrame, min_weight_filter: float, show_ticker_first: bool, show_full_names: bool, top_n: int) -> None:
    left, right = st.columns([1.35, 1])
    with left:
        treemap_df = portfolio.copy()
        treemap_df = treemap_df[treemap_df["weight"] * 100 >= min_weight_filter].copy()
        if treemap_df.empty:
            treemap_df = portfolio.head(30).copy()
        treemap_df = treemap_df.head(80).copy()
        treemap_df["sector"] = treemap_df["sector"].fillna("Other").replace("", "Other")
        treemap_df["plot_label"] = treemap_df["label"] if show_ticker_first else treemap_df["issuer_clean"]
        if not show_full_names:
            treemap_df["plot_label"] = treemap_df["plot_label"].str.slice(0, 24)
        treemap_df["weight_pct"] = treemap_df["weight"] * 100
        fig = px.treemap(
            treemap_df,
            path=[px.Constant(manager_name), "sector", "plot_label"],
            values="weight_pct",
            color="sector",
            color_discrete_map=SECTOR_COLOR_MAP,
            hover_data={
                "ticker": True,
                "exchange": True,
                "sector": True,
                "themes": True,
                "market_value_usd": ":,.0f",
                "shares": True,
                "cusip": True,
                "weight_pct": ":.2f",
                "plot_label": False,
            },
        )
        fig.update_traces(
            texttemplate="<b>%{label}</b><br>%{value:.2f}%",
            textfont=dict(color="white", size=14),
            marker=dict(line=dict(color="rgba(248,250,252,0.92)", width=2)),
            hoverlabel=dict(bgcolor="#0f172a", font_color="white"),
            root_color="#dbeafe",
        )
        fig.update_layout(
            margin=dict(t=12, l=8, r=8, b=8),
            height=700,
            paper_bgcolor="rgba(0,0,0,0)",
            uniformtext=dict(minsize=11, mode="hide"),
        )
        st.plotly_chart(fig, use_container_width=True)

    with right:
        st.subheader("Auto commentary")
        for bullet in build_insight_summary(manager_name, portfolio, stats, delta if not delta.empty else None):
            st.markdown(f"- {bullet}")

        st.subheader("Top holdings snapshot")
        top5 = portfolio.head(5)[["ticker", "issuer_clean", "sector", "weight", "market_value_usd"]].copy()
        top5["Security"] = top5.apply(lambda r: f"{r['ticker']} - {r['issuer_clean']}" if str(r['ticker']).strip() else r['issuer_clean'], axis=1)
        top5["Weight"] = top5["weight"].map(lambda x: f"{x*100:.2f}%")
        top5["Value"] = top5["market_value_usd"].map(fmt_money)
        st.dataframe(top5[["Security", "sector", "Weight", "Value"]], use_container_width=True, hide_index=True)

        hhi_bucket = "Very concentrated" if stats["hhi"] >= 0.18 else "Moderately concentrated" if stats["hhi"] >= 0.10 else "Diversified"
        st.markdown(
            f"""
            <div class='note-card'>
            <b>HHI</b>: {stats['hhi']:.3f}<br>
            <b>Profile</b>: {hhi_bucket}<br>
            <b>Top 3 combined</b>: {portfolio.head(3)['weight'].sum()*100:.2f}%<br>
            <b>Top 5 combined</b>: {portfolio.head(5)['weight'].sum()*100:.2f}%<br>
            <b>Lead sector</b>: {stats['top_sector']} ({stats['top_sector_weight']*100:.2f}%)
            </div>
            """,
            unsafe_allow_html=True,
        )

    s1, s2 = st.columns([1, 1])
    with s1:
        sector_df = sector_breakdown(portfolio)
        if not sector_df.empty:
            sector_fig = px.bar(sector_df, x="weight", y="sector", orientation="h")
            sector_fig.update_layout(height=360, xaxis_title="Portfolio weight", yaxis_title="")
            st.plotly_chart(sector_fig, use_container_width=True)
    with s2:
        theme_df = theme_breakdown(portfolio)
        if not theme_df.empty:
            theme_fig = px.pie(theme_df.head(8), values="weight", names="theme")
            theme_fig.update_layout(height=360)
            st.plotly_chart(theme_fig, use_container_width=True)

    st.subheader("Top holdings table")
    search_term = st.text_input("Filter holdings by issuer / ticker / CUSIP", value="")
    table = portfolio.copy()
    if search_term.strip():
        q = search_term.strip().lower()
        table = table[
            table["issuer_clean"].str.lower().str.contains(q, na=False)
            | table["cusip"].str.lower().str.contains(q, na=False)
            | table["ticker"].fillna("").str.lower().str.contains(q, na=False)
            | table["sector"].fillna("").str.lower().str.contains(q, na=False)
        ].copy()
    table = table.head(top_n).copy()
    table["Weight"] = table["weight"].map(lambda x: f"{x*100:.2f}%")
    table["Market Value"] = table["market_value_usd"].map(fmt_money)
    table["Shares"] = table["shares"].fillna(0).map(lambda x: f"{x:,.0f}")
    table["Match Score"] = table["ticker_match_score"].map(lambda x: f"{x:.2f}" if x else "")
    st.dataframe(
        table[["ticker", "issuer_clean", "sector", "themes", "exchange", "title_class", "cusip", "Weight", "Market Value", "Shares", "Match Score", "put_call", "investment_discretion"]],
        use_container_width=True,
        hide_index=True,
    )


def render_changes(selected_q: str, prev_q: str, delta: pd.DataFrame) -> None:
    st.subheader(f"Quarter-over-quarter changes: {selected_q} vs {prev_q}")
    if delta.empty:
        st.info("Comparison data is not available for the selected quarter pair.")
        return

    k1, k2, k3, k4 = st.columns(4)
    with k1:
        metric_card("New Positions", str(int((delta['change_type'] == 'New').sum())), "Names not present in comparison quarter")
    with k2:
        metric_card("Exited Positions", str(int((delta['change_type'] == 'Exited').sum())), "Names fully removed")
    with k3:
        metric_card("Added / Increased", str(int(delta['change_type'].isin(['New', 'Added']).sum())), "Names with larger weight")
    with k4:
        metric_card("Trimmed / Exited", str(int(delta['change_type'].isin(['Trimmed', 'Exited']).sum())), "Names with smaller weight")

    d1, d2 = st.columns([1, 1])
    with d1:
        adds = delta[delta["change_type"].isin(["New", "Added"])].head(20).copy()
        adds["Security"] = adds.apply(lambda r: f"{r['ticker']} - {r['issuer_clean']}" if str(r['ticker']).strip() else r['issuer_clean'], axis=1)
        adds["Weight Δ"] = adds["weight_change_pct_pt"].map(fmt_pct_pt)
        adds["Current Wt"] = adds["w_curr"].map(lambda x: f"{x*100:.2f}%")
        st.markdown("**Largest adds / new positions**")
        st.dataframe(adds[["Security", "sector", "change_type", "Weight Δ", "Current Wt"]], use_container_width=True, hide_index=True)
    with d2:
        trims = delta.sort_values("weight_change_pct_pt").head(20).copy()
        trims["Security"] = trims.apply(lambda r: f"{r['ticker']} - {r['issuer_clean']}" if str(r['ticker']).strip() else r['issuer_clean'], axis=1)
        trims["Weight Δ"] = trims["weight_change_pct_pt"].map(fmt_pct_pt)
        trims["Current Wt"] = trims["w_curr"].map(lambda x: f"{x*100:.2f}%")
        st.markdown("**Largest trims / exits**")
        st.dataframe(trims[["Security", "change_type", "Weight Δ", "Current Wt"]], use_container_width=True, hide_index=True)

    flow_fig_df = pd.concat([
        delta.sort_values("weight_change_pct_pt", ascending=False).head(12),
        delta.sort_values("weight_change_pct_pt", ascending=True).head(12),
    ]).drop_duplicates(subset=["issuer_clean", "cusip"])
    flow_fig_df = flow_fig_df.sort_values("weight_change_pct_pt")
    if not flow_fig_df.empty:
        flow_fig_df["plot_label"] = flow_fig_df.apply(lambda r: f"{r['ticker']}" if str(r['ticker']).strip() else r['issuer_clean'], axis=1)
        bar = px.bar(flow_fig_df, x="weight_change_pct_pt", y="plot_label", orientation="h", color="change_type")
        bar.update_layout(height=760, yaxis_title="", xaxis_title="Weight change (percentage points)")
        st.plotly_chart(bar, use_container_width=True)

    st.subheader("Full change ledger")
    ledger = delta.copy()
    ledger["Security"] = ledger.apply(lambda r: f"{r['ticker']} - {r['issuer_clean']}" if str(r['ticker']).strip() else r['issuer_clean'], axis=1)
    ledger["Current Weight"] = ledger["w_curr"].map(lambda x: f"{x*100:.2f}%")
    ledger["Previous Weight"] = ledger["w_prev"].map(lambda x: f"{x*100:.2f}%")
    ledger["Weight Δ"] = ledger["weight_change_pct_pt"].map(fmt_pct_pt)
    ledger["Value Δ"] = ledger["value_change_usd"].map(fmt_money)
    st.dataframe(
        ledger[["ticker", "Security", "sector", "cusip", "change_type", "Current Weight", "Previous Weight", "Weight Δ", "Value Δ"]],
        use_container_width=True,
        hide_index=True,
    )


def render_history(cik: str, history_default: int, common_stock_only: bool, long_only: bool) -> pd.DataFrame:
    st.subheader("Historical weight trends")
    with st.spinner("Loading filing history."):
        hist = build_history(cik, common_stock_only=common_stock_only, long_only=long_only)
    if hist.empty:
        st.info("No historical series could be constructed from the available filings.")
        return hist

    hist["security_key"] = hist.apply(lambda r: r["ticker"] if str(r["ticker"]).strip() else f"{r['issuer_clean']} | {r['cusip']}", axis=1)
    latest = hist.sort_values(["report_date", "weight"], ascending=[False, False]).drop_duplicates(subset=["security_key"]) 
    default_names = latest.head(history_default)["security_key"].tolist()
    selected_names = st.multiselect("Select holdings for weight history", options=latest["security_key"].tolist(), default=default_names)

    plot_df = hist[hist["security_key"].isin(selected_names)].copy() if selected_names else hist.head(0)
    if not plot_df.empty:
        line = px.line(plot_df, x="report_date", y="weight", color="security_key", markers=True)
        line.update_layout(height=540, yaxis_tickformat=".1%", xaxis_title="", yaxis_title="Portfolio weight")
        st.plotly_chart(line, use_container_width=True)

        rank_df = plot_df.copy()
        rank_df["rank"] = rank_df.groupby("report_date")["weight"].rank(method="dense", ascending=False)
        rank_fig = px.line(rank_df, x="report_date", y="rank", color="security_key", markers=True)
        rank_fig.update_yaxes(autorange="reversed")
        rank_fig.update_layout(height=420, xaxis_title="", yaxis_title="Portfolio rank")
        st.plotly_chart(rank_fig, use_container_width=True)

    pivot = hist.pivot_table(index="security_key", columns="report_date", values="weight", aggfunc="sum", fill_value=0)
    if not pivot.empty:
        heat = go.Figure(data=go.Heatmap(z=pivot.values, x=[str(x.date()) for x in pivot.columns], y=pivot.index, coloraxis="coloraxis"))
        heat.update_layout(height=580, coloraxis={"colorbar": {"title": "Weight"}})
        st.plotly_chart(heat, use_container_width=True)

    return hist


def render_multi_manager(selected_q: str, compare_names: list[str], selected_name: str, selected_cik: str, long_only: bool, common_stock_only: bool) -> None:
    st.subheader("Multi-manager comparison")
    cik_map = {selected_name: selected_cik}
    for manager_id in compare_names:
        meta = get_manager_record(manager_id)
        if meta:
            cik_map[meta["display"]] = meta["cik"]

    snapshot = build_multi_manager_snapshot(cik_map, selected_q, long_only=long_only, common_stock_only=common_stock_only)
    if snapshot.empty:
        st.info("Could not build a multi-manager snapshot for this quarter selection.")
        return

    view = snapshot.copy()
    view["Top 10"] = view["top10_weight"].map(lambda x: f"{x*100:.2f}%")
    view["Largest Position Weight"] = view["largest_position_weight"].map(lambda x: f"{x*100:.2f}%")
    view["Total Value"] = view["total_value_usd"].map(fmt_money)
    st.dataframe(view[["manager", "positions", "Top 10", "hhi", "top_sector", "largest_position", "Largest Position Weight", "Total Value"]], use_container_width=True, hide_index=True)

    c1, c2 = st.columns(2)
    with c1:
        fig = px.bar(snapshot, x="manager", y="top10_weight", color="top_sector")
        fig.update_layout(height=420, xaxis_title="", yaxis_tickformat=".0%", yaxis_title="Top 10 concentration")
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        fig2 = px.scatter(snapshot, x="positions", y="hhi", size="total_value_usd", color="top_sector", hover_name="manager")
        fig2.update_layout(height=420, xaxis_title="Visible positions", yaxis_title="HHI")
        st.plotly_chart(fig2, use_container_width=True)

    overlap = overlap_matrix(cik_map, selected_q, long_only=long_only, common_stock_only=common_stock_only)
    if not overlap.empty:
        overlap_fig = go.Figure(data=go.Heatmap(z=overlap.values, x=overlap.columns, y=overlap.index, coloraxis="coloraxis"))
        overlap_fig.update_layout(height=520, coloraxis={"colorbar": {"title": "Overlap"}})
        st.plotly_chart(overlap_fig, use_container_width=True)


def render_diagnostics(selected_q: str, prev_q: str, portfolio: pd.DataFrame, delta: pd.DataFrame, filing_date: str) -> None:
    st.subheader("Diagnostics & export")
    c1, c2 = st.columns([1, 1])
    with c1:
        mapping = portfolio[portfolio["ticker"].fillna("") == ""].copy()
        if not mapping.empty:
            mapping["Market Value"] = mapping["market_value_usd"].map(fmt_money)
        st.markdown("**Unmapped holdings**")
        st.dataframe(mapping[["issuer_clean", "cusip", "title_class", "Market Value"]].head(30), use_container_width=True, hide_index=True)
    with c2:
        ret_df = estimate_following_returns(portfolio, start_date=filing_date, top_n=15)
        if ret_df.empty:
            st.info("Return estimation layer is optional and may be unavailable if price data cannot be fetched locally.")
        else:
            ret_df["Portfolio Wt"] = ret_df["portfolio_weight"].map(lambda x: f"{x*100:.2f}%")
            ret_df["Price Return"] = ret_df["price_return"].map(lambda x: f"{x*100:.2f}%")
            ret_df["Contribution"] = ret_df["weighted_contribution"].map(lambda x: f"{x*100:.2f}%")
            st.markdown("**Approximate follow-along return layer (since filing date)**")
            st.dataframe(ret_df[["ticker", "issuer_clean", "Portfolio Wt", "Price Return", "Contribution"]], use_container_width=True, hide_index=True)

    csv_current = portfolio.to_csv(index=False).encode("utf-8")
    st.download_button("Download current quarter CSV", csv_current, file_name=f"13f_portfolio_{selected_q.replace(' ', '_')}.csv", mime="text/csv")
    if not delta.empty:
        csv_delta = delta.to_csv(index=False).encode("utf-8")
        st.download_button("Download quarter change CSV", csv_delta, file_name=f"13f_delta_{selected_q.replace(' ', '_')}_vs_{prev_q.replace(' ', '_')}.csv", mime="text/csv")

    report_lines = [
        f"13F Dashboard Report - {selected_q}",
        f"Generated view from SEC filing history. Filing date: {filing_date}",
        f"Visible positions: {len(portfolio)}",
        f"Top 10 concentration: {portfolio.head(10)['weight'].sum()*100:.2f}%",
        f"Largest position: {(portfolio.iloc[0]['ticker'] or portfolio.iloc[0]['issuer_clean'])} at {portfolio.iloc[0]['weight']*100:.2f}%",
    ]
    if not delta.empty:
        report_lines.append(recent_manager_activity_summary(delta))
    st.download_button("Download text report", "\n".join(report_lines), file_name=f"13f_report_{selected_q.replace(' ', '_')}.txt", mime="text/plain")

    st.markdown(
        """
        **What this build now includes**  
        - real SEC-backed 13F quarter snapshots  
        - manager search + CIK resolution  
        - disk-backed request caching and SEC-friendly throttling  
        - sector/theme overlays and concentration diagnostics  
        - quarter-to-quarter adds / trims / exits  
        - multi-manager comparison and overlap heatmap  
        - historical weight trends and rank history  
        - optional price-following return layer  
        - CSV and text export  

        **What still remains imperfect**  
        - 13F is delayed and incomplete by design  
        - ticker mapping is best-effort, not a full institutional security master  
        - theme and sector tagging is rules-based rather than vendor-grade taxonomy  
        - return estimates are for convenience, not audit-grade performance attribution  
        """
    )


def main() -> None:
    st.markdown(
        """
        <div class='hero'>
            <h1>13F Holdings Intelligence Dashboard</h1>
            <p>Official SEC 13F snapshots, quarter switching, position treemap, history tracking, manager comparison, and diagnostics in one research UI.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.sidebar:
        manager_name, cik, compare_managers = manager_picker()
        st.header("Portfolio Controls")
        long_only = st.toggle("Exclude put/call option rows", value=True)
        common_stock_only = st.toggle("Common stock only", value=False)
        show_ticker_first = st.toggle("Prefer ticker in labels when mapped", value=True)
        top_n = st.slider("Top holdings table size", min_value=10, max_value=100, value=25, step=5)
        history_default = st.slider("Default history names", min_value=3, max_value=15, value=8, step=1)
        show_full_names = st.toggle("Use full issuer labels in charts", value=True)
        min_weight_filter = st.slider("Minimum position weight shown in treemap (%)", min_value=0.0, max_value=3.0, value=0.0, step=0.1)
        st.markdown("---")
        st.markdown(
            """**Included tools**  
            • SEC-backed manager lookup  
            • Quarter-over-quarter adds / trims / exits  
            • Concentration, sector, and theme diagnostics  
            • Multi-manager comparison + overlap heatmap  
            • Multi-quarter history + rank history + heatmap  
            • Exportable tables and quick report  
            • Optional price-following layer"""
        )

    try:
        quarters = available_quarter_labels(cik)
    except Exception as e:
        st.error(f"Failed to read available 13F filings for CIK {cik}: {e}")
        return
    if not quarters:
        st.warning("No usable 13F-HR filings were found for this CIK. Try another manager or verify the CIK.")
        return

    c1, c2, c3 = st.columns([1.15, 1.15, 0.8])
    with c1:
        selected_q = st.selectbox("Quarter", options=quarters, index=0)
    with c2:
        prev_options = [q for q in quarters if q != selected_q]
        prev_q = st.selectbox("Comparison quarter", options=prev_options, index=min(1, len(prev_options)-1) if prev_options else 0)
    with c3:
        st.button("Refresh")

    try:
        filing, portfolio = load_quarter_portfolio(cik, selected_q, long_only=long_only, common_stock_only=common_stock_only)
        prev_filing, prev_portfolio = load_quarter_portfolio(cik, prev_q, long_only=long_only, common_stock_only=common_stock_only) if prev_q else (None, pd.DataFrame())
    except SecRequestError as e:
        st.error(str(e))
        return
    except Exception as e:
        st.error(f"Unexpected load error: {e}")
        return

    stats = summarize_portfolio(portfolio)
    delta = compare_quarters(portfolio, prev_portfolio) if prev_q and not prev_portfolio.empty else pd.DataFrame()
    official_total_value = stats.get("official_total_value_usd", stats.get("total_value_usd"))

    mc1, mc2, mc3, mc4, mc5, mc6 = st.columns(6)
    with mc1:
        metric_card("Manager", manager_name, f"Current view · CIK {cik}")
    with mc2:
        metric_card("Positions", f"{stats['positions']:,}", "Visible rows after your filters")
    with mc3:
        metric_card("Total Reported Value", fmt_money(official_total_value), "Official SEC filing total")
    with mc4:
        metric_card("Top 10 Concentration", f"{stats['top10_weight']*100:.1f}%", "How much of the book sits in the top ten")
    with mc5:
        metric_card("Largest Position", fmt_pct(portfolio.iloc[0]["weight"]), portfolio.iloc[0].get("ticker") or portfolio.iloc[0]["issuer_clean"])
    with mc6:
        metric_card("Lead Sector", f"{stats['top_sector_weight']*100:.1f}%", stats["top_sector"])

    st.markdown(
        f"<div class='small-note'>Viewing <b>{selected_q}</b> (report period {filing.report_period}; filed {filing.filing_date}). The total reported value above uses the official SEC cover-page total; charts and tables below reflect your current holdings filters. SEC 13F is delayed reporting, so this is a historical snapshot rather than a live portfolio.</div>",
        unsafe_allow_html=True,
    )

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["Overview", "Quarter Changes", "History", "Manager Compare", "Diagnostics & Export"])
    with tab1:
        render_overview(manager_name, portfolio, stats, delta, min_weight_filter, show_ticker_first, show_full_names, top_n)
    with tab2:
        render_changes(selected_q, prev_q, delta)
    with tab3:
        render_history(cik, history_default, common_stock_only, long_only)
    with tab4:
        render_multi_manager(selected_q, compare_managers, manager_name, cik, long_only, common_stock_only)
    with tab5:
        render_diagnostics(selected_q, prev_q, portfolio, delta, filing.filing_date)


if __name__ == "__main__":
    main()
