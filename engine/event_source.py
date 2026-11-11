"""Live Monitor event source (demo feed, simulated events).

The only place events come from. Swapping in a real source (GDELT, a news API) means
changing get_events() in this file only.
"""
from __future__ import annotations

from .loader import load_all

FEED_LABEL = "Live Monitor (demo feed, simulated events)"


def to_drivers(data: dict, scenario_id: str, severity: float) -> dict:
    """Maps an event's severity (0-100) onto its scenario's severity driver; other drivers keep defaults."""
    sdef = data["scenarios"][scenario_id]
    drivers = {k: v["default"] for k, v in sdef["drivers"].items()}
    key = sdef["severity_driver"]
    spec = sdef["drivers"][key]
    drivers[key] = min(max(severity * sdef["severity_scale"], spec["min"]), spec["max"])
    return drivers


def get_events(data: dict | None = None) -> list[dict]:
    data = data or load_all()
    out = []
    for i, e in enumerate(sorted(data["events"], key=lambda x: x["timestamp"])):
        out.append({"index": i, "timestamp": e["timestamp"], "headline": e["headline"],
                    "scenario_id": e["scenario_id"], "severity": e["severity"],
                    "scenario_name": data["scenarios"][e["scenario_id"]]["name"],
                    "drivers": to_drivers(data, e["scenario_id"], e["severity"]), "label": FEED_LABEL})
    return out
