"""Hand-checked cases for each formula, plus API, guardrail and design-rule checks.

Expected numbers are worked out by hand from data/*.csv (see comments), not by calling the engine.
"""
from datetime import timedelta
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from engine.decide import normalise_weights, rank
from engine.exposure import dependency_by_country, get_exposure
from engine.event_source import get_events
from engine.loader import DATA_DIR, load_all
from engine.simulate import resolve_scenario, run_baseline, run_scenario, evaluate
from engine.strategies import run_all

DATA = load_all()
ORDERS = pd.read_csv(DATA_DIR / "orders.csv", parse_dates=["due_date"])
TODAY = ORDERS["due_date"].min().date() - timedelta(days=3)      # first order is due on day 3
S1 = resolve_scenario(DATA, "S1", {})
S2 = resolve_scenario(DATA, "S2", {})


# ------------------------------------------------------------------ dataset design rules
def test_dataset_shape():
    assert len(DATA["materials"]) == 6
    sup = DATA["suppliers"]
    assert 10 <= len(sup) <= 12 and (~sup.is_alternative).sum() == 8 and 3 <= sup.is_alternative.sum() <= 4
    assert len(DATA["products"]) == 3
    assert 25 <= len(ORDERS) <= 30
    assert (ORDERS["due_date"].dt.date - TODAY).apply(lambda d: d.days).max() <= 60
    assert len(DATA["scenarios"]) == 2
    assert all(len([s for s in DATA["strategies"] if s["scenario_type"] == t]) == 4 for t in ("supply", "demand"))
    assert any(s["id"] == "DO_NOTHING" for s in DATA["strategies"])
    assert 5 <= len(DATA["events"]) <= 8


def test_supply_split_50_30_20():
    shares = {d["country"]: d["share_pct"] for d in dependency_by_country(DATA)}
    assert shares["China"] == pytest.approx(50, abs=1.5)
    assert shares["Taiwan"] + shares["Japan"] == pytest.approx(30, abs=1.5)        # M01: Taiwan 70% / Japan 30%
    assert shares["South Korea"] + shares["Vietnam"] == pytest.approx(20, abs=1.5)  # M06: Korea 60% / Vietnam 40%


# ------------------------------------------------------------------ KPI formulas (hand-checked)
def test_inventory_runway():
    # M02 PMIC: 17,600 units / 1,100 per day = 16.0 days
    m = {r["material_id"]: r for r in run_baseline(DATA, TODAY)["materials"]}
    assert m["M02"]["runway_days"] == 16.0


def test_supply_gap_and_stop_date():
    # new lead = 14 + 14 days x 85% = 25.9; gap = 25.9 - 16 = 9.9 > 0 -> stop on today + 16
    r = evaluate(DATA, S1, None, TODAY)
    m = {x["material_id"]: x for x in r["materials"]}
    assert m["M02"]["new_lead_time_days"] == 25.9
    assert m["M02"]["supply_gap_days"] == 9.9
    assert r["kpis"]["production_stop_date"]["value"] == (TODAY + timedelta(days=16)).isoformat()
    # M03 PCB: runway 30 > new lead 12 + 11.9 = 23.9 -> no stop
    assert not m["M03"]["stops_production"]


def test_cost_impact():
    # affected units = usage x 14 days; price +5%; extra freight = value x 8% x 60%
    # M02 15,400 x 6.50 = 100,100 -> 5,005.0 + 4,804.8
    # M03 12,600 x 9.00 = 113,400 -> 5,670.0 + 5,443.2
    # M04  5,600 x 4.00 =  22,400 -> 1,120.0 + 1,075.2
    # M05  5,600 x 3.50 =  19,600 ->   980.0 +   940.8      total = 25,039.0
    r = evaluate(DATA, S1, None, TODAY)
    assert r["kpis"]["cost_impact"]["value"] == pytest.approx(25039.0, abs=0.5)


def test_revenue_at_risk_s1():
    # every product uses M02, so all orders due between day 16.0 and day 25.9 are at risk
    due = (ORDERS["due_date"].dt.date - TODAY).apply(lambda d: d.days)
    expected = ORDERS[(due >= 16.0) & (due <= 25.9)]["value_rm"].sum()
    r = evaluate(DATA, S1, None, TODAY)
    assert expected > 0
    assert r["kpis"]["revenue_at_risk"]["value"] == pytest.approx(expected)


def test_baseline_gross_margin():
    # revenue (60 days) = 2 x (12,000x82 + 6,000x122 + 9,000x88) = 5,016,000
    # material = 60 x 36,478/day = 2,188,680 ; freight 8% = 175,094.4 ; conversion 30% = 1,504,800
    b = run_baseline(DATA, TODAY)["financials"]
    assert b["revenue_rm"] == 5_016_000
    assert b["gross_margin_pct"] == pytest.approx((5_016_000 - 2_188_680 * 1.08 - 1_504_800) / 5_016_000 * 100, abs=0.01)


