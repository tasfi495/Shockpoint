"""Applies each strategy (plus "Do nothing") and re-runs the scenario through the same simulation."""
from __future__ import annotations

from datetime import date

from .simulate import _r, evaluate


def applicable(data: dict, scenario: dict) -> list[dict]:
    return [s for s in data["strategies"] if s["scenario_type"] in ("all", scenario["type"])]


def run_all(data: dict, scenario: dict, today: date | None = None) -> list[dict]:
    """Returns one row per strategy with the four decision criteria in raw units."""
    dn = evaluate(data, scenario, None, today)
    dnf = dn["financials"]
    rows = []
    for strat in applicable(data, scenario):
        res = dn if strat["id"] == "DO_NOTHING" else evaluate(data, scenario, strat, today)
        f = res["financials"]
        rar_avoided = dnf["revenue_at_risk_rm"] - f["revenue_at_risk_rm"]
        # Value protected = extra gross profit vs Do nothing. Counted once: the margin on
        # orders saved is already inside gross profit, so it is not added to revenue saved.
        profit_gain = f["gross_profit_rm"] - dnf["gross_profit_rm"]
        strategy_ongoing = max(0.0, f["ongoing_cost_rm"] - dnf["ongoing_cost_rm"])
        rows.append({
            "id": strat["id"], "name": res["strategy_effect"].get("display_name") or strat["name"], "description": strat["description"],
            "is_do_nothing": strat["id"] == "DO_NOTHING",
            "feasibility_days": strat["feasibility_days"],
            "criteria": {
                "value_protected_rm": _r(profit_gain),
                "cost_rm": _r(f["upfront_cost_rm"] + strategy_ongoing),
                "cash_position_rm": f["cash_position_rm"],
                "feasibility": f["feasibility"],
            },
            "breakdown": {
                "revenue_at_risk_avoided_rm": _r(rar_avoided), "gross_profit_gain_rm": _r(profit_gain),
                "upfront_cost_rm": f["upfront_cost_rm"], "ongoing_cost_rm": _r(strategy_ongoing),
                "revenue_at_risk_rm": f["revenue_at_risk_rm"], "gross_margin_pct": f["gross_margin_pct"],
                "excess_inventory_rm": f["excess_inventory_rm"], "cash_position_rm": f["cash_position_rm"],
                "cash_vs_do_nothing_rm": _r(f["cash_position_rm"] - dnf["cash_position_rm"]),
                "feasibility_time": f["feasibility_time"], "feasibility_capacity": f["feasibility_capacity"],
            },
            "effect": res["strategy_effect"],
            "stop_date": res["kpis"]["production_stop_date"]["value"],
            "stock_projection": res["stock_projection"],
        })
    return rows
