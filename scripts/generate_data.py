"""Builds every file in /data with a fixed seed.

All company, supplier, order and event data is SYNTHETIC (fictional company).
Only the USD/MYR rate and the copper reference price in assumptions.csv are real,
with their sources cited.

Usage:
    python scripts/generate_data.py                 # dates relative to today (Malaysia time)
    python scripts/generate_data.py --as-of 2026-11-12
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from datetime import date, datetime, timedelta, time
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from faker import Faker

SEED = 42
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MYT = ZoneInfo("Asia/Kuala_Lumpur")


def write_csv(name: str, header: list[str], rows: list[list]) -> None:
    with open(DATA_DIR / name, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def write_json(name: str, obj) -> None:
    with open(DATA_DIR / name, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)


# Places a supply shock can hit: our supplier countries, plus Malaysia (Penang Port, where every import lands).
SUPPLY_AREAS = ["China", "Taiwan", "South Korea", "Japan", "Vietnam", "Malaysia"]


def main(as_of: date | None = None) -> None:
    as_of = as_of or datetime.now(MYT).date()
    rng = np.random.default_rng(SEED)
    random.seed(SEED)
    fake = Faker("en_US")
    Faker.seed(SEED)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ company.csv (1 row)
    write_csv("company.csv",
              ["name", "industry", "city", "cash_on_hand_rm", "monthly_fixed_cost_rm", "usd_revenue_share"],
              [["Mutiara Control Systems Sdn Bhd (fictional)", "Electronics manufacturing - control boards",
                "Penang", 2_400_000, 380_000, 0.45]])

    # ------------------------------------------------------------------ products.csv (3) + bom.csv (~10)
    products = [  # id, name, price_rm, monthly_volume
        ("P01", "HVAC Control Board HC-210", 82.0, 12_000),
        ("P02", "Motor Drive Controller MD-450", 122.0, 6_000),
        ("P03", "Smart Meter Control Board SM-120", 88.0, 9_000),
    ]
    bom = [
        ("P01", "M01", 1), ("P01", "M02", 1), ("P01", "M03", 1), ("P01", "M04", 1),
        ("P02", "M01", 1), ("P02", "M02", 2), ("P02", "M03", 1), ("P02", "M05", 2),
        ("P03", "M02", 1), ("P03", "M03", 1), ("P03", "M06", 1),
    ]
    write_csv("bom.csv", ["product_id", "material_id", "qty_per_unit"], [list(r) for r in bom])

    # ------------------------------------------------------------------ suppliers.csv (8 current + 4 alternatives)
    suppliers = [
        # id, name, country, lat, lon, material, share_pct, unit_cost_rm, lead_time_days, capacity/wk, is_alt, reliability, ship_route
        ("SUP01", "Shenzhen Huaxin Power Semiconductor", "China", 22.5431, 114.0579, "M02", 100, 6.50, 14, 9000, False, 0.92, "Yantian (Shenzhen) -> Penang Port"),
        ("SUP02", "Dongguan Lianda Circuit Technology", "China", 23.0207, 113.7518, "M03", 100, 9.00, 12, 7000, False, 0.90, "Yantian (Shenzhen) -> Penang Port"),
        ("SUP03", "Xiamen Jinlu Passive Components", "China", 24.4798, 118.0894, "M04", 100, 4.00, 10, 3500, False, 0.88, "Xiamen -> Penang Port"),
        ("SUP04", "Ningbo Haitong Connector", "China", 29.8683, 121.5440, "M05", 100, 3.50, 10, 3200, False, 0.72, "Ningbo -> Penang Port"),
        ("SUP05", "Formosa MicroLogic Corp.", "Taiwan", 24.8138, 120.9675, "M01", 70, 18.00, 12, 3600, False, 0.95, "Kaohsiung -> Penang Port"),
        ("SUP06", "Kansai Microdevices K.K.", "Japan", 34.6937, 135.5023, "M01", 30, 18.60, 12, 1800, False, 0.90, "Kobe -> Penang Port"),
        ("SUP07", "Hanbit Wireless Co.", "South Korea", 37.2636, 127.0286, "M06", 60, 24.00, 12, 1600, False, 0.93, "Busan -> Penang Port"),
        ("SUP08", "Bac Ninh Link Modules", "Vietnam", 21.1861, 106.0763, "M06", 40, 25.00, 12, 1200, False, 0.78, "Haiphong -> Penang Port"),
        ("ALT01", "Changwon Power Devices", "South Korea", 35.2280, 128.6811, "M02", 0, 7.15, 9, 8000, True, 0.94, "Busan -> Penang Port"),
        ("ALT02", "Kaohsiung PowerChip Ltd.", "Taiwan", 22.6273, 120.3014, "M02", 0, 7.00, 12, 2000, True, 0.89, "Kaohsiung -> Penang Port"),
        ("ALT03", "Pulau Circuit Works", "Malaysia", 5.3580, 100.3920, "M03", 0, 10.80, 4, 3000, True, 0.86, "Prai -> Bayan Lepas (road)"),
        ("ALT04", "Saigon Passive Tech", "Vietnam", 10.8231, 106.6297, "M04", 0, 4.40, 8, 2500, True, 0.84, "Cat Lai (HCMC) -> Penang Port"),
    ]
    write_csv("suppliers.csv",
              ["supplier_id", "name", "country", "lat", "lon", "material_id", "share_pct", "unit_cost_rm",
               "lead_time_days", "capacity_units_per_week", "is_alternative", "reliability", "ship_route"],
              [list(r) for r in suppliers])

    # ------------------------------------------------------------------ materials.csv (6)
    days_per_month = 30
    usage = {}
    for pid, _, _, vol in products:
        for p, m, q in bom:
            if p == pid:
                usage[m] = usage.get(m, 0) + q * vol / days_per_month
    materials = [  # id, name, unit, days of stock on hand, safety-stock days, criticality
        ("M01", "32-bit microcontroller (MCU)", "pcs", 25, 7, 3),
        ("M02", "Power management IC (PMIC)", "pcs", 16, 7, 3),
        ("M03", "6-layer bare PCB", "pcs", 30, 7, 2),
        ("M04", "Passive component kit (MLCC + resistors)", "kit", 40, 7, 1),
        ("M05", "Board connector set", "set", 35, 7, 1),
        ("M06", "Wi-Fi/BLE radio module", "pcs", 28, 7, 2),
    ]
    write_csv("materials.csv",
              ["material_id", "name", "unit", "stock_units", "daily_usage_units", "safety_stock_units", "criticality"],
              [[m, n, u, int(usage[m] * d), int(usage[m]), int(usage[m] * ss), c] for m, n, u, d, ss, c in materials])

    # weighted current unit cost per material (for products.csv unit_cost_rm)
    cur = [s for s in suppliers if not s[10]]
    mat_cost = {m: sum(s[7] * s[6] / 100 for s in cur if s[5] == m) for m, *_ in materials}
    conversion_pct, freight_pct = 0.30, 0.08          # also written to assumptions.csv
    prod_rows = []
    for pid, name, price, vol in products:
        mc = sum(q * mat_cost[m] for p, m, q in bom if p == pid)
        unit_cost = mc * (1 + freight_pct) + price * conversion_pct
        prod_rows.append([pid, name, price, vol, round(unit_cost, 2)])
    write_csv("products.csv", ["product_id", "name", "price_rm", "monthly_volume", "unit_cost_rm"], prod_rows)

    # ------------------------------------------------------------------ orders.csv (28 orders, due in next 60 days)
    countries = ["Malaysia", "Singapore", "Germany", "United States", "Japan", "Thailand", "Netherlands", "Australia"]
    customers = []
    for c in countries:
        nm = fake.company().replace(",", "")
        customers.append((f"{nm} ({c})", "MYR" if c == "Malaysia" else "USD"))
    price = {p[0]: p[2] for p in products}
    order_rows = []
    n_orders = 28
    for i in range(n_orders):
        due_day = 3 + int(round(i * 57 / (n_orders - 1)))       # spread over day 3..60
        pid = ["P01", "P02", "P03"][i % 3]
        cust, ccy = customers[int(rng.integers(0, len(customers)))]
        qty = int(rng.integers(8, 22)) * 100 if pid != "P02" else int(rng.integers(6, 16)) * 100
        order_rows.append([f"SO-{1001 + i}", cust, pid, qty, (as_of + timedelta(days=due_day)).isoformat(),
                           round(qty * price[pid], 2), ccy])
    write_csv("orders.csv", ["order_id", "customer", "product_id", "qty", "due_date", "value_rm", "currency"], order_rows)

    # ------------------------------------------------------------------ scenarios.json (2)
    scenarios = [
        {
            "id": "S1",
            "name": "Port closure / shipping disruption",
            "type": "supply",
            "category": "Port closure / shipping disruption",
            "description": "A typhoon, strike or other disruption shuts a port our supplies pass through. Shipments "
                           "from the affected suppliers cannot move until it reopens, so lead times stretch and freight "
                           "rates rise. Pick a supplier country, or Penang Port itself, where all our imports land.",
            "affected_countries": SUPPLY_AREAS,
            "precedent": "COVID-related shutdowns at Yantian port (Shenzhen) in 2021 delayed shipments for weeks.",
            "drivers": {
                "affected_country": {"label": "Affected country", "type": "select", "default": "China",
                                     "options": SUPPLY_AREAS},
                "severity_pct": {"label": "Severity (% export capacity lost)", "type": "range", "default": 85,
                                 "min": 0, "max": 100, "step": 5, "unit": "%"},
                "duration_days": {"label": "Duration", "type": "range", "default": 14, "min": 1, "max": 45,
                                  "step": 1, "unit": "days"},
                "freight_increase_pct": {"label": "Freight cost increase", "type": "range", "default": 60,
                                         "min": 0, "max": 200, "step": 5, "unit": "%"},
            },
            "multipliers": {"lead_time_delay_per_closed_day": 1.0, "input_price_increase_pct": 5},
            "severity_driver": "severity_pct",
            "severity_scale": 1.0,
            "epicentres": {
                "China": {"name": "Yantian Port (Shenzhen)", "lat": 22.575, "lon": 114.268,
                          "precedent": "COVID-related shutdowns at Yantian port (Shenzhen) in 2021 delayed shipments for weeks."},
                "Taiwan": {"name": "Kaohsiung Port", "lat": 22.613, "lon": 120.283,
                           "precedent": "Typhoon Krathon made landfall at Kaohsiung in October 2024 and temporarily shut Taiwan's major ports, including Kaohsiung."},
                "South Korea": {"name": "Busan Port", "lat": 35.104, "lon": 129.042,
                                "precedent": "Typhoon Hinnamnor closed Busan port in September 2022 and disrupted Asian shipping schedules."},
                "Japan": {"name": "Port of Kobe", "lat": 34.67, "lon": 135.21,
                          "precedent": "Typhoon Jebi flooded container terminals at Kobe and Osaka in September 2018 and shut Kansai Airport."},
                "Vietnam": {"name": "Port of Haiphong", "lat": 20.86, "lon": 106.69,
                            "precedent": "Super Typhoon Yagi closed Hai Phong's container terminals in September 2024; they took several days to reopen."},
                "Malaysia": {"name": "Penang Port", "lat": 5.42, "lon": 100.35, "route_port": "Penang Port",
                             "precedent": "Penang Port has had no full closure on record. The nearest case: monsoon floods in "
                                          "November 2025 closed roads and disrupted container traffic around Port Klang."},
            },
            "expected_advice": "Act early, secure supply",
        },
        {
            "id": "S2",
            "name": "Global electronics demand slump",
            "type": "demand",
            "category": "Global market downturn",
            "description": "End-market demand for electronics falls. Customers cut orders, so stock bought for the "
                           "old plan piles up and cash is tied up in inventory.",
            "affected_countries": ["Global"],
            "precedent": "The 2022-23 electronics and chip inventory glut after the pandemic demand boom.",
            "drivers": {
                "demand_drop_pct": {"label": "Demand drop", "type": "range", "default": 25, "min": 0, "max": 60,
                                    "step": 5, "unit": "%"},
                "input_price_change_pct": {"label": "Input price change", "type": "range", "default": -3,
                                           "min": -20, "max": 20, "step": 1, "unit": "%"},
                "myr_usd_change_pct": {"label": "Ringgit vs USD change (+ = stronger ringgit)", "type": "range",
                                       "default": 3, "min": -15, "max": 15, "step": 1, "unit": "%"},
                "supplier_failure_risk_pct": {"label": "Supplier failure risk", "type": "range", "default": 15,
                                              "min": 0, "max": 100, "step": 5, "unit": "%"},
            },
            "multipliers": {"lead_time_delay_per_closed_day": 0.0, "input_price_increase_pct": 0},
            "severity_driver": "demand_drop_pct",
            "severity_scale": 0.5,
            "epicentres": {"Global": {"name": "Customer markets (global)", "lat": 5.4164, "lon": 100.3327,
                                       "precedent": "The 2022-23 electronics and chip inventory glut after the pandemic demand boom."}},
            "expected_advice": "Hold back, protect cash",
        },
    ]
    write_json("scenarios.json", scenarios)

    # ------------------------------------------------------------------ strategies.json (4 per scenario + do nothing)
    strategies = [
        {"id": "DO_NOTHING", "scenario_type": "all", "name": "Do nothing",
         "description": "Keep current suppliers, orders and production plan. Shows the cost of inaction.",
         "upfront_cost": {"rule": "fixed", "amount_rm": 0},
         "lead_time_change": None, "cost_change_pct": 0, "stock_change": None, "feasibility_days": 0},
        {"id": "S1_BUY_EARLY_ALT", "scenario_type": "supply", "name": "Buy early from an alternative supplier",
         "description": "Place an emergency order now with the fastest alternative supplier outside the closed area, "
                        "enough to cover the supply gap plus a safety buffer of the stopped material.",
         "supplier_pick": "fastest",
         "upfront_cost": {"rule": "qty_x_alt_unit_cost",
                          "qty": "daily_usage x (supply_gap_days + feasibility_safety_buffer_days)"},
         "lead_time_change": {"rule": "set_to_supplier_lead_time"}, "cost_change_pct": 10,
         "stock_change": {"rule": "add_qty_on_arrival"}, "feasibility_days": 9},
        {"id": "S1_SWITCH_ALT", "scenario_type": "supply", "name": "Switch part of volume to a second alternative supplier",
         "description": "Qualify another alternative supplier outside the closed area and move volume of the stopped "
                        "material to it. Limited by its weekly capacity.",
         "supplier_pick": "second",
         "upfront_cost": {"rule": "fixed", "amount_rm": 12000, "note": "qualification + first-article inspection"},
         "lead_time_change": {"rule": "set_to_supplier_lead_time"}, "cost_change_pct": 7.7,
         "stock_change": {"rule": "add_capacity_limited_qty_on_arrival"}, "feasibility_days": 12},
        {"id": "S1_AIR_FREIGHT", "scenario_type": "supply", "name": "Air-freight critical parts",
         "description": "Fly the stopped material from the current supplier through the airport instead of the closed "
                        "port. Limited by booked air cargo space.",
         "upfront_cost": {"rule": "qty_x_air_surcharge", "surcharge_assumption": "air_freight_surcharge_rm_per_unit"},
         "lead_time_change": {"rule": "set_days", "days": 5}, "cost_change_pct": 0,
         "stock_change": {"rule": "add_air_capacity_limited_qty"}, "feasibility_days": 5},
        {"id": "S1_RAISE_PRICES", "scenario_type": "supply", "name": "Raise selling prices 5%",
         "description": "Pass the higher input and freight cost to customers. Does not fix the supply gap.",
         "upfront_cost": {"rule": "fixed", "amount_rm": 0},
         "lead_time_change": None, "cost_change_pct": 0, "stock_change": None, "feasibility_days": 14,
         "price_change_pct": 5},
        {"id": "S2_CUT_PO", "scenario_type": "demand", "name": "Cut purchase orders",
         "description": "Cancel open purchase orders in line with the demand drop, after the supplier notice period.",
         "upfront_cost": {"rule": "pct_of_cancelled_value", "assumption": "po_cancellation_fee_pct"},
         "lead_time_change": None, "cost_change_pct": 0,
         "stock_change": {"rule": "reduce_open_po_by_demand_drop_after_notice"}, "feasibility_days": 7},
        {"id": "S2_SLOW_PRODUCTION", "scenario_type": "demand", "name": "Slow production (cut shifts)",
         "description": "Drop overtime and one shift so variable conversion cost falls with volume.",
         "upfront_cost": {"rule": "fixed", "amount_rm": 25000, "note": "shift change and contract labour release"},
         "lead_time_change": None, "cost_change_pct": 0, "stock_change": None, "feasibility_days": 14},
        {"id": "S2_DISCOUNT", "scenario_type": "demand", "name": "Discount 10% to clear stock",
         "description": "Cut prices 10% to win back volume and use up stock. Margin per board falls.",
         "upfront_cost": {"rule": "fixed", "amount_rm": 0},
         "lead_time_change": None, "cost_change_pct": 0, "stock_change": {"rule": "volume_recovers_by_elasticity"},
         "feasibility_days": 3, "price_change_pct": -10},
        {"id": "S2_RENEGOTIATE", "scenario_type": "demand", "name": "Renegotiate supplier contracts",
         "description": "Negotiate 5% lower input prices for purchases after the negotiation period.",
         "upfront_cost": {"rule": "fixed", "amount_rm": 20000, "note": "legal and procurement time"},
         "lead_time_change": None, "cost_change_pct": -5, "stock_change": None, "feasibility_days": 21},
    ]
    write_json("strategies.json", strategies)

    # ------------------------------------------------------------------ assumptions.csv (~15)
    assumptions = [
        ("analysis_horizon_days", 60, "days", "illustrative"),
        ("days_per_month", 30, "days", "illustrative"),
        ("conversion_cost_pct_of_price", round(conversion_pct * 100), "%", "illustrative"),
        ("conversion_variable_share_pct", 25, "%", "illustrative"),
        ("freight_cost_pct_of_material", round(freight_pct * 100), "%", "illustrative"),
        ("holding_cost_pct_per_year", 20, "%", "illustrative"),
        ("excess_writedown_pct", 20, "%", "illustrative"),
        ("po_cancellation_fee_pct", 5, "%", "illustrative"),
        ("supplier_notice_days", 7, "days", "illustrative"),
        ("air_freight_surcharge_rm_per_unit", 1.80, "RM/unit", "illustrative"),
        ("air_cargo_capacity_share_pct", 35, "%", "illustrative"),
        ("price_elasticity", 1.0, "ratio", "illustrative"),
        ("feasibility_safety_buffer_days", 3, "days", "illustrative"),
        ("risk_high_margin_drop_pp", 4, "pp", "illustrative"),
        ("risk_high_revenue_at_risk_pct", 10, "%", "illustrative"),
        ("risk_medium_margin_drop_pp", 1.5, "pp", "illustrative"),
        ("risk_medium_revenue_at_risk_pct", 3, "%", "illustrative"),
        ("supplier_stress_threshold", 0.40, "score", "illustrative"),
        ("usd_myr_rate", 4.0582, "MYR per USD",
         "Trading Economics, USD/MYR on 30 Oct 2026: https://tradingeconomics.com/malaysia/currency"),
        ("copper_lme_usd_per_tonne", 13768, "USD/tonne",
         "LME 3-month copper close, reported 9 Nov 2026: https://kalkine.ca/news/general-news/copper-rebounds-as-global-growth-signals-clash-with-supply-constraints"),
    ]
    write_csv("assumptions.csv", ["name", "value", "unit", "source"], [list(a) for a in assumptions])

    # ------------------------------------------------------------------ events_feed.json (6, stretch)
    t0 = datetime.combine(as_of, time(8, 0), tzinfo=MYT)
    events = [
        (0, "Typhoon warning raised for Pearl River Delta; Yantian terminal suspends vessel berthing", "S1", 40),
        (25, "Yantian port operations halted as typhoon makes landfall near Shenzhen", "S1", 85),
        (70, "Port backlog grows: carriers announce 2-week delays on South China sailings", "S1", 95),
        (130, "Global PC and appliance makers report weaker orders for next quarter", "S2", 30),
        (190, "Chipmakers flag inventory glut as electronics demand slows sharply", "S2", 50),
        (250, "Major customers cut component orders by a quarter amid demand slump", "S2", 60),
    ]
    write_json("events_feed.json", [
        {"timestamp": (t0 + timedelta(minutes=m)).isoformat(), "headline": h, "scenario_id": s, "severity": sev}
        for m, h, s, sev in events])

    # meta.json: the engine uses this date as "today", so every number stays the same
    # until the data is regenerated (stable screenshots, deck figures and demo video).
    write_json("meta.json", {"as_of": as_of.isoformat(), "seed": SEED})

    print(f"Generated synthetic data in {DATA_DIR} (as of {as_of.isoformat()}, seed {SEED})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", help="YYYY-MM-DD; defaults to today in Malaysia time")
    a = ap.parse_args()
    main(date.fromisoformat(a.as_of) if a.as_of else None)
