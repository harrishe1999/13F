from __future__ import annotations

import re
from difflib import SequenceMatcher

import pandas as pd

MANAGER_DATABASE = [
    {
        "id": "berkshire_hathaway",
        "name": "Berkshire Hathaway",
        "display": "Berkshire Hathaway Inc.",
        "cik": "1067983",
        "aliases": ["Berkshire Hathaway", "Berkshire Hathaway Inc", "Berkshire"],
        "popular": True,
    },
    {
        "id": "bridgewater_associates",
        "name": "Bridgewater Associates",
        "display": "Bridgewater Associates, LP",
        "cik": "1350694",
        "aliases": ["Bridgewater Associates", "Bridgewater Associates LP", "Bridgewater"],
        "popular": True,
    },
    {
        "id": "scion_asset_management",
        "name": "Scion Asset Management",
        "display": "Scion Asset Management, LLC",
        "cik": "1649339",
        "aliases": ["Scion Asset Management", "Scion Asset Management LLC", "Scion"],
        "popular": True,
    },
    {
        "id": "pershing_square_capital",
        "name": "Pershing Square Capital",
        "display": "Pershing Square Capital Management, L.P.",
        "cik": "1336528",
        "aliases": ["Pershing Square Capital", "Pershing Square", "Pershing Square Capital Management", "Pershing"],
        "popular": True,
    },
    {
        "id": "hh_international",
        "name": "H&H International",
        "display": "H&H International Investment, LLC",
        "cik": "1759760",
        "aliases": [
            "H&H International",
            "H & H International",
            "H&H International Investment",
            "H&H International Investment LLC",
            "HH International",
            "Duan Yongping",
        ],
        "popular": True,
    },
    {
        "id": "duquesne_family_office",
        "name": "Duquesne Family Office",
        "display": "Duquesne Family Office LLC",
        "cik": "1536411",
        "aliases": ["Duquesne Family Office", "Duquesne Family Office LLC", "Duquesne"],
        "popular": True,
    },
    {
        "id": "tiger_global_management",
        "name": "Tiger Global Management",
        "display": "Tiger Global Management, LLC",
        "cik": "1167483",
        "aliases": ["Tiger Global Management", "Tiger Global Management LLC", "Tiger Global"],
        "popular": True,
    },
    {
        "id": "appaloosa_management",
        "name": "Appaloosa Management",
        "display": "Appaloosa LP",
        "cik": "1006438",
        "aliases": ["Appaloosa Management", "Appaloosa LP", "Appaloosa"],
        "popular": True,
    },
    {
        "id": "greenlight_capital",
        "name": "Greenlight Capital",
        "display": "Greenlight Capital, Inc.",
        "cik": "1079114",
        "aliases": ["Greenlight Capital", "Greenlight Capital Inc", "Greenlight"],
        "popular": True,
    },
    {
        "id": "third_point",
        "name": "Third Point",
        "display": "Third Point LLC",
        "cik": "1040273",
        "aliases": ["Third Point", "Third Point LLC"],
        "popular": True,
    },
    {
        "id": "soros_fund_management",
        "name": "Soros Fund Management",
        "display": "Soros Fund Management LLC",
        "cik": "1029160",
        "aliases": ["Soros Fund Management", "Soros Fund Management LLC", "Soros"],
        "popular": True,
    },
    {
        "id": "gates_foundation_trust",
        "name": "Bill & Melinda Gates Foundation Trust",
        "display": "Bill & Melinda Gates Foundation Trust",
        "cik": "1166559",
        "aliases": ["Bill & Melinda Gates Foundation Trust", "Gates Foundation Trust", "Gates Foundation"],
        "popular": True,
    },
    {
        "id": "coatue_management",
        "name": "Coatue Management",
        "display": "Coatue Management LLC",
        "cik": "1761774",
        "aliases": ["Coatue Management", "Coatue Management LLC", "Coatue"],
        "popular": True,
    },
    {
        "id": "viking_global_investors",
        "name": "Viking Global Investors",
        "display": "Viking Global Investors LP",
        "cik": "1103804",
        "aliases": ["Viking Global Investors", "Viking Global Investors LP", "Viking Global", "Viking"],
        "popular": True,
    },
    {
        "id": "baupost_group",
        "name": "Baupost Group",
        "display": "The Baupost Group, L.L.C.",
        "cik": "1061768",
        "aliases": ["Baupost Group", "The Baupost Group", "Baupost"],
        "popular": True,
    },
    {
        "id": "de_shaw",
        "name": "D. E. Shaw",
        "display": "D. E. Shaw & Co., L.P.",
        "cik": "1009207",
        "aliases": ["D. E. Shaw", "DE Shaw", "D E Shaw", "D. E. Shaw & Co.", "DEShaw"],
        "popular": True,
    },
    {
        "id": "renaissance_technologies",
        "name": "Renaissance Technologies",
        "display": "Renaissance Technologies LLC",
        "cik": "1037389",
        "aliases": ["Renaissance Technologies", "Renaissance Technologies LLC", "Renaissance"],
        "popular": True,
    },
    {
        "id": "citadel_advisors",
        "name": "Citadel Advisors",
        "display": "Citadel Advisors LLC",
        "cik": "1423053",
        "aliases": ["Citadel Advisors", "Citadel Advisors LLC", "Citadel"],
        "popular": True,
    },
    {
        "id": "point72_asset_management",
        "name": "Point72 Asset Management",
        "display": "Point72 Asset Management, L.P.",
        "cik": "1599882",
        "aliases": ["Point72 Asset Management", "Point72 Asset Management LP", "Point72"],
        "popular": True,
    },
    {
        "id": "maverick_capital",
        "name": "Maverick Capital",
        "display": "Maverick Capital, Ltd.",
        "cik": "0928616",
        "aliases": ["Maverick Capital", "Maverick Capital Ltd", "Maverick"],
        "popular": True,
    },
    {
        "id": "jana_partners",
        "name": "JANA Partners",
        "display": "JANA Partners LLC",
        "cik": "1034842",
        "aliases": ["JANA Partners", "JANA Partners LLC", "Jana Partners", "JANA"],
        "popular": True,
    },
]

