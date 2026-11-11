/* Fetch wrappers for every API route. The frontend never calculates; it only renders API results. */
const API = (() => {
  async function request(method, url, body) {
    const res = await fetch(url, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) {
      let msg = `${res.status} ${res.statusText}`;
      try { const j = await res.json(); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch (_) {}
      throw new Error(msg);
    }
    return res.json();
  }
  return {
    baseline: () => request("GET", "/api/baseline"),
    simulate: (scenario_id, drivers) => request("POST", "/api/simulate", { scenario_id, drivers }),
    decide: (scenario_id, drivers, weights) => request("POST", "/api/decide", { scenario_id, drivers, weights }),
    events: (source = "demo") => request("GET", `/api/events?source=${encodeURIComponent(source)}`),
    brief: (scenario_id, drivers, weights) => request("POST", "/api/ai/brief", { scenario_id, drivers, weights }),
    parseEvent: (headline) => request("POST", "/api/ai/parse-event", { headline }),
    ask: (question, scenario_id, drivers, weights) => request("POST", "/api/ai/ask", { question, scenario_id, drivers, weights }),
  };
})();