def test_cash_position_formula():
    r = evaluate(DATA, S1, None, TODAY)
    k = r["kpis"]["cash_position"]
    i = k["inputs"]
    assert k["value"] == pytest.approx(i["projected_cash_on_hand_rm"] - i["cost_impact_rm"] - i["strategy_upfront_cost_rm"], abs=0.02)


def test_excess_inventory_s2():
    # open POs = usage x 60 - stock, so baseline excess = 0;
    # with a 25% drop: excess = 25% x 60 days x 36,478 RM/day = 547,170
    assert run_baseline(DATA, TODAY)["kpis"]["excess_inventory"]["value"] == 0
    assert evaluate(DATA, S2, None, TODAY)["kpis"]["excess_inventory"]["value"] == pytest.approx(547_170, abs=1)


def test_revenue_at_risk_s2():
    book = ORDERS[(ORDERS["due_date"].dt.date - TODAY).apply(lambda d: d.days).between(0, 60)]["value_rm"].sum()
    assert evaluate(DATA, S2, None, TODAY)["kpis"]["revenue_at_risk"]["value"] == pytest.approx(book * 0.25)


def test_risk_level_thresholds():
    assert run_baseline(DATA, TODAY)["kpis"]["business_risk"]["value"] == "Low"
    assert run_scenario(DATA, S1, TODAY)["risk_level"] == "High"           # revenue at risk > 10%
    mild = resolve_scenario(DATA, "S1", {"severity_pct": 10, "duration_days": 3})
    assert run_scenario(DATA, mild, TODAY)["risk_level"] in ("Low", "Medium")


def test_weak_suppliers_flagged_in_s2():
    # stress = (1 - reliability) x (1 + 2 x 25%) + 15%: SUP04 0.57, SUP08 0.48 >= 0.40 ; SUP03 0.33 < 0.40
    flagged = {s["supplier_id"] for s in evaluate(DATA, S2, None, TODAY)["supplier_stress"] if s["at_risk"]}
    assert flagged == {"SUP04", "SUP08"}


# ------------------------------------------------------------------ decision engine
def test_weights_normalise():
    w = normalise_weights({"value": 4, "cost": 2.5, "cash": 2, "feasibility": 1.5})
    assert sum(w.values()) == pytest.approx(1)
    assert w["value"] == pytest.approx(0.40)


def test_score_is_weighted_sum():
    rows = run_all(DATA, S1, TODAY)
    out = rank(rows, None, S1, 16.0)
    for r in out["ranking"]:
        assert r["score"] == pytest.approx(sum(out["weights"][k] * r["normalised"][k] for k in out["weights"]), abs=1e-3)
        assert all(0 <= v <= 1 for v in r["normalised"].values())
    assert any(r["is_do_nothing"] for r in out["ranking"])


def test_opposite_advice():
    s1 = rank(run_all(DATA, S1, TODAY), None, S1, 16.0)
    s2 = rank(run_all(DATA, S2, TODAY), None, S2, None)
    assert s1["recommendation"]["strategy_id"] == "S1_BUY_EARLY_ALT"      # act early, secure supply
    assert s2["recommendation"]["strategy_id"] == "S2_CUT_PO"            # hold back, protect cash
    dn1 = s1["do_nothing"]
    assert any(r["score"] > dn1["score"] for r in s1["ranking"] if not r["is_do_nothing"])
    assert "before stockout" in s1["recommendation"]["sentence"]


def test_weights_change_ranking():
    rows = run_all(DATA, S1, TODAY)
    a = rank(rows, {"value": 0.4, "cost": 0.25, "cash": 0.2, "feasibility": 0.15}, S1, 16.0)
    b = rank(rows, {"value": 0, "cost": 1, "cash": 0, "feasibility": 0}, S1, 16.0)
    assert a["ranking"][0]["id"] != b["ranking"][0]["id"]


def test_exposure_and_events():
    e = get_exposure(DATA, S1, TODAY)
    assert e["summary"]["affected_suppliers"] == 4
    assert e["map"]["epicentre"]["name"].startswith("Yantian")
    ev = get_events(DATA)
    assert all(x["scenario_id"] in ("S1", "S2") for x in ev)


def test_invalid_scenario_values_rejected():
    with pytest.raises(ValueError):
        resolve_scenario(DATA, "S1", {"affected_country": "Atlantis"})
    assert resolve_scenario(DATA, "S1", {"severity_pct": 500})["drivers"]["severity_pct"] == 100


