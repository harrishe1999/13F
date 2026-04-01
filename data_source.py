from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup

from managers import search_local_managers

try:
    import yfinance as yf
except Exception:  # pragma: no cover
    yf = None

USER_AGENT = os.environ.get(
    "SEC_USER_AGENT",
    "13F Dashboard for personal research contact@example.com",
)
BASE_HEADERS = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate", "Host": "www.sec.gov"}
DATA_HEADERS = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate", "Host": "data.sec.gov"}
REQUEST_SLEEP = 0.15
CACHE_DIR = Path(__file__).resolve().parent / ".cache"
CACHE_DIR.mkdir(exist_ok=True)
NETWORK_CACHE_TTL_SECONDS = 60 * 60 * 24


class SecRequestError(RuntimeError):
    pass


@dataclass
class FilingRef:
    accession_nodashes: str
    accession_display: str
    filing_date: str
    report_period: str
    primary_doc: str
    filing_url: str
    official_total_value_usd: float | None = None
    table_entry_total: int | None = None
    value_unit_scale: float | None = None


@dataclass
class CachedResponse:
    status_code: int
    text: str
    url: str

    def json(self):
        return json.loads(self.text)


def _cache_file(url: str) -> Path:
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{key}.json"


def _cache_get(url: str) -> Optional[CachedResponse]:
    path = _cache_file(url)
    if not path.exists():
        return None
    age = time.time() - path.stat().st_mtime
    if age > NETWORK_CACHE_TTL_SECONDS:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return CachedResponse(status_code=payload["status_code"], text=payload["text"], url=url)
    except Exception:
        return None


def _cache_put(url: str, status_code: int, text: str) -> None:
    path = _cache_file(url)
    path.write_text(json.dumps({"status_code": status_code, "text": text}), encoding="utf-8")


def _get(url: str, data_host: bool = False, force_refresh: bool = False) -> CachedResponse:
    if not force_refresh:
        cached = _cache_get(url)
        if cached is not None:
            return cached

    headers = DATA_HEADERS if data_host else BASE_HEADERS
    r = requests.get(url, headers=headers, timeout=30)
    if r.status_code != 200:
        raise SecRequestError(f"SEC request failed [{r.status_code}] for {url}")
    _cache_put(url, r.status_code, r.text)
    time.sleep(REQUEST_SLEEP)
    return CachedResponse(status_code=r.status_code, text=r.text, url=url)


def _parse_numeric_text(value: str | None) -> float | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    cleaned = raw.replace(",", "").replace("$", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _relative_difference(a: float | None, b: float | None) -> float:
    if a in (None, 0) or b in (None, 0):
        return float("inf")
    return abs(a - b) / max(abs(a), abs(b), 1.0)


def _infer_value_unit_scale(raw_total: float | None, official_total: float | None) -> float:
    if raw_total in (None, 0) or official_total in (None, 0):
        return 1000.0

    direct_gap = _relative_difference(raw_total, official_total)
    thousands_gap = _relative_difference(raw_total * 1000.0, official_total)
    if direct_gap <= 0.02 or direct_gap <= thousands_gap:
        return 1.0
    if thousands_gap <= 0.02:
        return 1000.0
    return 1000.0


def normalize_cik(cik: str) -> str:
    digits = re.sub(r"\D", "", cik or "")
    if not digits:
        raise ValueError("CIK is empty.")
    return str(int(digits))


def quarter_end(year: int, quarter: int) -> str:
    month_day = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}
    if quarter not in month_day:
        raise ValueError("Quarter must be 1, 2, 3, or 4.")
    return f"{year}-{month_day[quarter]}"


def quarter_label(year: int, quarter: int) -> str:
    return f"{year} Q{quarter}"


def parse_quarter_label(q: str) -> tuple[int, int]:
    m = re.match(r"^(\d{4})\s*Q([1-4])$", q.strip(), flags=re.I)
    if not m:
        raise ValueError("Quarter label must look like '2025 Q1'.")
    return int(m.group(1)), int(m.group(2))


def _normalize_name(text: str) -> str:
    s = (text or "").upper()
    s = s.replace("&", " AND ")
    replacements = {
        "INCORPORATED": "INC",
        "CORPORATION": "CORP",
        "COMPANY": "CO",
        "LIMITED": "LTD",
        "HOLDINGS": "HLDGS",
        "TECHNOLOGIES": "TECH",
        "TECHNOLOGY": "TECH",
        "INTERNATIONAL": "INTL",
        "GROUP": "GRP",
        "LABORATORIES": "LABS",
        "LABORATORY": "LAB",
    }
    for k, v in replacements.items():
        s = re.sub(rf"\b{k}\b", v, s)
    s = re.sub(r"\bCLASS [A-Z]\b", "", s)
    s = re.sub(r"\bCL [A-Z]\b", "", s)
    s = re.sub(r"\bCOM\b", "", s)
    s = re.sub(r"\bNEW\b", "", s)
    s = re.sub(r"\bORD\b", "", s)
    s = re.sub(r"\bADR\b", "", s)
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


