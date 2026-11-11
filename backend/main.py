"""FastAPI: API routes + serves frontend/.

Routes (Development Plan):
  GET  /api/health         liveness check for the host: data loaded, data date, AI key set (never the key)
  GET  /api/baseline       company, baseline KPIs, scenario definitions, assumptions, supplier exposure
  POST /api/simulate       baseline vs scenario KPIs, exposure, banner, top recommendation
  POST /api/decide         strategy comparison, weighted ranking, recommendation sentence
  GET  /api/events         Live Monitor feed: ?source=demo (simulated) or ?source=live (real GDELT headlines)
  POST /api/ai/brief       Gemini executive briefing (template fallback)
  POST /api/ai/parse-event Gemini headline -> scenario JSON (validated)
  POST /api/ai/ask         Ask ShockPoint, grounded in current results
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from engine import decide as decide_mod  # noqa: E402
from engine.event_source import FEED_LABEL, get_events, to_drivers  # noqa: E402
from engine.exposure import get_exposure  # noqa: E402
from engine.loader import data_as_of, load_all  # noqa: E402
from engine.simulate import resolve_scenario, run_baseline, run_scenario  # noqa: E402
from engine.strategies import run_all  # noqa: E402

from . import ai, news  # noqa: E402
from .schemas import (AITextResponse, AskRequest, BaselineResponse, BriefRequest, DecideRequest,  # noqa: E402
                      DecideResponse, EventsResponse, ParseEventRequest, ParseEventResponse,
                      SimulateRequest, SimulateResponse)

logging.basicConfig(level=logging.INFO)
FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
DATA_LABEL = "Simulated data"
LIVE_LABEL = "Live Monitor (real headlines from GDELT, last 7 days)"

app = FastAPI(title="ShockPoint API", version="1.0.0",
              description="Know where a world event hits your business, and what to do about it.")


# ----------------------------------------------------------------- helpers
def _nice_date(iso: str) -> str:
    """2026-11-28 -> 28 Nov 2026 (works on Windows too)."""
    dt = date.fromisoformat(iso)
    return f"{dt.day} {dt.strftime('%b %Y')}"


def _scenario(req: SimulateRequest) -> dict:
    try:
        return resolve_scenario(load_all(), req.scenario_id, req.drivers)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


def _simulate(scenario: dict) -> dict:
    data = load_all()
    today = data_as_of()
    comp = run_scenario(data, scenario, today)
    exp = get_exposure(data, scenario, today)
    res = comp["scenario"]
    cards = {c["key"]: c for c in comp["kpi_cards"]}
    d = scenario["drivers"]
    s = exp["summary"]
    if scenario["type"] == "supply":
        stop = cards["production_stop_date"]["scenario"]
        port = (scenario.get("epicentre") or {}).get("route_port")
        where = f"that ship through {port}" if port else f"in {d['affected_country']}"
        lost = "port capacity" if port else "export capacity"
        detail = (f"{d['severity_pct']:.0f}% of {lost} lost for {d['duration_days']:.0f} days. "
                  f"{s['affected_suppliers']} of {s['current_suppliers']} current suppliers "
                  f"({s['affected_spend_share_pct']:.0f}% of supply spend) {where} are hit. "
                  + (f"Production stops on {_nice_date(stop)}." if stop else "Stock covers the delay; no production stop."))
    else:
        detail = (f"Customers cut orders {d['demand_drop_pct']:.0f}%. "
                  f"Excess inventory: {decide_mod._rm(cards['excess_inventory']['scenario'])}; "
                  f"cash {decide_mod._rm(abs(cards['cash_position']['delta']))} "
                  f"{'lower' if cards['cash_position']['delta'] < 0 else 'higher'} than baseline.")
    banner = {"title": scenario["name"], "status": "Scenario: Active", "risk_level": comp["risk_level"],
              "category": scenario["category"], "text": detail, "precedent": scenario["precedent"],
              "epicentre": exp["map"]["epicentre"]}
    return {"comparison": comp, "exposure": exp, "banner": banner, "result": res}


def _decide(scenario: dict, weights: dict | None) -> dict:
    data = load_all()
    today = data_as_of()
    rows = run_all(data, scenario, today)
    dn = next(r for r in rows if r["is_do_nothing"])
    stop_day = dn["stock_projection"]["stop_day"] if dn["stock_projection"] else None
    out = decide_mod.rank(rows, weights, scenario, stop_day)
    out["scenario"] = scenario
    return out


def _drivers_from(data: dict, parsed: dict | None) -> tuple[str | None, dict, list[str], str | None]:
    """Parsed headline -> (scenario id, full driver set, drivers the headline set, error).
    Starts from the scenario defaults, applies only what the headline says, then clamps to slider ranges."""
    if not parsed:
        return None, {}, [], None
    sid = parsed["scenario_id"]
    drivers = to_drivers(data, sid, parsed["severity"])
    from_headline: list[str] = []
    if sid == "S1":
        drivers["affected_country"] = parsed["affected_country"]
        from_headline += ["affected_country", "severity_pct"]
    keys = (["duration_days", "freight_increase_pct"] if sid == "S1"
            else ["demand_drop_pct", "input_price_change_pct", "myr_usd_change_pct"])
    if sid == "S2" and parsed.get("demand_drop_pct") is None:
        from_headline.append("demand_drop_pct")            # set from severity
    for k in keys:
        if parsed.get(k) is not None:
            drivers[k] = parsed[k]
            from_headline.append(k)
    try:
        drivers = resolve_scenario(data, sid, drivers)["drivers"]   # clamps values, rejects unknown places
    except ValueError as e:
        return None, {}, [], str(e)
    return sid, drivers, sorted(set(from_headline)), None


# ----------------------------------------------------------------- routes
@app.get("/api/health")
def api_health():
    """Cheap check for hosts and judges. Reports whether an AI key is set, never the key itself."""
    try:
        data = load_all()
        ok = bool(data["scenarios"]) and len(data["suppliers"]) > 0
    except Exception as e:  # noqa: BLE001 - report, don't crash
        return {"status": "error", "detail": f"data not loaded: {e}"}
    return {"status": "ok" if ok else "error", "app": "ShockPoint", "version": app.version,
            "data_as_of": data_as_of().isoformat(),
            "ai": {"gemini_key_set": ai._get_client() is not None, "model": ai.MODEL,
                   "backup_key_set": ai._backup_config() is not None}}


@app.get("/api/baseline", response_model=BaselineResponse)
def api_baseline():
    data = load_all()
    today = data_as_of()
    return {
        "app": {"name": "ShockPoint", "tagline": "Know where a world event hits your business, and what to do about it.",
                "data_label": DATA_LABEL, "monitor_label": FEED_LABEL},
        "today": today.isoformat(),
        "company": data["company"],
        "location": data["location"],
        "baseline": run_baseline(data, today),
        "scenarios": list(data["scenarios"].values()),
        "strategies": data["strategies"],
        "assumptions": data["assumptions_table"],
        "exposure": get_exposure(data, None, today),
        "default_weights": decide_mod.DEFAULT_WEIGHTS,
    }


@app.post("/api/simulate", response_model=SimulateResponse)
def api_simulate(req: SimulateRequest):
    scenario = _scenario(req)
    sim = _simulate(scenario)
    dec = _decide(scenario, None)
    return {"scenario": scenario, "banner": sim["banner"], "kpi_cards": sim["comparison"]["kpi_cards"],
            "risk_level": sim["comparison"]["risk_level"], "baseline": sim["comparison"]["baseline"],
            "result": sim["result"], "exposure": sim["exposure"],
            "top_recommendation": {**dec["recommendation"], "weights": dec["weights"]}}


@app.post("/api/decide", response_model=DecideResponse)
def api_decide(req: DecideRequest):
    scenario = _scenario(req)
    return _decide(scenario, req.weights.model_dump())


@app.get("/api/events", response_model=EventsResponse)
def api_events(source: str = "demo"):
    """source=demo: the simulated feed. source=live: real headlines from GDELT (last 7 days), kept only when the
    keyword rules map them to a shock ShockPoint models. Falls back to the demo feed if none can be used."""
    data = load_all()
    demo = {"label": FEED_LABEL, "events": get_events(data), "source": "demo", "note": None}
    if source != "live":
        return demo
    items, error, age = news.live_headlines()
    events = []
    for it in items:
        parsed = ai._rule_parse(it["headline"])
        if not parsed.get("relevant"):
            continue
        sid, drivers, from_headline, err = _drivers_from(data, parsed)
        if not sid:
            continue
        sev = drivers.get("severity_pct", parsed["severity"]) if sid == "S1" else parsed["severity"]
        events.append({"index": len(events), "timestamp": it["timestamp"], "headline": it["headline"],
                       "url": it["url"], "domain": it["domain"], "scenario_id": sid, "severity": int(sev),
                       "scenario_name": data["scenarios"][sid]["name"], "drivers": drivers,
                       "from_headline": from_headline, "evidence": parsed["evidence"], "label": LIVE_LABEL})
        if len(events) >= 12:
            break
    if not events:
        why = ("the news service could not be reached" if error else
               f"none of the {len(items)} recent headlines is a shock ShockPoint models")
        return {**demo, "note": f"Real headlines unavailable: {why}. Showing the demo feed instead."}
    events.sort(key=lambda e: e["timestamp"])               # play oldest to newest
    for i, e in enumerate(events):
        e["index"] = i
    return {"label": LIVE_LABEL, "events": events, "source": "live",
            "note": f"{len(events)} of {len(items)} recent headlines map to a modelled shock "
                    f"(updated {int(age // 60)} min ago)."}


@app.post("/api/ai/brief", response_model=AITextResponse)
def api_ai_brief(req: BriefRequest):
    scenario = _scenario(req)
    sim = run_scenario(load_all(), scenario, data_as_of())
    sim["scenario"] = scenario
    return ai.brief(sim, _decide(scenario, req.weights.model_dump()))


@app.post("/api/ai/ask", response_model=AITextResponse)
def api_ai_ask(req: AskRequest):
    scenario = _scenario(req)
    sim = run_scenario(load_all(), scenario, data_as_of())
    sim["scenario"] = scenario
    return ai.ask(req.question, sim, _decide(scenario, req.weights.model_dump()))


@app.post("/api/ai/parse-event", response_model=ParseEventResponse)
def api_ai_parse_event(req: ParseEventRequest):
    data = load_all()
    parsed, source, errors = ai.parse_event(req.headline)
    sid, drivers, from_headline, err = _drivers_from(data, parsed)
    if err:
        errors.append(err)
        parsed = None
    return {"headline": req.headline, "parsed": parsed, "scenario_id": sid, "drivers": drivers,
            "from_headline": sorted(set(from_headline)),
            "valid": parsed is not None, "errors": errors, "source": source,
            "label": ai.AI_LABEL if source == "gemini" else "Keyword rules (AI unavailable)"}


# ----------------------------------------------------------------- frontend
@app.get("/", include_in_schema=False)
def index():
    return FileResponse(FRONTEND / "index.html")


app.mount("/", StaticFiles(directory=FRONTEND), name="frontend")