# ------------------------------------------------------------------ API + AI fallback
@pytest.fixture(scope="module")
def client(monkeypatch_module=None):
    import os
    os.environ.pop("GEMINI_API_KEY", None)
    from backend.main import app
    return TestClient(app)


def test_api_routes(client):
    assert client.get("/api/baseline").status_code == 200
    r = client.post("/api/simulate", json={"scenario_id": "S1", "drivers": {}})
    assert r.status_code == 200 and len(r.json()["kpi_cards"]) == 5
    r = client.post("/api/decide", json={"scenario_id": "S2", "drivers": {}, "weights": {"value": .4, "cost": .25, "cash": .2, "feasibility": .15}})
    assert r.json()["ranking"][0]["id"] == "S2_CUT_PO"
    assert client.get("/api/events").json()["label"].startswith("Live Monitor (demo feed")
    assert client.post("/api/simulate", json={"scenario_id": "S1", "drivers": {"affected_country": "Mars"}}).status_code == 422
    assert client.get("/").status_code == 200


def test_ai_fallback_without_key(client):
    r = client.post("/api/ai/brief", json={"scenario_id": "S1", "drivers": {}}).json()
    assert r["source"] == "template" and "Recommended" in r["text"]
    p = client.post("/api/ai/parse-event", json={"headline": "Typhoon halts Yantian port operations for two weeks"}).json()
    assert p["valid"] and p["scenario_id"] == "S1" and p["drivers"]["affected_country"] == "China"
    a = client.post("/api/ai/ask", json={"question": "What if we wait a week?", "scenario_id": "S1", "drivers": {}}).json()
    assert a["source"] == "template"


def test_number_guardrail():
    from backend.ai import numbers_grounded
    res = {"cost": 25039.0, "margin": 22.88}
    assert numbers_grounded("Cost impact is RM 25k and margin is 22.9%.", res)
    assert not numbers_grounded("Cost impact is RM 90k.", res)


# ------------------------------------------------------------------ design rules on the UI text
def test_ui_wording_rules():
    root = Path(__file__).resolve().parent.parent / "frontend"
    text = " ".join(p.read_text(encoding="utf-8") for p in root.rglob("*") if p.suffix in (".html", ".js"))
    low = text.lower()
    assert "real-time" not in low and "realtime" not in low and "real time" not in low
    import re
    assert not re.search(r"\bLive\b(?! Monitor)", text)          # only "Live Monitor (demo feed...)"
    assert "stock market" not in low
    assert "Simulated data" in text and "Assumptions" in text and "Scenario: Active" not in text  # status text comes from API


def test_today_is_the_data_date():
    """The engine uses the data generation date as 'today', so results do not drift day to day."""
    from engine.loader import data_as_of
    assert data_as_of() == TODAY
    assert evaluate(DATA, S1, None)["today"] == TODAY.isoformat()


def test_value_protected_counts_saved_orders_once():
    """Value protected = extra gross profit vs Do nothing, so it can never exceed the revenue it saves plus
    the margin change on revenue that was already safe; for supply strategies it stays below revenue at risk."""
    rows = run_all(DATA, S1, TODAY)
    dn = next(r for r in rows if r["is_do_nothing"])
    dn_gp = evaluate(DATA, S1, None, TODAY)["financials"]["gross_profit_rm"]
    for r in rows:
        strat = next(s for s in DATA["strategies"] if s["id"] == r["id"])
        gp = dn_gp if r["is_do_nothing"] else evaluate(DATA, S1, strat, TODAY)["financials"]["gross_profit_rm"]
        assert r["criteria"]["value_protected_rm"] == pytest.approx(gp - dn_gp, abs=1)
        if r["breakdown"]["revenue_at_risk_avoided_rm"] > 0:
            assert r["criteria"]["value_protected_rm"] < dn["breakdown"]["revenue_at_risk_rm"]