@st.cache_data(ttl=60 * 60 * 12, show_spinner=False)
def get_submissions(cik: str) -> dict:
    cik = normalize_cik(cik)
    url = f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json"
    return _get(url, data_host=True).json()


@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def search_manager_matches(query: str, limit: int = 20) -> pd.DataFrame:
    q = query.strip()
    if not q:
        return search_local_managers("", limit=limit)

    local_df = search_local_managers(q, limit=limit)

    encoded = quote_plus(q)
    url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company={encoded}&owner=exclude&count={max(limit,20)}"
    html = _get(url).text
    soup = BeautifulSoup(html, "html.parser")

    results: list[dict] = []
    seen: set[str] = set(local_df["cik"].astype(str).tolist()) if not local_df.empty else set()

    table = soup.find("table", class_="tableFile2")
    if table is not None:
        header_text = " ".join(th.get_text(" ", strip=True) for th in table.find_all("th"))
        for row in table.find_all("tr")[1:]:
            if "Company" not in header_text:
                break
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            cik_text = cells[0].get_text(" ", strip=True)
            digits = re.sub(r"\D", "", cik_text)
            if not digits:
                continue
            cik = str(int(digits))
            if cik in seen:
                continue

            company_cell = cells[1]
            company_text = company_cell.get_text(" ", strip=True)
            if not company_text or company_text.strip().lower() == "documents":
                continue

            sic_match = re.search(r"SIC:\s*([0-9]{4})", company_text, flags=re.I)
            company_text = re.sub(r"SIC:\s*[0-9]{4}\s*-\s*.*$", "", company_text, flags=re.I).strip()
            location = cells[2].get_text(" ", strip=True) if len(cells) > 2 else ""

            seen.add(cik)
            results.append(
                {
                    "manager_id": "",
                    "name": company_text,
                    "display_name": company_text,
                    "cik": cik,
                    "location": location,
                    "sic": sic_match.group(1) if sic_match else "",
                    "source": "sec",
                    "score": 0.75,
                    "match_stage": 5,
                    "popular": False,
                }
            )

    sec_df = pd.DataFrame(results)
    if local_df.empty and sec_df.empty:
        return pd.DataFrame(columns=["manager_id", "name", "display_name", "cik", "location", "sic", "source", "score", "match_stage", "popular"])
    if local_df.empty:
        return sec_df.head(limit).reset_index(drop=True)
    if sec_df.empty:
        return local_df.head(limit).reset_index(drop=True)

    combined = pd.concat([local_df, sec_df], ignore_index=True)
    combined["score"] = pd.to_numeric(combined["score"], errors="coerce").fillna(0.0)
    combined["match_stage"] = pd.to_numeric(combined["match_stage"], errors="coerce").fillna(99).astype(int)
    combined["popular"] = combined["popular"].fillna(False)
    combined = combined.sort_values(["match_stage", "score", "popular", "name"], ascending=[True, False, False, True])
    return combined.drop_duplicates(subset=["cik"]).head(limit).reset_index(drop=True)


def list_13f_filings(cik: str) -> pd.DataFrame:
    sub = get_submissions(cik)
    recent = sub.get("filings", {}).get("recent", {})
    if not recent:
        return pd.DataFrame()
    df = pd.DataFrame(recent)
    if df.empty:
        return df
    forms = {"13F-HR", "13F-HR/A", "13F-NT", "13F-NT/A"}
    df = df[df["form"].isin(forms)].copy()
    if df.empty:
        return df
    df["reportDate"] = df.get("reportDate")
    df["filingDate"] = pd.to_datetime(df["filingDate"], errors="coerce")
    df = df.sort_values(["reportDate", "filingDate"], ascending=[False, False])
    return df.reset_index(drop=True)


