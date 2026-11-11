"""Real headlines for the Live Monitor, from the free GDELT DOC 2.0 API (no key, no sign-up).

GDELT allows about one request every 5 seconds and sometimes refuses requests, so:
  * results are cached for 30 minutes (one fetch serves every visitor);
  * any failure returns an error string, and the caller falls back to the demo feed.
Only headline text, link, source site and time are kept. Nothing about the company is ever sent.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

import httpx

log = logging.getLogger("shockpoint.news")

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
QUERIES = [
    # supply side: port and shipping disruptions (the keyword rules then keep only our supplier places)
    '("port closure" OR "port closed" OR "port shut" OR "ports closed" OR "port strike" OR "shipping disruption" '
    'OR "port congestion" OR "suspends port" OR "halts port") sourcelang:english',
    # demand side: falling electronics demand
    '("electronics demand" OR "chip demand" OR "inventory glut" OR "order cuts" OR "weaker demand" '
    'OR "demand slump") sourcelang:english',
]
TIMESPAN = "7d"
CACHE_SECONDS = 30 * 60
GAP_SECONDS = 5.5            # GDELT asks for at most one request every 5 seconds
TIMEOUT = 12.0

_cache: dict = {"at": 0.0, "items": [], "error": None}
_lock = threading.Lock()


def _parse_time(seen: str) -> str:
    """GDELT 'seendate' is like 20261112T043000Z -> ISO 8601 in UTC."""
    try:
        return datetime.strptime(seen, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return datetime.now(timezone.utc).isoformat()


def _fetch(query: str) -> list[dict]:
    params = {"query": query, "mode": "artlist", "format": "json", "maxrecords": 50,
              "timespan": TIMESPAN, "sort": "datedesc"}
    r = httpx.get(GDELT_URL, params=params, timeout=TIMEOUT, headers={"User-Agent": "ShockPoint/1.0 (hackathon demo)"})
    r.raise_for_status()
    try:
        data = r.json()                      # a throttled reply is plain text, not JSON
    except ValueError as e:
        raise RuntimeError(f"GDELT did not return JSON: {r.text[:80]!r}") from e
    out = []
    for a in data.get("articles", []) or []:
        title = " ".join(str(a.get("title", "")).split())
        if len(title) < 15:
            continue
        out.append({"headline": title, "url": a.get("url"), "domain": a.get("domain"),
                    "timestamp": _parse_time(a.get("seendate"))})
    return out


def live_headlines(force: bool = False) -> tuple[list[dict], str | None, float]:
    """Returns (headlines newest first, error or None, cache age in seconds)."""
    with _lock:
        age = time.time() - _cache["at"]
        if not force and _cache["at"] and age < CACHE_SECONDS:
            return _cache["items"], _cache["error"], age
        items, errors = [], []
        for i, q in enumerate(QUERIES):
            if i:
                time.sleep(GAP_SECONDS)
            try:
                items += _fetch(q)
            except Exception as e:  # noqa: BLE001 - any failure means "use the demo feed"
                log.warning("GDELT fetch failed: %s", e)
                errors.append(str(e)[:120])
        seen, uniq = set(), []
        for it in sorted(items, key=lambda x: x["timestamp"], reverse=True):
            key = it["headline"].lower()
            if key not in seen:
                seen.add(key)
                uniq.append(it)
        error = None if uniq else ("; ".join(errors) or "no headlines returned")
        # a failure is only remembered for 2 minutes, so the next visitor can try again soon
        _cache.update(at=time.time() - (CACHE_SECONDS - 120 if error else 0), items=uniq, error=error)
        return uniq, error, 0.0
