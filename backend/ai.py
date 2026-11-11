"""All Gemini calls. The AI explains and assists; the engine decides. AI never produces a number.

Guardrails (Development Plan):
  * prompts say: use only numbers in the given JSON, never invent figures;
  * an extra check rejects any RM amount or % in the AI text that is not in the JSON;
  * event parsing uses structured JSON-schema output and values are checked against allowed values;
  * AI text is labelled "AI-generated summary";
  * if Gemini fails, is not configured or hits a rate limit, a template explanation is returned instead.
Only synthetic data is ever sent.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from engine.decide import _rm

log = logging.getLogger("shockpoint.ai")
DEFAULT_MODEL = "gemini-3.8-flash"
MODEL = os.getenv("GEMINI_MODEL") or DEFAULT_MODEL
AI_LABEL = "AI-generated summary"
TEMPLATE_LABEL = "Template summary (AI unavailable)"
_client = None


def _get_client():
    global _client
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return None
    if _client is None:
        from google import genai
        from google.genai import types
        _client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=30_000))   # 30 s, then the next model is tried
    return _client


def _version(name: str) -> tuple:
    """'models/gemini-3.8-flash' -> (3, 8) so newer models sort first."""
    m = re.search(r"gemini-(\d+)(?:\.(\d+))?", name)
    return (int(m.group(1)), int(m.group(2) or 0)) if m else (0, 0)


_SKIP = ("preview", "exp", "image", "tts", "live", "audio", "thinking", "embedding")
_fallbacks: list[str] | None = None
LAST_MODEL = MODEL          # the model that actually answered the last request


def _flash_models(client) -> list[str]:
    """Flash models this key can use: newest first, full Flash before Flash-Lite."""
    names = []
    for m in client.models.list():
        name = getattr(m, "name", "") or ""
        actions = getattr(m, "supported_actions", None) or []
        if "flash" in name and not any(k in name for k in _SKIP) and (not actions or "generateContent" in actions):
            names.append(name.split("/")[-1])
    return sorted(set(names), key=lambda n: ("lite" in n, tuple(-v for v in _version(n))))


def _fallback_models(client) -> list[str]:
    """Backup models to try when the main one is busy or unavailable (asked from Google once, then cached).
    Can be fixed with GEMINI_FALLBACK_MODELS=model-a,model-b in .env."""
    global _fallbacks
    if _fallbacks is None:
        env = [m.strip() for m in os.getenv("GEMINI_FALLBACK_MODELS", "").split(",") if m.strip()]
        try:
            _fallbacks = env or _flash_models(client)
        except Exception as e:  # noqa: BLE001
            log.warning("Could not list Gemini models: %s", e)
            _fallbacks = env
    return [m for m in _fallbacks if m != MODEL][:3]


def _is_busy(msg: str) -> bool:
    return any(c in msg for c in ("503", "504", "UNAVAILABLE", "DEADLINE_EXCEEDED", "high demand"))


def _is_missing(msg: str) -> bool:
    return "404" in msg or "NOT_FOUND" in msg


def _complete_text(resp, is_json: bool) -> str:
    """Gemini reply -> text, trimmed to its last full sentence if it was cut off."""
    cut = False
    try:
        cut = "MAX_TOKENS" in str(resp.candidates[0].finish_reason)
    except Exception:  # noqa: BLE001
        pass
    return _finish_text(resp.text, is_json, cut)


def _finish_text(text, is_json: bool, cut: bool) -> str:
    """Rejects empty replies; trims a cut-off reply to its complete sentences (needs at least 2)."""
    text = (text or "").strip()
    if not text:
        raise RuntimeError("empty response")
    if is_json:
        return text
    if cut or text[-1] not in ".!?":
        # a sentence ends at . ! or ? followed by a space (so "RM 3.15M" is not split)
        parts = re.split(r"(?<=[.!?])\s+", text)
        sentences = [p for p in parts if p.rstrip().endswith((".", "!", "?"))]
        if parts and not parts[-1].rstrip().endswith((".", "!", "?")):
            sentences = sentences[:len(parts) - 1]
        if len(sentences) < 2:
            raise RuntimeError("reply was cut off before a complete answer")
        text = " ".join(sentences).strip()
        log.warning("AI reply was cut off; kept the %d complete sentences", len(sentences))
    return text


def _gemini_generate(prompt: str, system: str, schema=None) -> str:
    """Calls Gemini. If the main model is busy, overloaded or retired, tries up to 3 other Flash models."""
    global LAST_MODEL
    from google.genai import types
    client = _get_client()
    if client is None:
        raise RuntimeError("GEMINI_API_KEY not set")

    def config(model: str, thinking: bool):
        cfg = {"system_instruction": system, "max_output_tokens": 4096,   # thinking counts toward this limit
               "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True)}
        if schema is not None:
            cfg.update(response_mime_type="application/json", response_schema=schema)
        if thinking:
            # short summaries need little reasoning; low thinking keeps replies fast
            cfg["thinking_config"] = (types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW)
                                      if _version(model) >= (3, 0) else types.ThinkingConfig(thinking_budget=0))
        return types.GenerateContentConfig(**cfg)

    def call(model: str):
        try:
            return client.models.generate_content(model=model, contents=prompt, config=config(model, True))
        except Exception as e:  # noqa: BLE001
            if "INVALID_ARGUMENT" in str(e) and "thinking" in str(e).lower():
                return client.models.generate_content(model=model, contents=prompt, config=config(model, False))
            raise

    last_error = None
    tried = [MODEL]
    candidates = [MODEL]
    i = 0
    while i < len(candidates):
        model = candidates[i]
        i += 1
        try:
            resp = call(model)
            text = _complete_text(resp, schema is not None)
            if model != MODEL:
                log.warning("Answered by backup model %s (main model %s was busy or unavailable)", model, MODEL)
            LAST_MODEL = model
            return text
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            last_error = e
            if not (_is_busy(msg) or _is_missing(msg)):
                raise
            log.warning("Gemini model %s %s; trying another model", model, "is busy" if _is_busy(msg) else "is not available")
            if len(candidates) == 1:                             # first failure: line up the backups
                candidates += [m for m in _fallback_models(client) if m not in tried]
                tried += candidates[1:]
    raise last_error


# ----------------------------------------------------------------- backup AI (xAI Grok or Groq)
# Used only when Gemini fails. Both speak the OpenAI chat format; the key prefix says which one it is:
#   xai-...  -> xAI Grok (https://api.x.ai/v1)      gsk_... -> Groq (https://api.groq.com/openai/v1)
BACKUP_PROVIDERS = {
    "xai": {"label": "Grok", "base": "https://api.x.ai/v1", "default": "grok-4-fast-non-reasoning",
            "prefer": ("fast-non-reasoning", "fast", "mini", "grok")},
    "groq": {"label": "Groq", "base": "https://api.groq.com/openai/v1", "default": "llama-3.3-70b-versatile",
             "prefer": ("llama-3.3-70b", "gpt-oss-120b", "llama-4", "llama")},
}
_backup_model: str | None = None


def _backup_config():
    key = os.getenv("GROK_API_KEY") or os.getenv("XAI_API_KEY") or os.getenv("GROQ_API_KEY")
    if not key:
        return None
    name = os.getenv("BACKUP_AI_PROVIDER") or ("groq" if key.startswith("gsk_") else "xai")
    prov = BACKUP_PROVIDERS.get(name, BACKUP_PROVIDERS["xai"])
    return {"key": key, **prov, "model": _backup_model or os.getenv("BACKUP_AI_MODEL") or prov["default"]}


def _backup_pick_model(cfg: dict, httpx) -> str | None:
    """Asks the provider which models this key can use and picks one by preference."""
    r = httpx.get(f"{cfg['base']}/models", headers={"Authorization": f"Bearer {cfg['key']}"}, timeout=20)
    r.raise_for_status()
    ids = [m.get("id", "") for m in r.json().get("data", [])]
    ids = [i for i in ids if not any(k in i for k in ("vision", "image", "whisper", "tts", "guard", "embed"))]
    for want in cfg["prefer"]:
        hits = sorted(i for i in ids if want in i)
        if hits:
            return hits[-1]
    return ids[0] if ids else None


def _backup_generate(prompt: str, system: str, schema=None) -> str:
    global _backup_model, LAST_MODEL
    import httpx
    cfg = _backup_config()
    if cfg is None:
        raise RuntimeError("no backup AI key set")
    user = prompt
    if schema is not None:
        user += ("\n\nReply with JSON only (no code fences), matching this JSON schema exactly:\n"
                 + json.dumps(schema.model_json_schema()))

    def call(model: str):
        body = {"model": model, "temperature": 0.3, "max_tokens": 1500,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if schema is not None:
            body["response_format"] = {"type": "json_object"}
        return httpx.post(f"{cfg['base']}/chat/completions", json=body, timeout=45,
                          headers={"Authorization": f"Bearer {cfg['key']}"})

    model = cfg["model"]
    r = call(model)
    if r.status_code in (400, 404) and "model" in r.text.lower():
        new = _backup_pick_model(cfg, httpx)                    # model name retired: use one the key can use
        if new and new != model:
            log.warning("%s model %s is not available; switching to %s", cfg["label"], model, new)
            model = _backup_model = new
            r = call(model)
    if r.status_code >= 400:
        raise RuntimeError(f"{cfg['label']} {r.status_code}: {r.text[:200]}")
    choice = r.json()["choices"][0]
    text = choice.get("message", {}).get("content") or ""
    if schema is not None:
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    text = _finish_text(text, schema is not None, choice.get("finish_reason") == "length")
    LAST_MODEL = f"{cfg['label']}: {model}"
    return text


def _generate(prompt: str, system: str, schema=None) -> str:
    """Gemini first (with its own backup models); if Gemini fails for any reason, the Grok/Groq backup."""
    try:
        return _gemini_generate(prompt, system, schema)
    except Exception as e:  # noqa: BLE001
        if _backup_config() is None:
            raise
        log.warning("Gemini failed (%s); using the backup AI", str(e)[:80])
        return _backup_generate(prompt, system, schema)


# ----------------------------------------------------------------- number guardrail
def _numbers_in(obj: Any, out: list[float]) -> list[float]:
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.append(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            _numbers_in(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _numbers_in(v, out)
    elif isinstance(obj, str):
        for m in re.findall(r"-?\d[\d,]*\.?\d*", obj):
            try:
                out.append(float(m.replace(",", "")))
            except ValueError:
                pass
        # amounts written inside engine sentences ("frees RM 483k of cash") count at full size too
        out.extend(_claimed_numbers(obj))
    return out


def _claimed_numbers(text: str) -> list[float]:
    """RM amounts and percentages written in the AI text."""
    vals = []
    for num, suf in re.findall(r"RM\s?(-?\d[\d,]*\.?\d*)\s?([kKmM]?)", text):
        v = float(num.replace(",", ""))
        vals.append(v * (1_000 if suf in "kK" and suf else 1_000_000 if suf in "mM" and suf else 1))
    for num in re.findall(r"(-?\d+\.?\d*)\s?%", text):
        vals.append(float(num))
    return vals


def numbers_grounded(text: str, results: dict) -> bool:
    known = [abs(x) for x in _numbers_in(results, [])]
    for c in _claimed_numbers(text):
        c = abs(c)
        if c == 0:
            continue
        if not any(abs(k - c) <= max(0.012 * k, 0.051) or (c >= 1000 and abs(k - c) <= 0.05 * k) for k in known):
            log.warning("AI number %s not found in results JSON; using template", c)
            return False
    return True


# ----------------------------------------------------------------- compact results for prompts
def compact(sim: dict, decision: dict) -> dict:
    return {
        "scenario": sim["scenario"],
        "risk_level": sim["risk_level"],
        "kpis_baseline_vs_scenario": [{k: c.get(k) for k in ("label", "unit", "baseline", "scenario", "delta")}
                                      for c in sim["kpi_cards"]],
        "strategies_ranked": [{"rank": r["rank"], "name": r["name"], "score": r["score"],
                               "value_protected_rm": r["criteria"]["value_protected_rm"],
                               "cost_rm": r["criteria"]["cost_rm"],
                               "cash_position_rm": r["criteria"]["cash_position_rm"],
                               "feasibility": r["criteria"]["feasibility"],
                               "explanation": r["explanation"]} for r in decision["ranking"]],
        "recommendation": decision["recommendation"]["sentence"],
        "weights": decision["weights"],
        "currency": "RM (Malaysian ringgit)",
        "data_note": "All company data is simulated (fictional company).",
    }


def _fmt(v, unit: str = "") -> str:
    """Display formatting so Gemini copies tidy numbers (RM 924k, 22.9%) instead of raw floats."""
    if v is None:
        return "none"
    if unit == "RM":
        return _rm(v)
    if unit == "%":
        return f"{v:.1f}%"
    if unit == "days":
        return f"{v:.0f} days"
    if unit == "date":
        from datetime import date as _d
        d = _d.fromisoformat(v)
        return f"{d.day} {d.strftime('%b %Y')}"
    return str(v)


def _change(card: dict) -> str:
    """Scenario minus baseline, written the way the KPI card shows it (RM 635k lower, 4.7 pp lower)."""
    d = card.get("delta")
    if not isinstance(d, (int, float)) or isinstance(d, bool):
        return "none"
    if abs(d) < 1e-9:
        return "no change"
    word = "higher" if d > 0 else "lower"
    if card["unit"] == "RM":
        return f"{_rm(abs(d))} {word}"
    if card["unit"] == "%":
        return f"{abs(d):.1f} percentage points {word}"
    if card["unit"] == "days":
        return f"{abs(d):.0f} days {word}"
    return "none"


def compact_display(sim: dict, decision: dict) -> dict:
    sc = sim["scenario"]
    drivers = {}
    for k, v in sc["drivers"].items():
        drivers[k] = (f"{v:.0f}%" if k.endswith("_pct") else f"{v:.0f} days" if k.endswith("_days") else v)
    return {
        "scenario": {"title": sc["name"], "type": f"{sc['type']} shock", "settings": drivers},
        "risk_level": sim["risk_level"],
        "kpis_baseline_vs_scenario": [{"kpi": c["label"], "baseline": _fmt(c["baseline"], c["unit"]),
                                       "scenario": _fmt(c["scenario"], c["unit"]),
                                       "change": _change(c)} for c in sim["kpi_cards"]],
        "strategies_ranked": [{"rank": r["rank"], "name": r["name"], "score": f"{r['score']:.2f}",
                               "value_protected": _rm(r["criteria"]["value_protected_rm"]),
                               "cost": _rm(r["criteria"]["cost_rm"]),
                               "cash_position_after": _rm(r["criteria"]["cash_position_rm"]),
                               "feasibility_0_to_1": f"{r['criteria']['feasibility']:.2f}",
                               "explanation": r["explanation"]} for r in decision["ranking"]],
        "recommendation": decision["recommendation"]["sentence"],
        "criteria_weights": {k: f"{v:.0%}" for k, v in decision["weights"].items()},
        "currency": "RM (Malaysian ringgit)",
        "data_note": "All company data is simulated (fictional company).",
    }


def template_brief(sim: dict, decision: dict) -> str:
    cards = {c["key"]: c for c in sim["kpi_cards"]}
    dn = decision["do_nothing"]
    top = decision["ranking"][0]
    rar = cards["revenue_at_risk"]["scenario"]
    first = (f"Scenario '{sim['scenario']['name']}' puts the business at {sim['risk_level']} risk: "
             f"gross margin moves from {cards['gross_margin']['baseline']:.1f}% to {cards['gross_margin']['scenario']:.1f}% "
             + (f"and {_rm(rar)} of revenue is at risk." if rar > 0 else "and no customer orders are at risk."))
    if sim["scenario"]["type"] == "supply" and cards.get("production_stop_date", {}).get("scenario"):
        first += f" Production stops on {cards['production_stop_date']['scenario']} if nothing changes."
    if sim["scenario"]["type"] == "demand":
        first += f" Excess inventory reaches {_rm(cards['excess_inventory']['scenario'])}."
    return " ".join([
        first,
        f"Doing nothing leaves the cash position at {_rm(dn['criteria']['cash_position_rm'])}.",
        f"Recommended: {decision['recommendation']['sentence']}",
        f"It ranks first with a weighted score of {top['score']:.2f} (value {decision['weights']['value']:.0%}, "
        f"cost {decision['weights']['cost']:.0%}, cash {decision['weights']['cash']:.0%}, "
        f"feasibility {decision['weights']['feasibility']:.0%}).",
    ])


# ----------------------------------------------------------------- public functions
SYSTEM_BRIEF = ("You are ShockPoint's business analyst writing for a Malaysian manufacturer's operations and finance "
                "managers. Use ONLY numbers that appear in the JSON you are given, copied exactly as they are written "
                "there (they are already formatted, for example 'RM 924k' or '22.9%'). Never invent, estimate, round or "
                "calculate new figures. Plain English, no markdown, no bullet points, no headings. Always finish with a "
                "complete sentence.")


def brief(sim: dict, decision: dict) -> dict:
    data = compact(sim, decision)
    shown = compact_display(sim, decision)
    prompt = ("Write an executive briefing of 5 to 6 complete sentences (about 110 to 150 words) from these ShockPoint "
              "engine results, as one paragraph. Cover, in order: what the event does to the business (the key "
              "numbers), the cost of doing nothing, the top-ranked response and why it ranks first, its trade-off "
              "against the next best option, and the main risk to watch.\n\n"
              f"RESULTS JSON:\n{json.dumps(shown)}")
    try:
        text = _generate(prompt, SYSTEM_BRIEF)
        if numbers_grounded(text, {"raw": data, "shown": shown}):
            return {"text": text, "source": "gemini", "label": f"{AI_LABEL} ({LAST_MODEL})", "model": LAST_MODEL}
    except Exception as e:  # noqa: BLE001 - any failure falls back to the template
        log.warning("Gemini brief failed: %s", e)
    return {"text": template_brief(sim, decision), "source": "template", "label": TEMPLATE_LABEL, "model": None}


def ask(question: str, sim: dict, decision: dict) -> dict:
    data = compact(sim, decision)
    shown = compact_display(sim, decision)
    prompt = (f"Answer the user's question in 2 to 4 complete sentences, grounded only in these results. If the "
              f"results cannot answer it, say so and suggest which slider or scenario to run in ShockPoint.\n\n"
              f"QUESTION: {question}\n\nRESULTS JSON:\n{json.dumps(shown)}")
    try:
        text = _generate(prompt, SYSTEM_BRIEF)
        if numbers_grounded(text, {"raw": data, "shown": shown}):
            return {"text": text, "source": "gemini", "label": f"{AI_LABEL} ({LAST_MODEL})", "model": LAST_MODEL}
    except Exception as e:  # noqa: BLE001
        log.warning("Gemini ask failed: %s", e)
    return {"text": ("The AI assistant is unavailable right now, so here is the engine's own answer. "
                     + template_brief(sim, decision)),
            "source": "template", "label": TEMPLATE_LABEL, "model": None}


SUPPLY_WORDS = ("port", "shipping", "ship ", "vessel", "container", "freight", "typhoon", "storm", "flood",
                "earthquake", "strike", "lockdown", "closure", "closed", "closes", "shut", "halt", "suspend",
                "blockade", "export ban", "export restriction", "export curb", "congestion", "backlog", "berthing",
                "shortage", "disrupt")
DEMAND_WORDS = ("demand", "orders cut", "cut orders", "cut component orders", "slump", "glut", "downturn",
                "recession", "weaker orders", "order cuts", "sales fall", "sales drop", "spending falls")
# Malaysia first: "Penang Port" must not fall through to another country's words.
PLACE_WORDS = {"Malaysia": ("penang", "butterworth", "port klang", "malaysia", "strait of malacca", "malacca strait"),
               "China": ("china", "chinese", "shenzhen", "yantian", "shanghai", "ningbo", "guangzhou", "xiamen",
                         "pearl river", "south china", "hong kong"),
               "Taiwan": ("taiwan", "taiwanese", "kaohsiung", "keelung", "taichung", "taipei"),
               "South Korea": ("korea", "korean", "busan", "incheon", "ulsan", "changwon"),
               "Japan": ("japan", "japanese", "kobe", "osaka", "yokohama", "tokyo", "nagoya", "kansai"),
               "Vietnam": ("vietnam", "vietnamese", "haiphong", "hai phong", "ho chi minh", "hcmc", "cat lai",
                           "quang ninh")}
ELECTRONICS_WORDS = ("electronic", "chip", "semiconductor", "component", "pc ", "pcs", "appliance", "smartphone",
                     "device", "consumer tech", "gadget", "hvac", "meter", "motor")
SUPPLY_AREAS = ["China", "Taiwan", "South Korea", "Japan", "Vietnam", "Malaysia"]


def _country_in(h: str) -> tuple[str, str] | tuple[None, None]:
    for country, words in PLACE_WORDS.items():
        for w in words:
            if w in h:
                return country, w
    return None, None


def _pct_near(h: str, words: tuple[str, ...]) -> tuple[int, str] | tuple[None, None]:
    """First 'N%' (or 'by a quarter/third/half') within a few words of a keyword."""
    for w in words:
        i = h.find(w)
        if i < 0:
            continue
        window = h[max(0, i - 40): i + len(w) + 40]
        m = re.search(r"(\d{1,3})\s*(?:%|per ?cent)", window)
        if m:
            return int(m.group(1)), m.group(0).strip()
        for word, val in (("half", 50), ("a third", 33), ("a quarter", 25), ("a fifth", 20)):
            if word in window:
                return val, word
    return None, None


def _rule_parse(headline: str) -> dict:
    """Keyword fallback used only when Gemini is unavailable. Unrelated headlines come back with relevant=False.
    Every value it sets carries the words that set it (evidence); anything not in the headline stays null."""
    h = f" {headline.lower()} "
    empty = {"duration_days": None, "freight_increase_pct": None, "demand_drop_pct": None,
             "input_price_change_pct": None, "myr_usd_change_pct": None}
    demand = any(w in h for w in DEMAND_WORDS) and any(w in h for w in ELECTRONICS_WORDS + ("customers", "global"))
    country, place = _country_in(h)
    supply = any(w in h for w in SUPPLY_WORDS) and country is not None
    if not demand and not supply:
        return {"relevant": False, "scenario_id": "S1", "affected_country": "China", "severity": 0,
                **empty, "evidence": []}
    ev = []
    out = {"relevant": True, **empty}
    if demand:
        out.update(scenario_id="S2", affected_country="Global")
        drop, said = _pct_near(h, ("cut", "drop", "fall", "down", "slump", "lower"))
        if drop is None and any(w in h for w in ("sharp", "plunge", "collapse")):
            drop, said = 40, next(w for w in ("sharp", "plunge", "collapse") if w in h)
        if drop is not None:
            out["demand_drop_pct"] = drop
            ev.append({"setting": "Demand drop", "value": f"{drop}%", "because": f"'{said}'"})
        out["severity"] = int(min(100, (drop or 25) * 2))
        trig = next(w for w in DEMAND_WORDS if w in h)
        ev.insert(0, {"setting": "Type", "value": "Demand shock", "because": f"'{trig.strip()}'"})
        ring, said = _pct_near(h, ("ringgit",))
        if ring is not None:
            sign = -1 if any(w in h for w in ("ringgit falls", "ringgit weak", "ringgit drops", "weaker ringgit")) else 1
            out["myr_usd_change_pct"] = sign * ring
            ev.append({"setting": "Ringgit vs USD", "value": f"{sign * ring:+d}%", "because": f"'{said}'"})
    else:
        out.update(scenario_id="S1", affected_country=country)
        trig = next(w for w in SUPPLY_WORDS if w in h)
        ev.append({"setting": "Type", "value": "Supply shock", "because": f"'{trig.strip()}'"})
        ev.append({"setting": "Place", "value": country, "because": f"'{place}'"})
        hard = next((w for w in ("halt", "closed", "closes", "shut", "suspend", "blockade") if w in h), None)
        out["severity"] = 85 if hard else 50
        ev.append({"setting": "Severity", "value": f"{out['severity']}%",
                   "because": f"'{hard}' means a full stop" if hard else "a disruption without a full stop"})
        days = re.search(r"(\d+|two|three|four|a)\s*(?:-|\s)?(day|week)s?", h)
        if days:
            n = {"a": 1, "two": 2, "three": 3, "four": 4}.get(days.group(1)) or int(days.group(1))
            dur = n * (7 if days.group(2) == "week" else 1)
            out["duration_days"] = max(1, min(45, dur))
            ev.append({"setting": "Duration", "value": f"{out['duration_days']} days", "because": f"'{days.group(0)}'"})
        fr, said = _pct_near(h, ("freight", "shipping rate", "surcharge", "container rate"))
        if fr is not None:
            out["freight_increase_pct"] = fr
            ev.append({"setting": "Freight cost increase", "value": f"{fr}%", "because": f"'{said}'"})
    out["evidence"] = ev
    return out


SYSTEM_PARSE = ("You turn a news headline into a ShockPoint scenario for an electronics maker in Penang, Malaysia. "
                "ShockPoint models only two kinds of event.\n"
                "S1 = supply shock: a port closure, shipping disruption, disaster, strike or export restriction that "
                "stops goods leaving one of our supplier countries (China, Taiwan, South Korea, Japan, Vietnam) or "
                "stops imports landing at Penang Port / Malaysian ports (affected_country 'Malaysia').\n"
                "S2 = global demand shock: customers buying fewer electronics or cutting component orders "
                "(affected_country 'Global').\n"
                "Set relevant=false for anything else: sports, politics with no trade effect, company news, events "
                "in other countries, price moves alone, or good news.\n"
                "Fill a setting ONLY when the headline gives a clue for it; otherwise return null so the model uses "
                "its default. Settings: severity 0-100 (S1: % of export capacity lost, about 85 for a full closure, "
                "40-60 for partial disruption; S2: strength of the fall); S1 duration_days 1-45 and "
                "freight_increase_pct 0-200; S2 demand_drop_pct 0-60, input_price_change_pct -20 to 20, "
                "myr_usd_change_pct -15 to 15 (+ = stronger ringgit).\n"
                "In evidence, list each setting you filled (including Type and Place) with its value and the exact "
                "words from the headline that justify it, in quotes. Never invent words that are not in the headline.")


NOT_RELEVANT = ("This headline is not a shock ShockPoint models. Try a port closure or shipping disruption in "
                "China, Taiwan, South Korea, Japan, Vietnam or at Penang Port, or a fall in global electronics demand.")


def parse_event(headline: str) -> tuple[dict | None, str, list[str]]:
    """Returns (parsed dict or None, source, errors). Values are validated by the caller's schema."""
    from .schemas import ParsedEvent
    errors: list[str] = []
    try:
        raw = _generate(f"Headline: {headline}", SYSTEM_PARSE, schema=ParsedEvent)
        parsed = ParsedEvent.model_validate_json(raw)
        if not parsed.relevant:
            errors.append(NOT_RELEVANT)
            return None, "gemini", errors
        if parsed.scenario_id == "S2" and parsed.affected_country != "Global":
            parsed.affected_country = "Global"
        if parsed.scenario_id == "S1" and parsed.affected_country == "Global":
            errors.append("A supply shock must name one of: " + ", ".join(SUPPLY_AREAS) + "; rejected.")
            return None, "gemini", errors
        return parsed.model_dump(), "gemini", errors
    except Exception as e:  # noqa: BLE001
        log.warning("Gemini parse_event failed: %s", e)
        reason = ("No AI key set" if _get_client() is None and _backup_config() is None
                  else "AI unavailable or returned invalid values")
        errors.append(f"{reason}; keyword rules used instead.")
    try:
        rule = ParsedEvent.model_validate(_rule_parse(headline))
        if not rule.relevant:
            errors.append(NOT_RELEVANT)
            return None, "template", errors
        return rule.model_dump(), "template", errors
    except Exception as e:  # noqa: BLE001
        errors.append(f"Could not parse headline: {e}")
        return None, "template", errors