def find_filing_for_quarter(cik: str, year: int, quarter: int) -> Optional[FilingRef]:
    q_end = quarter_end(year, quarter)
    df = list_13f_filings(cik)
    if df.empty:
        return None
    candidates = df[(df["form"].isin(["13F-HR", "13F-HR/A"])) & (df["reportDate"] == q_end)].copy()
    if candidates.empty:
        candidates = df[df["reportDate"].astype(str).str.startswith(q_end)].copy()
    if candidates.empty:
        return None
    row = candidates.iloc[0]
    accession_display = row["accessionNumber"]
    accession_nodashes = accession_display.replace("-", "")
    cik_norm = normalize_cik(cik)
    primary_doc = row.get("primaryDocument", "") or ""
    filing_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik_norm)}/{accession_nodashes}/"
    return FilingRef(
        accession_nodashes=accession_nodashes,
        accession_display=accession_display,
        filing_date=str(row["filingDate"].date()) if pd.notna(row["filingDate"]) else "",
        report_period=q_end,
        primary_doc=primary_doc,
        filing_url=filing_url,
    )


@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def get_filing_index_xml(cik: str, accession_nodashes: str) -> str:
    cik_norm = normalize_cik(cik)
    url = f"https://www.sec.gov/Archives/edgar/data/{int(cik_norm)}/{accession_nodashes}/index.xml"
    return _get(url).text


def list_information_table_candidates(cik: str, accession_nodashes: str) -> list[str]:
    xml_text = get_filing_index_xml(cik, accession_nodashes)
    soup = BeautifulSoup(xml_text, "xml")
    names: list[tuple[str, int]] = []
    for item in soup.find_all(["file", "item"]):
        name_node = item.find("name")
        if name_node and name_node.text:
            size_node = item.find("size")
            try:
                size_value = int((size_node.text or "0").strip()) if size_node is not None else 0
            except ValueError:
                size_value = 0
            names.append((name_node.text.strip(), size_value))

    def sort_key(item: tuple[str, int]) -> tuple[int, int, str]:
        filename, size_value = item
        lower = filename.lower()
        is_xml = lower.endswith(".xml")
        explicit_info = any(k in lower for k in ["infotable", "informationtable", "form13finfo", "13finfo"])
        is_primary = "primary_doc" in lower
        numeric_name = bool(re.fullmatch(r"[0-9]+\.xml", lower))
        return (
            1 if explicit_info else 0,
            1 if numeric_name else 0,
            0 if is_primary else 1,
            size_value,
            filename,
        ) if is_xml else (-1, -1, -1, -1, filename)

    candidates = [name for name, _ in sorted(names, key=sort_key, reverse=True) if name.lower().endswith(".xml")]
    return candidates


def discover_information_table_filename(cik: str, accession_nodashes: str) -> Optional[str]:
    candidates = list_information_table_candidates(cik, accession_nodashes)
    return candidates[0] if candidates else None


@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def get_primary_doc_xml(cik: str, accession_nodashes: str, primary_doc: str = "") -> str:
    cik_norm = normalize_cik(cik)
    candidates = ["primary_doc.xml", primary_doc]
    tried: list[str] = []
    for candidate in candidates:
        name = str(candidate or "").strip().lstrip("/")
        if not name or name in tried:
            continue
        tried.append(name)
        url = f"https://www.sec.gov/Archives/edgar/data/{int(cik_norm)}/{accession_nodashes}/{name}"
        try:
            return _get(url).text
        except SecRequestError:
            continue
    raise SecRequestError("Could not locate the filing cover-page XML.")


def parse_filing_cover_metadata(xml_text: str) -> dict[str, float | int | None]:
    soup = BeautifulSoup(xml_text, "xml")

    def read_tag(tag_name: str) -> float | None:
        node = soup.find(lambda tag: tag.name and tag.name.lower().endswith(tag_name.lower()))
        return _parse_numeric_text(node.text if node and node.text is not None else None)

    total_value = read_tag("tableValueTotal")
    entry_total = read_tag("tableEntryTotal")
    return {
        "official_total_value_usd": total_value,
        "table_entry_total": int(entry_total) if entry_total is not None else None,
    }


@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def get_filing_cover_metadata(cik: str, accession_nodashes: str, primary_doc: str = "") -> dict[str, float | int | None]:
    tried_xml: list[str] = []
    for candidate in ["primary_doc.xml", primary_doc]:
        name = str(candidate or "").strip()
        if not name or name in tried_xml:
            continue
        tried_xml.append(name)
        try:
            xml_text = get_primary_doc_xml(cik, accession_nodashes, primary_doc=name)
        except SecRequestError:
            continue
        metadata = parse_filing_cover_metadata(xml_text)
        if metadata.get("official_total_value_usd") is not None or metadata.get("table_entry_total") is not None:
            return metadata
    return {"official_total_value_usd": None, "table_entry_total": None}


