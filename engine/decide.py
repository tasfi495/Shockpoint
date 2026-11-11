"""Normalised criteria, transparent weighted score, ranking and template explanation.

Score_s = sum_c w_c * norm_c(s),  sum_c w_c = 1, each criterion scaled 0-1 across the strategies.
"""
from __future__ import annotations

DEFAULT_WEIGHTS = {"value": 0.40, "cost": 0.25, "cash": 0.20, "feasibility": 0.15}
CRITERIA = {  # weight key -> (criterion field, higher is better?)
    "value": ("value_protected_rm", True),
    "cost": ("cost_rm", False),
    "cash": ("cash_position_rm", True),
    "feasibility": ("feasibility", True),
}
LABELS = {"value": "Value protected", "cost": "Cost", "cash": "Cash impact", "feasibility": "Feasibility"}


def normalise_weights(weights: dict | None) -> dict:
    w = {k: max(0.0, float((weights or {}).get(k, DEFAULT_WEIGHTS[k]))) for k in DEFAULT_WEIGHTS}
    total = sum(w.values())
    if total <= 0:
        return dict(DEFAULT_WEIGHTS)
    return {k: v / total for k, v in w.items()}


def _norm(values: list[float], higher_better: bool) -> list[float]:
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return [1.0 for _ in values]
    return [((v - lo) / (hi - lo)) if higher_better else ((hi - v) / (hi - lo)) for v in values]


def _rm(x: float) -> str:
    x = float(x)
    if abs(x) >= 1_000_000:
        return f"RM {x / 1_000_000:.2f}M"
    if abs(x) >= 1_000:
        return f"RM {x / 1_000:.0f}k"
    return f"RM {x:,.0f}"


def explain(row: dict, scenario: dict, stock_day: float | None, dn: dict) -> str:
    """One plain sentence, filled from the numbers (no AI)."""
    b, c = row["breakdown"], row["criteria"]
    no_gap = scenario["type"] == "supply" and dn["breakdown"]["revenue_at_risk_rm"] <= 0
    if row["is_do_nothing"]:
        if no_gap:
            return (f"Do nothing: stock covers the delay, so no orders are at risk; gross margin is "
                    f"{dn['breakdown']['gross_margin_pct']:.1f}%.")
        if scenario["type"] == "supply":
            return (f"Do nothing: {_rm(dn['breakdown']['revenue_at_risk_rm'])} of orders stay at risk and gross margin "
                    f"is {dn['breakdown']['gross_margin_pct']:.1f}%.")
        return (f"Do nothing: {_rm(dn['breakdown']['excess_inventory_rm'])} of excess inventory and a cash position "
                f"of {_rm(dn['breakdown']['cash_position_rm'])}.")
    if scenario["type"] == "supply":
        later = f" plus {_rm(b['ongoing_cost_rm'])} over the horizon" if b["ongoing_cost_rm"] >= 500 else ""
        if no_gap and c["cost_rm"] <= 0:
            return f"{row['name']}: not needed, because stock already covers the delay."
        if no_gap:
            return (f"{row['name']}: there is no supply gap to fix; it adds {_rm(b['gross_profit_gain_rm'])} of gross profit "
                    f"but costs {_rm(c['cost_rm'])} in lost sales.")
        if row["criteria"]["feasibility"] <= 0 and row["effect"].get("notes"):
            return f"{row['name']}: does not help here. {row['effect']['notes']}"
        if b["revenue_at_risk_avoided_rm"] <= 0:
            return (f"{row['name']}: adds {_rm(b['gross_profit_gain_rm'])} of gross profit but leaves "
                    f"{_rm(b['revenue_at_risk_rm'])} of orders at risk; costs {_rm(b['upfront_cost_rm'])} now{later}.")
        arrival = row["effect"].get("arrival_day")
        timing = ""
        if stock_day is not None and arrival is not None:
            gap = stock_day - arrival
            timing = (f", and arrives {gap:.0f} days before stockout" if gap >= 0
                      else f", but arrives {-gap:.0f} days after stockout")
        return (f"{row['name']}: costs {_rm(b['upfront_cost_rm'])} now{later}, protects "
                f"{_rm(b['revenue_at_risk_avoided_rm'])} of orders{timing}.")
    return (f"{row['name']}: {'frees' if b['cash_vs_do_nothing_rm'] >= 0 else 'uses'} "
            f"{_rm(abs(b['cash_vs_do_nothing_rm']))} of cash vs doing nothing, leaves "
            f"{_rm(b['excess_inventory_rm'])} of excess inventory (do nothing: "
            f"{_rm(dn['breakdown']['excess_inventory_rm'])}), and costs {_rm(c['cost_rm'])}.")


def rank(results: list[dict], weights: dict | None = None, scenario: dict | None = None,
         stock_day: float | None = None) -> dict:
    w = normalise_weights(weights)
    norms = {k: _norm([r["criteria"][f] for r in results], hb) for k, (f, hb) in CRITERIA.items()}
    dn = next(r for r in results if r["is_do_nothing"])
    ranked = []
    for i, r in enumerate(results):
        parts = {k: round(w[k] * norms[k][i], 4) for k in w}
        row = {**r, "normalised": {k: round(norms[k][i], 4) for k in w}, "score_parts": parts,
               "score": round(sum(parts.values()), 4)}
        row["explanation"] = explain(row, scenario, stock_day, dn) if scenario else ""
        ranked.append(row)
    ranked.sort(key=lambda r: (-r["score"], r["criteria"]["cost_rm"]))
    for i, r in enumerate(ranked, 1):
        r["rank"] = i
    top = ranked[0]
    return {
        "weights": {k: round(v, 4) for k, v in w.items()},
        "weight_labels": LABELS,
        "formula": "Score = sum(w_c x norm_c), each criterion scaled 0-1 across strategies "
                   "(cost: lower is better); weights sum to 1",
        "ranking": ranked,
        "recommendation": {"strategy_id": top["id"], "name": top["name"], "score": top["score"],
                           "sentence": top["explanation"]},
        "do_nothing": next(r for r in ranked if r["is_do_nothing"]),
    }