def test_unrelated_headline_rejected(client, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    for h in ("Manchester United wins the derby", "Apple launches a new iPhone", "US port strike ends"):
        r = client.post("/api/ai/parse-event", json={"headline": h}).json()
        assert r["valid"] is False and r["scenario_id"] is None
    r = client.post("/api/ai/parse-event", json={"headline": "Typhoon halts Kaohsiung port for 10 days"}).json()
    assert r["valid"] and r["scenario_id"] == "S1" and r["drivers"]["affected_country"] == "Taiwan"


def test_health(client):
    r = client.get("/api/health").json()
    assert r["status"] == "ok" and r["data_as_of"] == TODAY.isoformat()
    assert "key" not in str(r["ai"].get("model", "")).lower()


def test_every_supply_area_runs_and_penang_hits_all_suppliers():
    for area in DATA["scenarios"]["S1"]["drivers"]["affected_country"]["options"]:
        sc = resolve_scenario(DATA, "S1", {"affected_country": area})
        assert get_exposure(DATA, sc, TODAY)["summary"]["affected_suppliers"] >= 1, area
    pen = resolve_scenario(DATA, "S1", {"affected_country": "Malaysia"})
    ex = get_exposure(DATA, pen, TODAY)["summary"]
    assert ex["affected_suppliers"] == ex["current_suppliers"]
    rows = {r["id"]: r for r in run_all(DATA, pen, TODAY)}
    # every alternative for the PMIC also ships through Penang Port, so buying early cannot help
    assert rows["S1_BUY_EARLY_ALT"]["criteria"]["feasibility"] == 0
    assert rows["S1_AIR_FREIGHT"]["breakdown"]["revenue_at_risk_avoided_rm"] > 0


def test_alternative_supplier_is_picked_outside_the_closed_area():
    rows = {r["id"]: r for r in run_all(DATA, S1, TODAY)}
    assert rows["S1_BUY_EARLY_ALT"]["name"].endswith("(South Korea)")     # fastest: Changwon, 9 days
    assert rows["S1_SWITCH_ALT"]["name"].endswith("(Taiwan)")             # next: Kaohsiung PowerChip


def test_headline_sets_every_input_it_mentions(client):
    r = client.post("/api/ai/parse-event",
                    json={"headline": "Typhoon halts Hai Phong port for 10 days; freight rates up 40%"}).json()
    assert r["valid"] and r["drivers"]["affected_country"] == "Vietnam"
    assert r["drivers"]["duration_days"] == 10 and r["drivers"]["freight_increase_pct"] == 40
    assert {"duration_days", "freight_increase_pct"} <= set(r["from_headline"])
    assert all(e["because"] for e in r["parsed"]["evidence"])          # each value says which words set it
    r = client.post("/api/ai/parse-event", json={"headline": "Penang Port shut after flooding"}).json()
    assert r["drivers"]["affected_country"] == "Malaysia"


def test_real_headlines_mapped_and_fallback(client):
    from unittest import mock
    from backend import news
    fake = [{"headline": "Typhoon halts Kaohsiung port operations for three days", "url": "https://a.example/1",
             "domain": "a.example", "timestamp": "2026-11-10T03:00:00+00:00"},
            {"headline": "Rotterdam port strike ends after pay deal", "url": "https://a.example/2",
             "domain": "a.example", "timestamp": "2026-11-11T03:00:00+00:00"}]
    with mock.patch.object(news, "live_headlines", return_value=(fake, None, 60)):
        r = client.get("/api/events?source=live").json()
    assert r["source"] == "live" and len(r["events"]) == 1                  # Rotterdam is not a modelled shock
    e = r["events"][0]
    assert e["drivers"]["affected_country"] == "Taiwan" and e["drivers"]["duration_days"] == 3 and e["url"]
    with mock.patch.object(news, "live_headlines", return_value=([], "timeout", 0)):
        r = client.get("/api/events?source=live").json()
    assert r["source"] == "demo" and r["events"] and "demo feed" in r["note"]


def test_gdelt_reply_parsing():
    from unittest import mock
    from backend import news

    class Resp:
        def __init__(self, body, js=True):
            self.text, self._js = body, js
        def raise_for_status(self): pass
        def json(self):
            if not self._js:
                raise ValueError("not json")
            return self.text
    ok = Resp({"articles": [{"title": "Port  closed in Busan as typhoon nears", "url": "u", "domain": "d",
                             "seendate": "20261111T043000Z"}, {"title": "short"}]})
    with mock.patch.object(news.httpx, "get", return_value=ok):
        items = news._fetch("q")
    assert items == [{"headline": "Port closed in Busan as typhoon nears", "url": "u", "domain": "d",
                      "timestamp": "2026-11-11T04:30:00+00:00"}]
    with mock.patch.object(news.httpx, "get", return_value=Resp("Please limit requests to one every 5 seconds.", js=False)):
        with pytest.raises(RuntimeError):
            news._fetch("q")


def test_guardrail_reads_amounts_inside_engine_sentences():
    from backend import ai
    results = {"explanation": "Cut purchase orders: frees RM 483k of cash vs doing nothing.", "cash": 2543762.0}
    assert ai.numbers_grounded("Cutting orders frees RM 483k of cash.", results)
    assert ai.numbers_grounded("Cash stands at RM 2.54M.", results)
    assert not ai.numbers_grounded("It would save RM 999k.", results)