@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def load_information_table(cik: str, accession_nodashes: str, primary_doc: str = "") -> pd.DataFrame:
    filenames = list_information_table_candidates(cik, accession_nodashes)
    if not filenames:
        raise SecRequestError("Could not locate 13F information table XML in the filing directory.")
    cik_norm = normalize_cik(cik)
    cover_meta = get_filing_cover_metadata(cik, accession_nodashes, primary_doc=primary_doc)
    errors = []
    for filename in filenames:
        url = f"https://www.sec.gov/Archives/edgar/data/{int(cik_norm)}/{accession_nodashes}/{filename}"
        xml_text = _get(url).text
        try:
            df = parse_13f_xml(xml_text)
            raw_total = float(df["value_reported"].fillna(0).sum())
            scale = _infer_value_unit_scale(raw_total, cover_meta.get("official_total_value_usd"))
            df["value_unit_scale"] = scale
            df["market_value_usd"] = df["value_reported"].fillna(0) * scale
            df["official_total_value_usd"] = cover_meta.get("official_total_value_usd")
            df["table_entry_total"] = cover_meta.get("table_entry_total")
            df["source_filename"] = filename
            return df
        except SecRequestError as exc:
            errors.append(f"{filename}: {exc}")
            continue
    raise SecRequestError(
        "Could not parse a valid 13F holdings XML from the filing directory. "
        f"Tried: {', '.join(errors[:5])}"
    )


def parse_13f_xml(xml_text: str) -> pd.DataFrame:
    soup = BeautifulSoup(xml_text, "xml")
    rows = []
    for info in soup.find_all(lambda tag: tag.name and tag.name.lower().endswith("infotable")):
        def text(path: str) -> str:
            node = info.find(lambda tag: tag.name and tag.name.lower() == path.lower())
            return node.text.strip() if node and node.text is not None else ""

        def nested_text(parent_name: str, child_name: str) -> str:
            parent = info.find(lambda tag: tag.name and tag.name.lower() == parent_name.lower())
            if parent is None:
                return ""
            child = parent.find(lambda tag: tag.name and tag.name.lower() == child_name.lower())
            return child.text.strip() if child and child.text is not None else ""

        rows.append(
            {
                "issuer": text("nameOfIssuer"),
                "title_class": text("titleOfClass"),
                "cusip": text("cusip"),
                "value_reported": pd.to_numeric(text("value"), errors="coerce"),
                "shares": pd.to_numeric(text("sshPrnamt"), errors="coerce"),
                "share_type": text("sshPrnamtType"),
                "put_call": text("putCall"),
                "investment_discretion": text("investmentDiscretion"),
                "other_managers": text("otherManager"),
                "voting_sole": pd.to_numeric(nested_text("votingAuthority", "Sole"), errors="coerce"),
                "voting_shared": pd.to_numeric(nested_text("votingAuthority", "Shared"), errors="coerce"),
                "voting_none": pd.to_numeric(nested_text("votingAuthority", "None"), errors="coerce"),
            }
        )
    df = pd.DataFrame(rows)
    if df.empty:
        raise SecRequestError("13F XML parsed but no holdings rows were found.")
    df["market_value_usd"] = df["value_reported"].fillna(0)
    df["issuer_clean"] = df["issuer"].str.replace(r"\s+", " ", regex=True).str.strip()
    return df


@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def get_company_tickers_exchange() -> pd.DataFrame:
    url = "https://www.sec.gov/files/company_tickers_exchange.json"
    payload = _get(url).json()
    records = payload.get("data", [])
    fields = payload.get("fields", [])
    if not records or not fields:
        return pd.DataFrame(columns=["cik", "name", "ticker", "exchange", "name_norm"])
    df = pd.DataFrame(records, columns=fields)
    rename_map = {}
    for col in df.columns:
        low = str(col).lower()
        if low == "cik":
            rename_map[col] = "cik"
        elif low in {"name", "title"}:
            rename_map[col] = "name"
        elif low == "ticker":
            rename_map[col] = "ticker"
        elif low == "exchange":
            rename_map[col] = "exchange"
    df = df.rename(columns=rename_map)
    for col in ["cik", "name", "ticker", "exchange"]:
        if col not in df.columns:
            df[col] = ""
    df = df[["cik", "name", "ticker", "exchange"]].copy()
    df["name_norm"] = df["name"].map(_normalize_name)
    return df.drop_duplicates(subset=["name_norm", "ticker"]).reset_index(drop=True)


@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def get_ticker_lookup() -> dict[str, list[dict[str, str]]]:
    df = get_company_tickers_exchange()
    mapping: dict[str, list[dict[str, str]]] = {}
    for _, row in df.iterrows():
        norm = row["name_norm"]
        if norm:
            mapping.setdefault(norm, []).append(
                {
                    "ticker": str(row["ticker"] or "").upper(),
                    "exchange": str(row["exchange"] or ""),
                    "name": str(row["name"] or ""),
                }
            )
    return mapping


