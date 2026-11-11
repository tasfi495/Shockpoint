"""Pydantic models for every request and response."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ----------------------------------------------------------------- requests
class Weights(BaseModel):
    value: float = Field(0.40, ge=0, le=1)
    cost: float = Field(0.25, ge=0, le=1)
    cash: float = Field(0.20, ge=0, le=1)
    feasibility: float = Field(0.15, ge=0, le=1)


class SimulateRequest(BaseModel):
    scenario_id: Literal["S1", "S2"]
    drivers: dict[str, Any] = Field(default_factory=dict)


class DecideRequest(SimulateRequest):
    weights: Weights = Field(default_factory=Weights)


class BriefRequest(DecideRequest):
    pass


class AskRequest(DecideRequest):
    question: str = Field(..., min_length=3, max_length=500)


class ParseEventRequest(BaseModel):
    headline: str = Field(..., min_length=10, max_length=400)


# ----------------------------------------------------------------- responses
class BaselineResponse(BaseModel):
    app: dict[str, Any]
    today: str
    company: dict[str, Any]
    location: dict[str, Any]
    baseline: dict[str, Any]
    scenarios: list[dict[str, Any]]
    strategies: list[dict[str, Any]]
    assumptions: list[dict[str, Any]]
    exposure: dict[str, Any]
    default_weights: dict[str, float]


class SimulateResponse(BaseModel):
    scenario: dict[str, Any]
    banner: dict[str, Any]
    kpi_cards: list[dict[str, Any]]
    risk_level: str
    baseline: dict[str, Any]
    result: dict[str, Any]
    exposure: dict[str, Any]
    top_recommendation: dict[str, Any]


class DecideResponse(BaseModel):
    scenario: dict[str, Any]
    weights: dict[str, float]
    weight_labels: dict[str, str]
    formula: str
    ranking: list[dict[str, Any]]
    recommendation: dict[str, Any]
    do_nothing: dict[str, Any]


class EventsResponse(BaseModel):
    label: str
    events: list[dict[str, Any]]
    source: Literal["demo", "live"] = "demo"
    note: Optional[str] = None


class AITextResponse(BaseModel):
    text: str
    source: Literal["gemini", "template"]
    label: str
    model: Optional[str] = None


class Evidence(BaseModel):
    """Why one setting got its value: the words in the headline that point to it."""
    setting: str
    value: str
    because: str


class ParsedEvent(BaseModel):
    """Structured output Gemini must return for a headline. Values outside the slider ranges are clamped by
    the engine; a missing (null) value means the headline does not say, so the scenario default is used."""
    relevant: bool  # false when the headline is not a supply or demand shock ShockPoint models
    scenario_id: Literal["S1", "S2"]
    affected_country: Literal["China", "Taiwan", "South Korea", "Japan", "Vietnam", "Malaysia", "Global"]
    severity: int                                   # 0-100: S1 % export capacity lost; S2 strength of the fall
    duration_days: Optional[int] = None             # S1, 1-45
    freight_increase_pct: Optional[int] = None      # S1, 0-200
    demand_drop_pct: Optional[int] = None           # S2, 0-60
    input_price_change_pct: Optional[int] = None    # S2, -20 to 20
    myr_usd_change_pct: Optional[int] = None        # S2, -15 to 15 (+ = stronger ringgit)
    evidence: list[Evidence]


class ParseEventResponse(BaseModel):
    headline: str
    parsed: Optional[ParsedEvent]
    scenario_id: Optional[str]
    drivers: dict[str, Any]
    from_headline: list[str] = []
    valid: bool
    errors: list[str]
    source: Literal["gemini", "template"]
    label: str