MANAGER_BY_ID = {manager["id"]: manager for manager in MANAGER_DATABASE}
POPULAR_MANAGER_IDS = [manager["id"] for manager in MANAGER_DATABASE if manager["popular"]]
POPULAR_MANAGER_LOOKUP = {manager["name"]: {"cik": manager["cik"], "display": manager["display"]} for manager in MANAGER_DATABASE if manager["popular"]}


def _normalize_manager_text(text: str) -> str:
    cleaned = re.sub(r"[^A-Z0-9]+", " ", (text or "").upper())
    return re.sub(r"\s+", " ", cleaned).strip()


def get_manager_record(manager_id: str) -> dict | None:
    return MANAGER_BY_ID.get(manager_id)


def popular_manager_options() -> pd.DataFrame:
    rows = []
    for manager_id in POPULAR_MANAGER_IDS:
        manager = MANAGER_BY_ID[manager_id]
        rows.append(
            {
                "manager_id": manager["id"],
                "name": manager["name"],
                "display_name": manager["display"],
                "cik": manager["cik"],
                "location": "",
                "sic": "",
                "source": "curated",
                "score": 1.0,
                "popular": True,
            }
        )
    return pd.DataFrame(rows)


def search_local_managers(query: str, limit: int = 20) -> pd.DataFrame:
    q = _normalize_manager_text(query)
    if not q:
        return popular_manager_options().head(limit).reset_index(drop=True)

    q_tokens = set(q.split())
    rows = []
    for manager in MANAGER_DATABASE:
        names = [manager["name"], manager["display"], *manager.get("aliases", [])]
        best_stage = 99
        best_score = 0.0
        for candidate in names:
            norm = _normalize_manager_text(candidate)
            if not norm:
                continue
            if norm == q:
                stage, score = 0, 1.0
            elif norm.startswith(q):
                stage, score = 1, 0.985
            elif q in norm:
                stage, score = 3, 0.94
            else:
                ratio = SequenceMatcher(None, q, norm).ratio()
                overlap = len(q_tokens.intersection(set(norm.split()))) / max(len(q_tokens), 1)
                score = max(ratio * 0.82 + overlap * 0.18, overlap * 0.9)
                stage = 4
            is_alias = norm != _normalize_manager_text(manager["name"]) and norm != _normalize_manager_text(manager["display"])
            if is_alias and stage < 4:
                stage = 2
            if (stage, -score) < (best_stage, -best_score):
                best_stage = stage
                best_score = score

        if best_score < 0.45:
            continue

        rows.append(
            {
                "manager_id": manager["id"],
                "name": manager["name"],
                "display_name": manager["display"],
                "cik": manager["cik"],
                "location": "",
                "sic": "",
                "source": "curated",
                "score": round(best_score + (0.02 if manager["popular"] else 0.0), 4),
                "match_stage": best_stage,
                "popular": manager["popular"],
            }
        )

    if not rows:
        return pd.DataFrame(columns=["manager_id", "name", "display_name", "cik", "location", "sic", "source", "score", "match_stage", "popular"])

    out = pd.DataFrame(rows).sort_values(["match_stage", "score", "popular", "name"], ascending=[True, False, False, True])
    return out.drop_duplicates(subset=["cik"]).head(limit).reset_index(drop=True)