def _best_ticker_match(name_norm: str, lookup: dict[str, list[dict[str, str]]]) -> tuple[str, str, float]:
    if not name_norm:
        return "", "", 0.0
    direct = lookup.get(name_norm)
    if direct:
        best = direct[0]
        return best["ticker"], best["exchange"], 1.0

    candidates: list[tuple[float, str, str]] = []
    prefix = name_norm[:8]
    for key, values in lookup.items():
        if prefix and prefix in key[:12]:
            ratio = SequenceMatcher(None, name_norm, key).ratio()
            if ratio >= 0.84:
                candidates.append((ratio, values[0]["ticker"], values[0]["exchange"]))
    if not candidates:
        for key, values in lookup.items():
            ratio = SequenceMatcher(None, name_norm, key).ratio()
            if ratio >= 0.92:
                candidates.append((ratio, values[0]["ticker"], values[0]["exchange"]))
    if not candidates:
        return "", "", 0.0
    candidates.sort(reverse=True)
    best = candidates[0]
    return best[1], best[2], float(best[0])


SECTOR_RULES = {
    "Semiconductors": {"NVDA", "AMD", "AVGO", "TSM", "QCOM", "MU", "MRVL", "INTC", "ASML", "ARM"},
    "Software & Internet": {"MSFT", "GOOGL", "META", "AMZN", "NFLX", "CRM", "ADBE", "ORCL", "UBER", "SHOP"},
    "Consumer": {"AAPL", "COST", "WMT", "MCD", "SBUX", "NKE", "TSLA", "HD", "LOW"},
    "Financials": {"BRK.B", "JPM", "BAC", "GS", "MS", "AXP", "C", "SCHW", "BK", "BLK", "SPGI", "V", "MA"},
    "Healthcare": {"LLY", "JNJ", "PFE", "MRK", "ABBV", "UNH", "ISRG", "TMO", "DHR", "AMGN"},
    "Energy & Materials": {"XOM", "CVX", "COP", "SLB", "CAT", "FCX"},
}

THEME_RULES = {
    "AI": {"NVDA", "AMD", "MSFT", "GOOGL", "META", "AMZN", "AVGO", "TSM", "ARM", "MRVL", "ASML"},
    "Big Tech": {"AAPL", "MSFT", "GOOGL", "META", "AMZN", "NFLX", "NVDA", "TSLA"},
    "Financial Services": {"JPM", "BAC", "GS", "MS", "AXP", "V", "MA", "SPGI", "BLK"},
    "China ADR": {"BABA", "JD", "PDD", "BIDU", "NTES", "BEKE", "TME"},
    "Consumer Staples": {"COST", "WMT", "KO", "PEP", "PG"},
}


def infer_sector_and_themes(ticker: str, issuer_clean: str) -> tuple[str, str]:
    tick = str(ticker or "").upper()
    issuer = str(issuer_clean or "").upper()
    sector = "Other"
    for name, tickers in SECTOR_RULES.items():
        if tick in tickers:
            sector = name
            break
    if sector == "Other":
        if any(k in issuer for k in ["BANK", "CAPITAL", "FINANCIAL", "PAYMENTS"]):
            sector = "Financials"
        elif any(k in issuer for k in ["PHARMA", "HEALTH", "BIO", "THERAPEUTICS", "MEDICAL"]):
            sector = "Healthcare"
        elif any(k in issuer for k in ["SEMICONDUCTOR", "MICRO", "CHIP", "TECH"]):
            sector = "Semiconductors"
        elif any(k in issuer for k in ["SOFTWARE", "INTERNET", "DIGITAL", "PLATFORM"]):
            sector = "Software & Internet"
        elif any(k in issuer for k in ["ENERGY", "OIL", "GAS", "MINING"]):
            sector = "Energy & Materials"
        elif any(k in issuer for k in ["RETAIL", "APPAREL", "FOODS", "BEVERAGE", "AUTO"]):
            sector = "Consumer"
    matched_themes = [name for name, tickers in THEME_RULES.items() if tick in tickers]
    return sector, ", ".join(matched_themes)


