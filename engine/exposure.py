"""Which suppliers, materials, products and orders a scenario touches, and how dependent we are on them."""
from __future__ import annotations

from datetime import date

from .simulate import _prep, _r, evaluate, is_affected


def dependency_by_country(data: dict) -> list[dict]:
    """Share of supply spend by country (current suppliers): sum(daily usage x share x unit cost)."""
    P = _prep(data)
    spend: dict[str, float] = {}
    for r in P["cur"].itertuples():
        spend[r.country] = spend.get(r.country, 0.0) + P["usage"][r.material_id] * r.share_pct / 100 * r.unit_cost_rm
    total = sum(spend.values())
    return sorted([{"country": c, "daily_spend_rm": _r(v), "share_pct": _r(v / total * 100, 1)}
                   for c, v in spend.items()], key=lambda x: -x["share_pct"])


def get_exposure(data: dict, scenario: dict | None, today: date | None = None) -> dict:
    P = _prep(data)
    H = P["H"]
    res = evaluate(data, scenario, None, today)
    mats = {m["material_id"]: m for m in res["materials"]}
    stress = {s["supplier_id"]: s for s in res["supplier_stress"]}
    stype = scenario["type"] if scenario else None
    country = scenario["drivers"].get("affected_country") if scenario else None
    total_spend = sum(P["usage"][r.material_id] * r.share_pct / 100 * r.unit_cost_rm for r in P["cur"].itertuples())
    bom = data["bom"]
    orders = data["orders"]
    risk_by_order = {o["order_id"]: o["at_risk_value_rm"] for o in res["orders_at_risk"]}

    suppliers = []
    for r in data["suppliers"].itertuples():
        spend = P["usage"][r.material_id] * r.share_pct / 100 * r.unit_cost_rm
        prods = sorted(bom[bom["material_id"] == r.material_id]["product_id"].unique().tolist())
        dep_orders = orders[orders["product_id"].isin(prods)]
        st = stress.get(r.supplier_id, {})
        affected = (not r.is_alternative) and (
            (stype == "supply" and is_affected(r.country, r.ship_route, scenario)) or (stype == "demand" and st.get("at_risk", False)))
        suppliers.append({
            "supplier_id": r.supplier_id, "name": r.name, "country": r.country, "lat": r.lat, "lon": r.lon,
            "material_id": r.material_id, "material_name": mats[r.material_id]["name"],
            "share_pct": r.share_pct, "unit_cost_rm": r.unit_cost_rm, "lead_time_days": r.lead_time_days,
            "capacity_units_per_week": int(r.capacity_units_per_week), "is_alternative": bool(r.is_alternative),
            "reliability": r.reliability, "ship_route": r.ship_route,
            "spend_rm_horizon": _r(spend * H), "share_of_total_spend_pct": _r(spend / total_spend * 100, 1),
            "products_using": prods,
            "orders_depending_rm": _r(float(dep_orders["value_rm"].sum())),
            "orders_at_risk_rm": _r(sum(risk_by_order.get(o, 0.0) for o in dep_orders["order_id"])) if affected else 0.0,
            "material_runway_days": mats[r.material_id]["runway_days"],
            "material_new_lead_time_days": mats[r.material_id]["new_lead_time_days"],
            "material_stops_production": mats[r.material_id]["stops_production"],
            "stress_score": st.get("stress_score"), "at_risk": bool(st.get("at_risk", False)),
            "affected": bool(affected),
        })

    affected_materials = [m for m in res["materials"] if m["affected_share_pct"] > 0] if stype == "supply" else (
        [m for m in res["materials"] if res["kpis"]["excess_inventory"]["inputs"]["by_material_rm"][m["material_id"]] > 0]
        if stype == "demand" else [])
    aff_ids = {m["material_id"] for m in affected_materials}
    alternatives = [s for s in suppliers if s["is_alternative"] and (s["material_id"] in aff_ids or not aff_ids)]
    aff_sup = [s for s in suppliers if s["affected"]]
    sdef = data["scenarios"][scenario["id"]] if scenario else None
    epi_key = country if stype == "supply" else "Global"
    epicentre = sdef["epicentres"].get(epi_key) if sdef else None

    return {
        "dependency_by_country": dependency_by_country(data),
        "suppliers": suppliers,
        "affected_materials": affected_materials,
        "orders_at_risk": [o for o in res["orders_at_risk"] if o["at_risk_value_rm"] > 0],
        "alternatives": alternatives,
        "affected_products": sorted({p for m in aff_ids for p in bom[bom["material_id"] == m]["product_id"]}),
        "summary": {
            "affected_suppliers": len(aff_sup),
            "current_suppliers": int((~data["suppliers"]["is_alternative"]).sum()),
            "affected_spend_share_pct": _r(sum(s["share_of_total_spend_pct"] for s in aff_sup), 1),
            "affected_materials": len(affected_materials),
            "materials_stopping_production": sum(1 for m in affected_materials if m.get("stops_production")),
            "orders_at_risk": len([o for o in res["orders_at_risk"] if o["at_risk_value_rm"] > 0]),
            "revenue_at_risk_rm": res["financials"]["revenue_at_risk_rm"],
            "at_risk_suppliers": [s["name"] for s in suppliers if s["at_risk"] and not s["is_alternative"]],
        },
        "map": {"company": {**data["location"], "label": data["company"]["name"]},
                "epicentre": epicentre, "scenario_type": stype},
    }
