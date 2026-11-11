"""Baseline vs scenario KPIs.

KPIs (Project Definition, "Outputs: business KPIs"):
  Inventory runway (days)  = stock on hand / daily usage                       (per material)
  Supply gap (days)        = new lead time - runway                          (production stops if > 0)
  Production stop date     = today + runway, when new lead time > runway
  Cost impact (RM)         = sum(affected units x unit cost x price increase %) + extra freight
  Gross margin (%)         = (revenue - cost of goods) / revenue
  Revenue at risk (RM)     = value of orders due inside the supply gap window (S1)
                             or cancelled by the demand drop (S2)
  Cash position (RM)       = cash on hand - cost impact - strategy upfront cost
                             (cash on hand is projected to the end of the analysis horizon)
  Excess inventory (RM)    = (stock - reduced usage x horizon days) x unit cost, if positive
  Business risk level      = Low / Medium / High from thresholds in assumptions.csv

Pure Python: no web framework, no AI. Every function returns plain dicts that include
the inputs and assumptions used, so the UI can show the working.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

from .loader import assumption_source, data_as_of

SRC_DATA = "Simulated data (data/*.csv)"


# --------------------------------------------------------------------------- helpers
def _r(x: float, n: int = 2) -> float:
    return float(round(float(x), n))


def resolve_scenario(data: dict, scenario_id: str | None, drivers: dict | None = None) -> dict | None:
    """Merges user drivers with scenarios.json defaults; clamps to slider ranges; rejects unknown values."""
    if not scenario_id:
        return None
    if scenario_id not in data["scenarios"]:
        raise ValueError(f"Unknown scenario_id '{scenario_id}'")
    sdef = data["scenarios"][scenario_id]
    drivers = drivers or {}
    out = {}
    for key, spec in sdef["drivers"].items():
        val = drivers.get(key, spec["default"])
        if spec["type"] == "select":
            if val not in spec["options"]:
                raise ValueError(f"'{val}' is not an allowed value for {key}: {spec['options']}")
        else:
            val = float(val)
            val = min(max(val, spec["min"]), spec["max"])
        out[key] = val
    # title, epicentre and precedent follow the drivers the user chose (not a fixed template)
    if sdef["type"] == "supply":
        country = out["affected_country"]
        epi = sdef["epicentres"].get(country)
        title = f"Port closure in {country}: {epi['name']}" if epi else f"Port closure in {country}"
    else:
        epi = sdef["epicentres"].get("Global")
        title = f"{sdef['name']}: orders down {out['demand_drop_pct']:.0f}%"
    precedent = (epi or {}).get("precedent") or sdef["precedent"]
    return {"id": scenario_id, "name": title, "base_name": sdef["name"], "type": sdef["type"],
            "category": sdef["category"], "drivers": out, "multipliers": sdef["multipliers"],
            "epicentre": epi, "precedent": precedent}


def is_affected(country: str, ship_route: str, scenario: dict | None) -> bool:
    """A supplier is hit when it sits in the closed country, or (for Penang Port) when its route ends at that port."""
    if not scenario or scenario["type"] != "supply":
        return False
    port = (scenario.get("epicentre") or {}).get("route_port")
    if port:
        return str(ship_route).strip().endswith(port)
    return country == scenario["drivers"]["affected_country"]


def _affected_rows(df, scenario: dict | None):
    return df[[is_affected(r.country, r.ship_route, scenario) for r in df.itertuples()]]


def pick_alternative(data: dict, scenario: dict, material_id: str, pick: str):
    """Alternative suppliers for a material that can still deliver (outside the closed area), fastest first.
    pick='fastest' -> the first; pick='second' -> the next one. Returns (row or None, reason)."""
    sup = data["suppliers"]
    alts = sup[(sup["is_alternative"]) & (sup["material_id"] == material_id)]
    if alts.empty:
        return None, "no alternative supplier makes it"
    ok = alts[[not is_affected(r.country, r.ship_route, scenario) for r in alts.itertuples()]]
    ok = ok.sort_values(["lead_time_days", "unit_cost_rm"])
    idx = 0 if pick == "fastest" else 1
    if len(ok) > idx:
        return ok.iloc[idx], ""
    if ok.empty:
        names = ", ".join(f"{r.name} ({r.country})" for r in alts.itertuples())
        return None, f"every alternative ({names}) ships through the closed port"
    return None, "there is only one alternative outside the closed area, used by the buy-early option"


def _prep(data: dict) -> dict:
    """Per-material and per-product base figures shared by every calculation."""
    A = data["assumptions"]
    mats = data["materials"].set_index("material_id")
    sup = data["suppliers"]
    cur = sup[~sup["is_alternative"]]
    mat_cost = {m: float((g["share_pct"] / 100 * g["unit_cost_rm"]).sum()) for m, g in cur.groupby("material_id")}
    base_lead = {m: float(g["lead_time_days"].max()) for m, g in cur.groupby("material_id")}
    dpm = A["days_per_month"]
    prods = data["products"].set_index("product_id")
    bom = data["bom"]
    p_mats = {p: set(g["material_id"]) for p, g in bom.groupby("product_id")}
    mc = {p: float(sum(r.qty_per_unit * mat_cost[r.material_id] for r in g.itertuples()))
          for p, g in bom.groupby("product_id")}
    H = A["analysis_horizon_days"]
    usage = {m: float(mats.loc[m, "daily_usage_units"]) for m in mats.index}
    stock = {m: float(mats.loc[m, "stock_units"]) for m in mats.index}
    receipts_plan = {m: max(0.0, usage[m] * H - stock[m]) for m in mats.index}
    return dict(A=A, H=H, mats=mats, sup=sup, cur=cur, mat_cost=mat_cost, base_lead=base_lead, prods=prods,
                p_mats=p_mats, mc=mc, dpm=dpm, usage=usage, stock=stock, receipts_plan=receipts_plan)


def _risk_level(A: dict, margin_drop_pp: float, rar_pct: float) -> str:
    if margin_drop_pp >= A["risk_high_margin_drop_pp"] or rar_pct >= A["risk_high_revenue_at_risk_pct"]:
        return "High"
    if margin_drop_pp >= A["risk_medium_margin_drop_pp"] or rar_pct >= A["risk_medium_revenue_at_risk_pct"]:
        return "Medium"
    return "Low"


def _supplier_stress(P: dict, demand_drop_pct: float, failure_risk_pct: float, po_cut_pct: float = 0.0) -> list:
    """stress = (1 - reliability) x (1 + 2 x (demand drop + our PO cut)) + supplier failure risk."""
    out = []
    thr = P["A"]["supplier_stress_threshold"]
    for r in P["cur"].itertuples():
        stress = (1 - r.reliability) * (1 + 2 * (demand_drop_pct + po_cut_pct) / 100) + failure_risk_pct / 100
        out.append({"supplier_id": r.supplier_id, "name": r.name, "country": r.country,
                    "reliability": r.reliability, "stress_score": _r(stress, 3), "at_risk": bool(stress >= thr)})
    return out


# --------------------------------------------------------------------------- core
def evaluate(data: dict, scenario: dict | None, strategy: dict | None = None, today: date | None = None) -> dict:
    """Runs one case: baseline (scenario=None), a scenario, or a scenario plus one strategy."""
    today = today or data_as_of()
    P = _prep(data)
    A, H = P["A"], P["H"]
    company = data["company"]
    stype = scenario["type"] if scenario else None
    dv = scenario["drivers"] if scenario else {}
    sid = strategy["id"] if strategy else "DO_NOTHING"

    orders = data["orders"].copy()
    orders["due_day"] = [(d - today).days for d in orders["due_date"]]
    orders = orders[(orders["due_day"] >= 0) & (orders["due_day"] <= H)]
    order_book = float(orders["value_rm"].sum())

    # ---- baseline money (over the analysis horizon)
    vol = {p: P["prods"].loc[p, "monthly_volume"] / P["dpm"] * H for p in P["prods"].index}   # units in horizon
    price = {p: float(P["prods"].loc[p, "price_rm"]) for p in P["prods"].index}
    rev_b = sum(vol[p] * price[p] for p in vol)
    mat_b = sum(P["usage"][m] * H * P["mat_cost"][m] for m in P["usage"])
    conv_b = sum(vol[p] * price[p] * A["conversion_cost_pct_of_price"] / 100 for p in vol)
    fr = A["freight_cost_pct_of_material"] / 100
    fixed = company["monthly_fixed_cost_rm"] * H / P["dpm"]
    purchases_b = sum(P["receipts_plan"][m] * P["mat_cost"][m] for m in P["usage"])

    # ---- material table (runway, lead time, supply gap)
    mat_rows = {}
    for m in P["usage"]:
        runway = P["stock"][m] / P["usage"][m]
        mat_rows[m] = {"material_id": m, "name": P["mats"].loc[m, "name"],
                       "criticality": int(P["mats"].loc[m, "criticality"]),
                       "stock_units": P["stock"][m], "daily_usage_units": P["usage"][m],
                       "safety_stock_units": float(P["mats"].loc[m, "safety_stock_units"]),
                       "unit_cost_rm": _r(P["mat_cost"][m], 4), "runway_days": _r(runway, 1),
                       "base_lead_time_days": P["base_lead"][m], "new_lead_time_days": P["base_lead"][m],
                       "affected_share_pct": 0.0, "supply_gap_days": _r(P["base_lead"][m] - runway, 1),
                       "stops_production": False, "stop_date": None, "restart_date": None,
                       "coverage_pct": 0.0, "open_po_units": P["receipts_plan"][m]}

    cost_impact, ci_parts = 0.0, []
    conv_save = 0.0
    rar, orders_at_risk = 0.0, []
    effect = {"strategy_id": sid, "coverage": {}, "qty_units": 0.0, "arrival_day": None, "notes": ""}
    upfront = ongoing = extra_purchases = savings = 0.0
    feas_time = feas_cap = 1.0
    stock_projection = None

    # =========================================================== SUPPLY SHOCK (S1)
    if stype == "supply":
        country = dv["affected_country"]
        sev, dur, fr_inc = dv["severity_pct"], dv["duration_days"], dv["freight_increase_pct"]
        delay = dur * sev / 100 * scenario["multipliers"]["lead_time_delay_per_closed_day"]
        price_inc = scenario["multipliers"]["input_price_increase_pct"]
        aff = _affected_rows(P["cur"], scenario)
        for m, g in aff.groupby("material_id"):
            row = mat_rows[m]
            share = float(g["share_pct"].sum())
            row["affected_share_pct"] = share
            row["new_lead_time_days"] = _r(float(g["lead_time_days"].max()) + delay, 1)
            row["supply_gap_days"] = _r(row["new_lead_time_days"] - row["runway_days"], 1)
            units = P["usage"][m] * share / 100 * dur                       # affected units
            price_part = units * P["mat_cost"][m] * price_inc / 100
            freight_part = units * P["mat_cost"][m] * fr * fr_inc / 100   # extra freight
            cost_impact += price_part + freight_part
            ci_parts.append({"material_id": m, "affected_units": _r(units, 0), "unit_cost_rm": _r(P["mat_cost"][m], 2),
                             "price_increase_pct": price_inc, "price_part_rm": _r(price_part),
                             "extra_freight_rm": _r(freight_part)})
            if row["supply_gap_days"] > 0:
                row["stops_production"] = True
                row["stop_day"] = row["runway_days"]
                row["restart_day"] = row["new_lead_time_days"]
                row["stop_date"] = (today + timedelta(days=int(math.floor(row["runway_days"])))).isoformat()
                row["restart_date"] = (today + timedelta(days=int(math.ceil(row["new_lead_time_days"])))).isoformat()
        stopped = [m for m, r in mat_rows.items() if r["stops_production"]]
        shortfall = {m: P["usage"][m] * mat_rows[m]["supply_gap_days"] for m in stopped}

        # ---- strategy effect on the supply gap
        cov = {m: 0.0 for m in stopped}
        stop_day = min((mat_rows[m]["runway_days"] for m in stopped), default=None)
        restart_day = max((mat_rows[m]["new_lead_time_days"] for m in stopped), default=None)
        buffer = A["feasibility_safety_buffer_days"]
        hold = A["holding_cost_pct_per_year"] / 100 * H / 365 * 0.5
        if strategy and sid != "DO_NOTHING":
            def timing(arrival: float) -> tuple[float, float]:
                """(time feasibility 0-1, share of the gap the arrival can still cover)."""
                ft = 1.0
                if stop_day is not None:
                    if arrival <= stop_day - buffer:
                        ft = 1.0
                    elif arrival <= stop_day:
                        ft = 0.75
                    elif arrival < restart_day:
                        ft = 0.75 * (restart_day - arrival) / (restart_day - stop_day)
                    else:
                        ft = 0.0
                return ft, (1.0 if (stop_day is None or arrival <= stop_day) else max(0.0, ft / 0.75))

            arrival = float(strategy["feasibility_days"])
            effect["arrival_day"] = arrival
            feas_time, time_cov = timing(arrival)
            if sid in ("S1_BUY_EARLY_ALT", "S1_SWITCH_ALT"):
                pick = strategy.get("supplier_pick", "fastest")
                # target: the stopped material that runs out first and has a usable alternative
                alt, reason, m = None, "", None
                for cand in sorted(stopped, key=lambda x: mat_rows[x]["runway_days"]):
                    a, why = pick_alternative(data, scenario, cand, pick)
                    if a is not None:
                        alt, m = a, cand
                        break
                    reason = reason or f"{P['mats'].loc[cand, 'name']}: {why}"
                if alt is not None:
                    arrival = float(alt["lead_time_days"])
                    effect["arrival_day"] = arrival
                    feas_time, time_cov = timing(arrival)
                    verb = "Buy early from" if sid == "S1_BUY_EARLY_ALT" else "Switch part of volume to"
                    effect["display_name"] = f"{verb} {alt['name']} ({alt['country']})"
                if not stopped:
                    feas_cap = 0.0
                    effect["notes"] = "No material runs short in this scenario, so no emergency supplier is needed."
                elif alt is None:
                    feas_cap = 0.0
                    effect["notes"] = reason[0].upper() + reason[1:] + "."
                else:
                    need = P["usage"][m] * (mat_rows[m]["supply_gap_days"] + buffer)
                    deliverable = alt["capacity_units_per_week"] * restart_day / 7
                    qty = min(need, deliverable)
                    feas_cap = min(1.0, deliverable / need)
                    cov[m] = feas_cap * time_cov
                    premium = qty * (alt["unit_cost_rm"] - P["mat_cost"][m])
                    upfront = premium + (strategy["upfront_cost"].get("amount_rm", 0) or 0)
                    extra_purchases = qty * P["mat_cost"][m]
                    ongoing = extra_purchases * hold
                    effect.update(qty_units=_r(qty, 0), material_id=m, supplier=alt["name"],
                                  notes=f"Order {qty:,.0f} units of {m} from {alt['name']} ({alt['country']}) "
                                        f"(capacity covers {feas_cap:.0%} of need).")
            elif sid == "S1_AIR_FREIGHT":
                total_qty = 0.0
                caps = []
                for m in stopped:
                    cap_wk = float(P["cur"][P["cur"]["material_id"] == m]["capacity_units_per_week"].sum())
                    deliverable = cap_wk * A["air_cargo_capacity_share_pct"] / 100 * dur / 7
                    qty = min(shortfall[m], deliverable)
                    c = min(1.0, deliverable / shortfall[m]) if shortfall[m] > 0 else 1.0
                    caps.append(c)
                    cov[m] = c * time_cov
                    total_qty += qty
                feas_cap = min(caps) if caps else 1.0
                upfront = total_qty * A["air_freight_surcharge_rm_per_unit"]
                effect.update(qty_units=_r(total_qty, 0),
                              notes=f"Fly {total_qty:,.0f} units at RM {A['air_freight_surcharge_rm_per_unit']:.2f}/unit "
                                    f"(air cargo space limited to {A['air_cargo_capacity_share_pct']:.0f}% of supplier volume).")
            elif sid == "S1_RAISE_PRICES":
                effect["notes"] = "Prices rise; the supply gap is not closed."
            effect["coverage"] = {m: _r(c * 100, 1) for m, c in cov.items()}
        for m in stopped:
            mat_rows[m]["coverage_pct"] = _r(cov[m] * 100, 1)

        # ---- orders due inside the supply gap window
        for o in orders.itertuples():
            blocking = [m for m in stopped if m in P["p_mats"][o.product_id]
                        and mat_rows[m]["runway_days"] <= o.due_day <= mat_rows[m]["new_lead_time_days"]]
            if blocking:
                frac = max(1 - cov[m] for m in blocking)
                rar += o.value_rm * frac
                orders_at_risk.append({"order_id": o.order_id, "customer": o.customer, "product_id": o.product_id,
                                       "qty": int(o.qty), "due_date": o.due_date.isoformat(), "due_day": int(o.due_day),
                                       "value_rm": float(o.value_rm), "currency": o.currency,
                                       "blocked_by": blocking, "at_risk_value_rm": _r(o.value_rm * frac)})

        # ---- money
        price_factor, vol_factor = 1.0, 1.0
        if strategy and "price_change_pct" in strategy and sid == "S1_RAISE_PRICES":
            pc = strategy["price_change_pct"] / 100
            price_factor, vol_factor = 1 + pc, 1 - A["price_elasticity"] * pc
        rev = (rev_b - rar) * price_factor * vol_factor
        lost_ratio = (rev_b - rar) * vol_factor / rev_b
        if sid == "S1_RAISE_PRICES":
            gm_dn_unit = (rev_b - mat_b * (1 + fr) - conv_b) / rev_b
            ongoing = (rev_b - rar) * (1 - vol_factor) * gm_dn_unit       # gross profit lost on volume
        mat_cons = mat_b * lost_ratio
        cogs = mat_cons * (1 + fr) + conv_b + cost_impact + upfront + extra_purchases * hold
        purchases = purchases_b + extra_purchases
        projected_cash = company["cash_on_hand_rm"] + rev - purchases * (1 + fr) - conv_b - fixed

        # ---- stock projection of the most critical affected material (chart data)
        focus = min(stopped, key=lambda m: mat_rows[m]["runway_days"]) if stopped else (
            max(ci_parts, key=lambda c: mat_rows[c["material_id"]]["criticality"])["material_id"] if ci_parts else "M02")
        s0, u = P["stock"][focus], P["usage"][focus]
        L0, L1 = P["base_lead"][focus], mat_rows[focus]["new_lead_time_days"]
        arr = effect.get("arrival_day") if effect.get("material_id", focus) == focus or sid == "S1_AIR_FREIGHT" else None
        add = effect["qty_units"] if arr is not None and sid != "S1_AIR_FREIGHT" else 0
        days = list(range(0, int(H) + 1))
        base_line = [_r(max(0.0, s0 - u * min(t, L0)), 0) for t in days]
        scen_line = [_r(max(0.0, s0 - u * min(t, L1)), 0) for t in days]
        strat_line = None
        if strategy and sid not in ("DO_NOTHING", "S1_RAISE_PRICES") and focus in stopped:
            strat_line = []
            c = cov.get(focus, 0.0)
            for t in days:
                if sid == "S1_AIR_FREIGHT":
                    v = max(0.0, s0 - u * min(t, L1) + c * u * max(0.0, min(t, L1) - mat_rows[focus]["runway_days"]))
                else:
                    v = s0 - u * min(t, L1) + (add if arr is not None and t >= arr else 0)
                strat_line.append(_r(max(0.0, v), 0))
        stock_projection = {"material_id": focus, "material_name": mat_rows[focus]["name"], "days": days,
                            "dates": [(today + timedelta(days=t)).isoformat() for t in days],
                            "baseline": base_line, "scenario": scen_line, "strategy": strat_line,
                            "stop_day": mat_rows[focus].get("stop_day"), "restart_day": mat_rows[focus].get("restart_day")}
        excess_rows = {m: 0.0 for m in P["usage"]}
        stress = _supplier_stress(P, 0.0, 0.0)
        for s in stress:
            s["affected"] = bool(s["country"] == country)

    # =========================================================== DEMAND SHOCK (S2)
    elif stype == "demand":
        d = dv["demand_drop_pct"] / 100
        pc = dv["input_price_change_pct"] / 100
        fx = dv["myr_usd_change_pct"] / 100
        fail = dv["supplier_failure_risk_pct"]
        d_eff, price_factor, conv_save, cut_frac = d, 1.0, 0.0, 0.0
        cancelled = {m: 0.0 for m in P["usage"]}
        if sid == "S2_DISCOUNT":
            disc = -strategy["price_change_pct"] / 100
            price_factor = 1 - disc
            d_eff = max(0.0, d - A["price_elasticity"] * disc)
        if sid == "S2_CUT_PO":
            notice = A["supplier_notice_days"]
            for m in P["usage"]:
                cancelled[m] = min(P["receipts_plan"][m], P["usage"][m] * d * (H - notice))
            cut_val = sum(cancelled[m] * P["mat_cost"][m] for m in P["usage"])
            upfront = cut_val * A["po_cancellation_fee_pct"] / 100
            extra_purchases = -cut_val
            cut_frac = d * (H - notice) / H * 100
            effect.update(qty_units=_r(sum(cancelled.values()), 0),
                          notes=f"Cancel RM {cut_val:,.0f} of open POs after the {notice:.0f}-day notice period.")
        if sid == "S2_SLOW_PRODUCTION":
            conv_save = conv_b * A["conversion_variable_share_pct"] / 100 * d
            upfront = strategy["upfront_cost"]["amount_rm"]
            effect["notes"] = f"Variable conversion cost falls by RM {conv_save:,.0f}."
        if sid == "S2_RENEGOTIATE":
            upfront = strategy["upfront_cost"]["amount_rm"]
        if sid == "S2_DISCOUNT":
            effect["notes"] = f"Demand drop narrows from {d:.0%} to {d_eff:.0%} at a {disc:.0%} lower price."

        receipts = {m: P["receipts_plan"][m] - cancelled[m] for m in P["usage"]}
        cons = {m: P["usage"][m] * (1 - d_eff) * H for m in P["usage"]}
        excess_rows = {m: max(0.0, (P["stock"][m] + receipts[m] - cons[m])) * P["mat_cost"][m] for m in P["usage"]}
        for m in P["usage"]:
            mat_rows[m]["open_po_units"] = _r(receipts[m], 0)
            mat_rows[m]["reduced_daily_usage_units"] = _r(P["usage"][m] * (1 - d_eff), 1)
        # cost impact: affected units = units purchased in the horizon; no freight driver in S2
        for m in P["usage"]:
            part = receipts[m] * P["mat_cost"][m] * pc
            cost_impact += part
            ci_parts.append({"material_id": m, "affected_units": _r(receipts[m], 0), "unit_cost_rm": _r(P["mat_cost"][m], 2),
                             "price_increase_pct": dv["input_price_change_pct"], "price_part_rm": _r(part),
                             "extra_freight_rm": 0.0})
        if sid == "S2_RENEGOTIATE":
            after = max(0.0, H - strategy["feasibility_days"]) / H
            savings = sum(receipts[m] * P["mat_cost"][m] for m in P["usage"]) * after * -strategy["cost_change_pct"] / 100
            effect["notes"] = f"5% lower prices on purchases after day {strategy['feasibility_days']}: RM {savings:,.0f} saved."
        rev = rev_b * (1 - d_eff) * price_factor * (1 - company["usd_revenue_share"] * fx)
        rar = order_book * d_eff
        for o in orders.itertuples():
            orders_at_risk.append({"order_id": o.order_id, "customer": o.customer, "product_id": o.product_id,
                                   "qty": int(o.qty), "due_date": o.due_date.isoformat(), "due_day": int(o.due_day),
                                   "value_rm": float(o.value_rm), "currency": o.currency, "blocked_by": [],
                                   "at_risk_value_rm": _r(o.value_rm * d_eff)})
        excess = sum(excess_rows.values())
        writedown = excess * A["excess_writedown_pct"] / 100
        holding = excess * A["holding_cost_pct_per_year"] / 100 * H / 365 * 0.5
        mat_cons = sum(cons[m] * P["mat_cost"][m] for m in P["usage"])
        conv = conv_b - conv_save
        cogs = mat_cons * (1 + fr) + conv + cost_impact + upfront + writedown + holding - savings
        ongoing = holding + writedown
        if sid == "S2_DISCOUNT":
            ongoing += rev_b * (1 - d_eff) * (1 - price_factor) * (1 - company["usd_revenue_share"] * fx)
        purchases = sum(receipts[m] * P["mat_cost"][m] for m in P["usage"])
        projected_cash = company["cash_on_hand_rm"] + rev - purchases * (1 + fr) - conv - fixed + savings
        extra_purchases = 0.0 if sid != "S2_CUT_PO" else extra_purchases   # already inside purchases
        notice_days = float(strategy["feasibility_days"]) if strategy else 0.0
        feas_time = max(0.2, min(1.0, 1 - notice_days / H))
        stress = _supplier_stress(P, dv["demand_drop_pct"], fail, cut_frac)
        for s in stress:
            s["affected"] = s["at_risk"]

    # =========================================================== BASELINE
    else:
        rev = rev_b
        cogs = mat_b * (1 + fr) + conv_b
        purchases = purchases_b
        projected_cash = company["cash_on_hand_rm"] + rev - purchases * (1 + fr) - conv_b - fixed
        excess_rows = {m: 0.0 for m in P["usage"]}
        stress = _supplier_stress(P, 0.0, 0.0)
        for s in stress:
            s["affected"] = False

    cash_position = projected_cash - cost_impact - upfront          # Project Definition formula
    gross_profit = rev - cogs
    gm = gross_profit / rev * 100 if rev else 0.0
    gm_b = (rev_b - mat_b * (1 + fr) - conv_b) / rev_b * 100
    rar_pct = rar / rev_b * 100
    risk = _risk_level(A, gm_b - gm, rar_pct) if scenario else "Low"
    if not strategy or sid == "DO_NOTHING":
        feas = 1.0
    else:
        feas = feas_time * feas_cap

    # ---- headline items
    stopped_rows = [r for r in mat_rows.values() if r["stops_production"] and r["coverage_pct"] < 100]
    first_stop = min(stopped_rows, key=lambda r: r["runway_days"]) if stopped_rows else None
    crit = max(mat_rows.values(), key=lambda r: (r["affected_share_pct"] > 0, r["criticality"],
                                                  r["supply_gap_days"], -r["runway_days"]))
    excess_total = sum(excess_rows.values())

    S = lambda n: assumption_source(data, n)
    kpis = {
        "inventory_runway": {
            "label": "Inventory runway", "unit": "days", "value": crit["runway_days"],
            "formula": "stock on hand / daily usage (per material)",
            "inputs": {"material": f"{crit['material_id']} {crit['name']}", "stock_units": crit["stock_units"],
                       "daily_usage_units": crit["daily_usage_units"]},
            "source": SRC_DATA},
        "supply_gap": {
            "label": "Supply gap", "unit": "days", "value": max(0.0, crit["supply_gap_days"]) if scenario else 0.0,
            "formula": "new lead time - runway (production stops if > 0)",
            "inputs": {"material": crit["material_id"], "new_lead_time_days": crit["new_lead_time_days"],
                       "runway_days": crit["runway_days"], "after_strategy_coverage_pct": crit["coverage_pct"]},
            "source": SRC_DATA},
        "production_stop_date": {
            "label": "Production stop date", "unit": "date",
            "value": first_stop["stop_date"] if first_stop else None,
            "formula": "today + runway, when new lead time > runway",
            "inputs": {"today": today.isoformat(),
                       "material": first_stop["material_id"] if first_stop else None,
                       "runway_days": first_stop["runway_days"] if first_stop else None,
                       "new_lead_time_days": first_stop["new_lead_time_days"] if first_stop else None,
                       "restart_date": first_stop["restart_date"] if first_stop else None},
            "source": SRC_DATA},
        "cost_impact": {
            "label": "Cost impact", "unit": "RM", "value": _r(cost_impact),
            "formula": "sum(affected units x unit cost x price increase %) + extra freight",
            "inputs": {"by_material": ci_parts,
                       "freight_cost_pct_of_material": A["freight_cost_pct_of_material"],
                       "freight_increase_pct": dv.get("freight_increase_pct", 0)},
            "source": f"{SRC_DATA}; freight share: {S('freight_cost_pct_of_material')}"},
        "gross_margin": {
            "label": "Gross margin", "unit": "%", "value": _r(gm, 2),
            "formula": "(revenue - cost of goods) / revenue",
            "inputs": {"revenue_rm": _r(rev), "cost_of_goods_rm": _r(cogs), "horizon_days": H,
                       "conversion_cost_pct_of_price": A["conversion_cost_pct_of_price"]},
            "source": f"{SRC_DATA}; conversion cost: {S('conversion_cost_pct_of_price')}"},
        "revenue_at_risk": {
            "label": "Revenue at risk", "unit": "RM", "value": _r(rar),
            "formula": ("value of orders due inside the supply gap window" if stype != "demand"
                        else "value of orders cancelled by the demand drop (order book x demand drop)"),
            "inputs": {"orders_at_risk": len([o for o in orders_at_risk if o["at_risk_value_rm"] > 0]),
                       "order_book_rm": _r(order_book),
                       "window": ([first_stop["stop_date"], first_stop["restart_date"]] if first_stop else None)},
            "source": SRC_DATA},
        "cash_position": {
            "label": "Cash position", "unit": "RM", "value": _r(cash_position),
            "formula": "cash on hand - cost impact - strategy upfront cost "
                       "(cash on hand projected to the end of the horizon)",
            "inputs": {"opening_cash_rm": company["cash_on_hand_rm"], "revenue_rm": _r(rev),
                       "material_purchases_rm": _r(purchases * (1 + fr)),
                       "fixed_costs_rm": _r(fixed), "projected_cash_on_hand_rm": _r(projected_cash),
                       "cost_impact_rm": _r(cost_impact), "strategy_upfront_cost_rm": _r(upfront)},
            "source": SRC_DATA},
        "excess_inventory": {
            "label": "Excess inventory", "unit": "RM", "value": _r(excess_total),
            "formula": "(stock - reduced usage x horizon days) x unit cost, if positive "
                       "(stock = on hand + open purchase orders in the horizon)",
            "inputs": {"horizon_days": H, "by_material_rm": {m: _r(v) for m, v in excess_rows.items()}},
            "source": SRC_DATA},
        "business_risk": {
            "label": "Business risk level", "unit": "level", "value": risk,
            "formula": "High if margin drop >= {:.1f} pp or revenue at risk >= {:.0f}%; Medium if >= {:.1f} pp or >= {:.0f}%"
                       .format(A["risk_high_margin_drop_pp"], A["risk_high_revenue_at_risk_pct"],
                               A["risk_medium_margin_drop_pp"], A["risk_medium_revenue_at_risk_pct"]),
            "inputs": {"margin_drop_pp": _r(gm_b - gm, 2), "revenue_at_risk_pct": _r(rar_pct, 2)},
            "source": "assumptions.csv thresholds (illustrative)"},
    }
    kpis["cash_position"]["inputs"]["conversion_rm"] = _r(conv_b - (conv_save if stype == "demand" else 0.0))

    return {
        "today": today.isoformat(),
        "horizon_days": H,
        "scenario": scenario,
        "strategy_id": sid,
        "kpis": kpis,
        "financials": {
            "revenue_rm": _r(rev), "cost_of_goods_rm": _r(cogs), "gross_profit_rm": _r(gross_profit),
            "gross_margin_pct": _r(gm, 2), "baseline_revenue_rm": _r(rev_b), "baseline_gross_margin_pct": _r(gm_b, 2),
            "projected_cash_on_hand_rm": _r(projected_cash), "cost_impact_rm": _r(cost_impact),
            "upfront_cost_rm": _r(upfront), "ongoing_cost_rm": _r(ongoing), "cash_position_rm": _r(cash_position),
            "revenue_at_risk_rm": _r(rar), "excess_inventory_rm": _r(excess_total), "order_book_rm": _r(order_book),
            "feasibility": _r(feas, 3), "feasibility_time": _r(feas_time, 3), "feasibility_capacity": _r(feas_cap, 3),
        },
        "materials": list(mat_rows.values()),
        "orders_at_risk": sorted(orders_at_risk, key=lambda o: o["due_day"]),
        "stock_projection": stock_projection,
        "supplier_stress": stress,
        "strategy_effect": effect,
    }


# --------------------------------------------------------------------------- public API
CARD_KEYS = {
    "supply": ["production_stop_date", "revenue_at_risk", "cost_impact", "gross_margin", "cash_position"],
    "demand": ["excess_inventory", "revenue_at_risk", "cost_impact", "gross_margin", "cash_position"],
}


def run_baseline(data: dict, today: date | None = None) -> dict:
    return evaluate(data, None, None, today)


def run_scenario(data: dict, scenario: dict, today: date | None = None) -> dict:
    """Baseline vs scenario (with "Do nothing"), plus the 5 KPI cards for the Overview."""
    base = evaluate(data, None, None, today)
    scen = evaluate(data, scenario, None, today)
    cards = []
    for k in CARD_KEYS[scenario["type"]]:
        b, s = base["kpis"][k], scen["kpis"][k]
        card = {"key": k, "label": s["label"], "unit": s["unit"], "baseline": b["value"], "scenario": s["value"],
                "formula": s["formula"], "inputs": s["inputs"], "source": s["source"]}
        if isinstance(b["value"], (int, float)) and isinstance(s["value"], (int, float)):
            card["delta"] = _r(s["value"] - b["value"])
        else:
            card["delta"] = None
        if k == "production_stop_date":
            card["runway_days"] = s["inputs"]["runway_days"]
            card["supply_gap_days"] = scen["kpis"]["supply_gap"]["value"]
            card["material"] = s["inputs"]["material"]
            card["days_until_stop"] = (int(math.floor(s["inputs"]["runway_days"]))
                                       if s["inputs"]["runway_days"] is not None else None)
        cards.append(card)
    return {"baseline": base, "scenario": scen, "kpi_cards": cards,
            "risk_level": scen["kpis"]["business_risk"]["value"]}