def attach_tickers(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    lookup = get_ticker_lookup()
    norms = out["issuer_clean"].fillna("").map(_normalize_name)
    tickers: list[str] = []
    exchanges: list[str] = []
    scores: list[float] = []
    sectors: list[str] = []
    themes: list[str] = []
    for issuer_clean, norm in zip(out["issuer_clean"].fillna(""), norms):
        t, ex, s = _best_ticker_match(norm, lookup)
        tickers.append(t)
        exchanges.append(ex)
        scores.append(s)
        sector, theme = infer_sector_and_themes(t, issuer_clean)
        sectors.append(sector)
        themes.append(theme)
    out["ticker"] = tickers
    out["exchange"] = exchanges
    out["ticker_match_score"] = scores
    out["sector"] = sectors
    out["themes"] = themes
    out["display_name"] = out.apply(
        lambda r: f"{r['ticker']} - {r['issuer_clean']}" if str(r.get("ticker", "")).strip() else r["issuer_clean"],
        axis=1,
    )
    return out


def enrich_with_weights(df: pd.DataFrame, long_only: bool = True, common_stock_only: bool = False) -> pd.DataFrame:
    out = df.copy()
    if long_only:
        out = out[out["put_call"].fillna("").eq("")].copy()
    if common_stock_only:
        out = out[out["title_class"].str.contains("COM", case=False, na=False)].copy()
    total = out["market_value_usd"].sum()
    out["weight"] = out["market_value_usd"] / total if total else 0.0
    out = attach_tickers(out)
    out = out.sort_values("weight", ascending=False).reset_index(drop=True)
    out["label"] = out["display_name"]
    return out


def summarize_portfolio(df: pd.DataFrame) -> dict:
    filtered_total = float(df["market_value_usd"].sum()) if not df.empty else 0.0
    official_total = filtered_total
    table_entry_total = int(len(df)) if not df.empty else 0
    value_unit_scale = 1000.0
    if not df.empty:
        official_series = pd.to_numeric(df.get("official_total_value_usd"), errors="coerce") if "official_total_value_usd" in df.columns else pd.Series(dtype=float)
        entry_series = pd.to_numeric(df.get("table_entry_total"), errors="coerce") if "table_entry_total" in df.columns else pd.Series(dtype=float)
        scale_series = pd.to_numeric(df.get("value_unit_scale"), errors="coerce") if "value_unit_scale" in df.columns else pd.Series(dtype=float)
        if not official_series.dropna().empty:
            official_total = float(official_series.dropna().iloc[0])
        if not entry_series.dropna().empty:
            table_entry_total = int(entry_series.dropna().iloc[0])
        if not scale_series.dropna().empty:
            value_unit_scale = float(scale_series.dropna().iloc[0])
    top10 = float(df.head(10)["weight"].sum()) if not df.empty else 0.0
    hhi = float((df["weight"].fillna(0) ** 2).sum()) if not df.empty else 0.0
    mapped = int(df["ticker"].fillna("").astype(str).str.len().gt(0).sum()) if not df.empty else 0
    sector_weights = df.groupby("sector", dropna=False)["weight"].sum().sort_values(ascending=False) if not df.empty else pd.Series(dtype=float)
    return {
        "positions": int(len(df)),
        "total_value_usd": filtered_total,
        "filtered_total_value_usd": filtered_total,
        "official_total_value_usd": official_total,
        "table_entry_total": table_entry_total,
        "value_unit_scale": value_unit_scale,
        "top10_weight": top10,
        "hhi": hhi,
        "mapped_tickers": mapped,
        "ticker_coverage": (mapped / len(df)) if len(df) else 0.0,
        "top_sector": sector_weights.index[0] if not sector_weights.empty else "N/A",
        "top_sector_weight": float(sector_weights.iloc[0]) if not sector_weights.empty else 0.0,
    }


def build_history(cik: str, common_stock_only: bool = False, long_only: bool = True) -> pd.DataFrame:
    filings = list_13f_filings(cik)
    filings = filings[filings["form"].isin(["13F-HR", "13F-HR/A"])].copy()
    histories = []
    for _, row in filings.iterrows():
        report_date = row.get("reportDate")
        accession = str(row["accessionNumber"]).replace("-", "")
        try:
            holdings = load_information_table(cik, accession, primary_doc=str(row.get("primaryDocument", "") or ""))
            holdings = enrich_with_weights(holdings, long_only=long_only, common_stock_only=common_stock_only)
            holdings["report_date"] = report_date
            holdings["filing_date"] = row.get("filingDate")
            holdings["accession_number"] = row.get("accessionNumber")
            histories.append(
                holdings[
                    [
                        "report_date",
                        "filing_date",
                        "accession_number",
                        "issuer_clean",
                        "ticker",
                        "exchange",
                        "sector",
                        "themes",
                        "cusip",
                        "title_class",
                        "put_call",
                        "market_value_usd",
                        "weight",
                    ]
                ]
            )
        except Exception:
            continue
    if not histories:
        return pd.DataFrame()
    hist = pd.concat(histories, ignore_index=True)
    hist["report_date"] = pd.to_datetime(hist["report_date"], errors="coerce")
    hist = hist.sort_values(["report_date", "weight"], ascending=[True, False]).reset_index(drop=True)
    return hist


def compare_quarters(current_df: pd.DataFrame, previous_df: pd.DataFrame) -> pd.DataFrame:
    curr = current_df[["issuer_clean", "ticker", "cusip", "market_value_usd", "weight", "sector", "themes"]].rename(
        columns={"market_value_usd": "mv_curr", "weight": "w_curr", "ticker": "ticker_curr"}
    )
    prev = previous_df[["issuer_clean", "ticker", "cusip", "market_value_usd", "weight"]].rename(
        columns={"market_value_usd": "mv_prev", "weight": "w_prev", "ticker": "ticker_prev"}
    )
    merged = curr.merge(prev, on=["issuer_clean", "cusip"], how="outer")
    merged[["mv_curr", "w_curr", "mv_prev", "w_prev"]] = merged[["mv_curr", "w_curr", "mv_prev", "w_prev"]].fillna(0)
    merged["ticker"] = merged["ticker_curr"].fillna(merged["ticker_prev"]).fillna("")
    merged["weight_change_pct_pt"] = (merged["w_curr"] - merged["w_prev"]) * 100
    merged["value_change_usd"] = merged["mv_curr"] - merged["mv_prev"]
    merged["relative_weight_change_pct"] = ((merged["w_curr"] - merged["w_prev"]) / merged["w_prev"].replace(0, pd.NA)) * 100

    def classify(r: pd.Series) -> str:
        if r["mv_prev"] == 0 and r["mv_curr"] > 0:
            return "New"
        if r["mv_prev"] > 0 and r["mv_curr"] == 0:
            return "Exited"
        if r["weight_change_pct_pt"] > 0.05:
            return "Added"
        if r["weight_change_pct_pt"] < -0.05:
            return "Trimmed"
        return "Stable"

    merged["change_type"] = merged.apply(classify, axis=1)
    return merged.sort_values("weight_change_pct_pt", ascending=False).reset_index(drop=True)


def available_quarter_labels(cik: str) -> list[str]:
    df = list_13f_filings(cik)
    if df.empty:
        return []
    labels = []
    for rd in df["reportDate"].dropna().astype(str).tolist():
        if re.match(r"^\d{4}-\d{2}-\d{2}$", rd):
            y = int(rd[:4])
            q = {"03-31": 1, "06-30": 2, "09-30": 3, "12-31": 4}.get(rd[5:])
            if q:
                labels.append(quarter_label(y, q))
    unique = []
    seen = set()
    for x in labels:
        if x not in seen:
            seen.add(x)
            unique.append(x)
    return unique


@st.cache_data(ttl=60 * 60 * 12, show_spinner=False)
def load_quarter_portfolio(cik: str, quarter_str: str, long_only: bool = True, common_stock_only: bool = False):
    year, quarter = parse_quarter_label(quarter_str)
    filing = find_filing_for_quarter(cik, year, quarter)
    if filing is None:
        raise SecRequestError(f"No 13F-HR filing found for {quarter_str}.")
    df = load_information_table(cik, filing.accession_nodashes, primary_doc=filing.primary_doc)
    df = enrich_with_weights(df, long_only=long_only, common_stock_only=common_stock_only)
    if not df.empty:
        stats = summarize_portfolio(df)
        filing.official_total_value_usd = stats["official_total_value_usd"]
        filing.table_entry_total = stats["table_entry_total"]
        filing.value_unit_scale = stats["value_unit_scale"]
    return filing, df


def sector_breakdown(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["sector", "weight", "market_value_usd"])
    out = df.groupby("sector", dropna=False)[["weight", "market_value_usd"]].sum().reset_index()
    return out.sort_values("weight", ascending=False).reset_index(drop=True)


def theme_breakdown(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["theme", "weight"])
    rows = []
    for _, row in df.iterrows():
        raw = str(row.get("themes") or "")
        if not raw.strip():
            continue
        for item in [x.strip() for x in raw.split(",") if x.strip()]:
            rows.append({"theme": item, "weight": row["weight"], "market_value_usd": row["market_value_usd"]})
    if not rows:
        return pd.DataFrame(columns=["theme", "weight", "market_value_usd"])
    out = pd.DataFrame(rows).groupby("theme")[["weight", "market_value_usd"]].sum().reset_index()
    return out.sort_values("weight", ascending=False).reset_index(drop=True)


def build_multi_manager_snapshot(cik_map: dict[str, str], quarter_str: str, long_only: bool = True, common_stock_only: bool = False) -> pd.DataFrame:
    rows = []
    for manager_name, cik in cik_map.items():
        try:
            filing, pf = load_quarter_portfolio(cik, quarter_str, long_only=long_only, common_stock_only=common_stock_only)
            stats = summarize_portfolio(pf)
            top = pf.iloc[0] if not pf.empty else None
            rows.append(
                {
                    "manager": manager_name,
                    "cik": cik,
                    "quarter": quarter_str,
                    "report_period": filing.report_period,
                    "positions": stats["positions"],
                    "top10_weight": stats["top10_weight"],
                    "hhi": stats["hhi"],
                    "top_sector": stats["top_sector"],
                    "top_sector_weight": stats["top_sector_weight"],
                    "largest_position": (top.get("ticker") or top["issuer_clean"]) if top is not None else "",
                    "largest_position_weight": float(top["weight"]) if top is not None else 0.0,
                    "total_value_usd": stats["official_total_value_usd"],
                }
            )
        except Exception:
            continue
    return pd.DataFrame(rows).sort_values("total_value_usd", ascending=False).reset_index(drop=True) if rows else pd.DataFrame()


def overlap_matrix(cik_map: dict[str, str], quarter_str: str, long_only: bool = True, common_stock_only: bool = False, top_n: int = 20) -> pd.DataFrame:
    manager_sets: dict[str, set[str]] = {}
    for manager_name, cik in cik_map.items():
        try:
            _, pf = load_quarter_portfolio(cik, quarter_str, long_only=long_only, common_stock_only=common_stock_only)
            ids = pf.head(top_n).apply(lambda r: r["ticker"] if str(r["ticker"]).strip() else f"{r['issuer_clean']}|{r['cusip']}", axis=1)
            manager_sets[manager_name] = set(ids.tolist())
        except Exception:
            continue
    if not manager_sets:
        return pd.DataFrame()
    names = list(manager_sets.keys())
    data = []
    for a in names:
        row = {"manager": a}
        for b in names:
            denom = max(len(manager_sets[a]), 1)
            row[b] = len(manager_sets[a].intersection(manager_sets[b])) / denom
        data.append(row)
    return pd.DataFrame(data).set_index("manager")


def recent_manager_activity_summary(delta: pd.DataFrame) -> str:
    if delta.empty:
        return "No quarter-over-quarter delta was available for this comparison."
    new_count = int((delta["change_type"] == "New").sum())
    exit_count = int((delta["change_type"] == "Exited").sum())
    added_names = delta[delta["change_type"].isin(["New", "Added"])].head(3)
    trimmed_names = delta[delta["change_type"].isin(["Trimmed", "Exited"])].sort_values("weight_change_pct_pt").head(3)
    adds = ", ".join([(r["ticker"] or r["issuer_clean"]) for _, r in added_names.iterrows()]) or "none"
    trims = ", ".join([(r["ticker"] or r["issuer_clean"]) for _, r in trimmed_names.iterrows()]) or "none"
    return (
        f"Opened {new_count} new positions and exited {exit_count}. "
        f"Most notable positive swings: {adds}. Most notable negative swings: {trims}."
    )


def estimate_following_returns(df: pd.DataFrame, start_date: str, end_date: Optional[str] = None, top_n: int = 15) -> pd.DataFrame:
    if yf is None or df.empty:
        return pd.DataFrame()
    end = end_date or datetime.utcnow().strftime("%Y-%m-%d")
    subset = df[df["ticker"].fillna("").ne("")].head(top_n).copy()
    rows = []
    for _, row in subset.iterrows():
        ticker = row["ticker"]
        try:
            prices = yf.download(ticker, start=start_date, end=(pd.to_datetime(end) + timedelta(days=1)).strftime("%Y-%m-%d"), progress=False, auto_adjust=True)
            if prices.empty or "Close" not in prices:
                continue
            first = float(prices["Close"].dropna().iloc[0])
            last = float(prices["Close"].dropna().iloc[-1])
            ret = (last / first) - 1 if first else None
            rows.append(
                {
                    "ticker": ticker,
                    "issuer_clean": row["issuer_clean"],
                    "portfolio_weight": row["weight"],
                    "start_price": first,
                    "end_price": last,
                    "price_return": ret,
                    "weighted_contribution": (ret * row["weight"]) if ret is not None else None,
                }
            )
        except Exception:
            continue
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows).sort_values("weighted_contribution", ascending=False).reset_index(drop=True)
    return out
