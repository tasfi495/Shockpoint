"""Reads all CSV/JSON in /data into DataFrames once."""
from __future__ import annotations

import json
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MYT = ZoneInfo("Asia/Kuala_Lumpur")

# Map coordinates for the company's city (location only, not a business figure).
CITY_COORDS = {"Penang": {"lat": 5.2945, "lon": 100.2590, "name": "Bayan Lepas, Penang"}}


def today_myt() -> date:
    return datetime.now(MYT).date()


def data_as_of() -> date:
    """The date the data was generated. The engine treats it as "today", so results
    do not drift from day to day. Falls back to the real date if meta.json is missing."""
    try:
        with open(DATA_DIR / "meta.json", encoding="utf-8") as f:
            return date.fromisoformat(json.load(f)["as_of"])
    except (OSError, KeyError, ValueError):
        return today_myt()


def _read_json(name: str):
    with open(DATA_DIR / name, encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def load_all() -> dict:
    """Returns every dataset. DataFrames for CSV, lists/dicts for JSON."""
    company = pd.read_csv(DATA_DIR / "company.csv").iloc[0].to_dict()
    materials = pd.read_csv(DATA_DIR / "materials.csv")
    suppliers = pd.read_csv(DATA_DIR / "suppliers.csv")
    suppliers["is_alternative"] = suppliers["is_alternative"].astype(str).str.lower() == "true"
    products = pd.read_csv(DATA_DIR / "products.csv")
    bom = pd.read_csv(DATA_DIR / "bom.csv")
    orders = pd.read_csv(DATA_DIR / "orders.csv", parse_dates=["due_date"])
    orders["due_date"] = orders["due_date"].dt.date
    assumptions_df = pd.read_csv(DATA_DIR / "assumptions.csv")
    assumptions = {r["name"]: float(r["value"]) for _, r in assumptions_df.iterrows()}
    events_path = DATA_DIR / "events_feed.json"
    return {
        "company": company,
        "materials": materials,
        "suppliers": suppliers,
        "products": products,
        "bom": bom,
        "orders": orders,
        "scenarios": {s["id"]: s for s in _read_json("scenarios.json")},
        "strategies": _read_json("strategies.json"),
        "assumptions": assumptions,
        "assumptions_table": assumptions_df.to_dict(orient="records"),
        "events": _read_json("events_feed.json") if events_path.exists() else [],
        "location": CITY_COORDS.get(company["city"], {"lat": 0.0, "lon": 0.0, "name": company["city"]}),
    }


def assumption_source(data: dict, name: str) -> str:
    for r in data["assumptions_table"]:
        if r["name"] == name:
            return str(r["source"])
    return "illustrative"
