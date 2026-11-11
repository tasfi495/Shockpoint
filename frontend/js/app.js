/* View switching, shared state (current scenario and results), API calls. */
const SP = (() => {
  const state = {
    baseline: null,      // GET /api/baseline
    scenarioId: null,    // active scenario id or null (baseline)
    drivers: {},         // drivers sent with the last simulation
    sim: null,           // POST /api/simulate result
    decision: null,      // POST /api/decide result
    weights: null,       // slider values (the API normalises them)
    driversBy: {},       // last drivers the user ran for each scenario, so switching back keeps their settings
  };
  const TYPE_LABEL = { supply: "Supply shock", demand: "Demand shock" };

  const VIEWS = {
    overview: ["Overview", "Know where a world event hits your business, and what to do about it."],
    simulator: ["Scenario Simulator", "Pick a shock, set the drivers and run the simulation."],
    exposure: ["Business Exposure", "Which suppliers, materials and customer orders the shock touches."],
    decision: ["Decision Engine", "Every response runs through the same simulation, then gets a transparent weighted score."],
    monitor: ["Live Monitor", "Demo headlines or real ones from the past week, each mapped to a scenario and its settings."],
  };

  // ---------------------------------------------------------------- formatting (display only)
  const fmt = {
    rm(x) {
      if (x === null || x === undefined) return "-";
      const a = Math.abs(x), s = x < 0 ? "-" : "";
      if (a >= 1e6) return `${s}RM ${(a / 1e6).toFixed(2)}M`;
      if (a >= 1e3) return `${s}RM ${(a / 1e3).toFixed(0)}k`;
      return `${s}RM ${a.toFixed(0)}`;
    },
    rmFull: (x) => (x === null || x === undefined ? "-" : `RM ${Number(x).toLocaleString("en-MY", { maximumFractionDigits: 0 })}`),
    pct: (x, d = 1) => (x === null || x === undefined ? "-" : `${Number(x).toFixed(d)}%`),
    num: (x, d = 0) => (x === null || x === undefined ? "-" : Number(x).toLocaleString("en-MY", { maximumFractionDigits: d })),
    date(iso) {
      if (!iso) return "No stop";
      return new Date(iso + "T00:00:00").toLocaleDateString("en-MY", { day: "numeric", month: "short", year: "numeric" });
    },
    value(v, unit) {
      if (unit === "RM") return fmt.rm(v);
      if (unit === "%") return fmt.pct(v);
      if (unit === "days") return v === null ? "-" : `${fmt.num(v, 1)} days`;
      if (unit === "date") return fmt.date(v);
      return v ?? "-";
    },
  };
  // direction in which a KPI change is bad (used only to colour the delta)
  const BAD_WHEN_UP = new Set(["cost_impact", "revenue_at_risk", "excess_inventory", "supply_gap"]);

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // ---------------------------------------------------------------- KPI card + info popover
  function kpiCard(card, opts = {}) {
    const el = document.createElement("div");
    let cls = "kpi";
    if (card.key === "production_stop_date" && card.scenario) cls += " warn";
    else if (card.delta !== null && card.delta !== undefined && card.delta !== 0) {
      const bad = BAD_WHEN_UP.has(card.key) ? card.delta > 0 : card.delta < 0;
      if (bad) cls += Math.abs(card.delta) > 0 && (card.key === "revenue_at_risk" || card.key === "excess_inventory") ? " warn" : " caution";
    }
    el.className = cls;
    let deltaHtml = "";
    if (card.key === "production_stop_date") {
      deltaHtml = card.scenario
        ? `<div class="kpi-delta bad">Stops in ${card.days_until_stop} days · supply gap ${fmt.num(card.supply_gap_days, 1)} days (${esc(card.material)})</div>`
        : `<div class="kpi-delta neutral">Stock covers the delay</div>`;
    } else if (card.delta !== null && card.delta !== undefined && !opts.baselineOnly) {
      const bad = BAD_WHEN_UP.has(card.key) ? card.delta > 0 : card.delta < 0;
      const sign = card.delta > 0 ? "+" : "";
      const d = card.unit === "%" ? `${sign}${card.delta.toFixed(1)} pp` : card.unit === "RM" ? `${sign}${fmt.rm(card.delta)}` : `${sign}${card.delta}`;
      deltaHtml = `<div class="kpi-delta ${card.delta === 0 ? "neutral" : bad ? "bad" : "good"}">${d} vs baseline</div>`;
    }
    const main = opts.baselineOnly ? card.baseline : card.scenario;
    el.innerHTML = `
      <div class="kpi-label"><span>${esc(card.label)}</span><button class="info-btn" title="Formula, inputs and source">i</button></div>
      <div class="kpi-value">${esc(fmt.value(main, card.unit))}</div>
      ${opts.baselineOnly ? `<div class="kpi-base">Baseline (no shock)</div>` : `<div class="kpi-base">Baseline: ${esc(fmt.value(card.baseline, card.unit))}</div>`}
      ${deltaHtml}`;
    el.querySelector(".info-btn").addEventListener("click", (e) => { e.stopPropagation(); showInfo(e, card); });
    return el;
  }

  function flatten(obj, prefix = "") {
    const rows = [];
    for (const [k, v] of Object.entries(obj || {})) {
      if (v && typeof v === "object" && !Array.isArray(v)) rows.push(...flatten(v, prefix + k + "."));
      else if (Array.isArray(v) && v.length && typeof v[0] === "object") {
        v.forEach((item) => rows.push([prefix + k, Object.entries(item).map(([a, b]) => `${a}: ${b}`).join(", ")]));
      } else rows.push([prefix + k, Array.isArray(v) ? v.join(" to ") : v]);
    }
    return rows;
  }

  function showInfo(evt, item) {
    const pop = document.getElementById("popover");
    const rows = flatten(item.inputs).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`).join("");
    pop.innerHTML = `<h4>${esc(item.label)}</h4><div class="formula">${esc(item.formula)}</div>
      <table>${rows}</table><div class="src">Source: ${esc(item.source)}</div>`;
    pop.style.display = "block";
    const r = pop.getBoundingClientRect();
    let x = evt.clientX + 12, y = evt.clientY + 12;
    if (x + r.width > window.innerWidth - 10) x = window.innerWidth - r.width - 10;
    if (y + r.height > window.innerHeight - 10) y = Math.max(10, window.innerHeight - r.height - 10);
    pop.style.left = `${x}px`; pop.style.top = `${y}px`;
  }
  document.addEventListener("click", (e) => { if (!e.target.closest("#popover")) document.getElementById("popover").style.display = "none"; });

  // ---------------------------------------------------------------- assumptions panel (every page)
  function renderAssumptions() {
    const rows = state.baseline.assumptions.map((a) => {
      const src = String(a.source);
      const m = src.match(/https?:\/\/\S+/);
      const srcHtml = m ? `${esc(src.replace(m[0], "").replace(/:\s*$/, ""))} <a href="${esc(m[0])}" target="_blank" rel="noopener">link</a>` : esc(src);
      return `<tr><td>${esc(a.name)}</td><td class="num">${esc(a.value)}</td><td>${esc(a.unit)}</td><td>${srcHtml}</td></tr>`;
    }).join("");
    document.querySelectorAll(".assumptions-slot").forEach((slot) => {
      slot.innerHTML = `<details class="assumptions"><summary><i data-lucide="book-open"></i> Assumptions
        <span class="badge badge-sim" style="margin-left:auto"><i data-lucide="flask-conical"></i> Simulated data</span></summary>
        <p class="small muted">Company, supplier, order and event data are synthetic (fictional company). Only the USD/MYR rate and the copper reference price are real, with sources cited.</p>
        <table class="table"><thead><tr><th>Name</th><th class="num">Value</th><th>Unit</th><th>Source</th></tr></thead><tbody>${rows}</tbody></table></details>`;
    });
    lucide.createIcons();
  }

  // ---------------------------------------------------------------- banner + header
  function renderBanner() {
    const b = document.getElementById("banner");
    const pill = document.getElementById("status-pill");
    b.classList.remove("calm", "alert-high", "alert-medium");
    if (!state.sim) {
      b.classList.add("calm");
      document.getElementById("banner-title").textContent = "Baseline: no active shock";
      document.getElementById("banner-text").textContent = "Pick a scenario or play the Live Monitor demo feed to see the impact.";
      document.getElementById("banner-risk").textContent = "Risk: Low";
      document.getElementById("status-text").textContent = "Baseline";
      pill.classList.remove("active");
      pill.querySelector(".dot").style.background = ""; pill.querySelector(".dot").style.boxShadow = "";
      setBannerIcon("shield-check");
      return;
    }
    const bn = state.sim.banner;
    b.classList.add(bn.risk_level === "High" ? "alert-high" : bn.risk_level === "Medium" ? "alert-medium" : "calm");
    const title = document.getElementById("banner-title");
    title.textContent = bn.title;
    // the real-world precedent sits behind a small "i" so the banner stays about our business
    if (bn.precedent) {
      const info = document.createElement("button");
      info.className = "info-btn";
      info.title = "Has this happened before?";
      info.textContent = "i";
      info.style.cssText = "margin-left:8px;vertical-align:2px;";
      info.addEventListener("click", (e) => { e.stopPropagation(); showPrecedent(e, bn); });
      title.appendChild(info);
    }
    document.getElementById("banner-text").textContent = bn.text;
    document.getElementById("banner-risk").textContent = `${bn.risk_level} risk`;
    document.getElementById("status-text").textContent = bn.status;
    pill.classList.add("active");
    // dot colour follows the risk level (red = High, amber = Medium, blue = Low)
    pill.querySelector(".dot").style.background = { High: "#ef4444", Medium: "#f59e0b" }[bn.risk_level] || "#60a5fa";
    pill.querySelector(".dot").style.boxShadow = bn.risk_level === "Low" ? "none" : "";
    setBannerIcon(bn.risk_level === "Low" ? "shield-check" : "triangle-alert");
    b.classList.remove("flash"); void b.offsetWidth; b.classList.add("flash");
  }
  function showPrecedent(evt, bn) {
    const pop = document.getElementById("popover");
    pop.innerHTML = `<h4>Has this happened before?</h4><p style="margin:0 0 8px;line-height:1.5">${esc(bn.precedent)}</p>
      <div class="src">A real past event, shown for context only. The scenario numbers are simulated.</div>`;
    pop.style.display = "block";
    const r = pop.getBoundingClientRect();
    let x = evt.clientX + 12, y = evt.clientY + 12;
    if (x + r.width > window.innerWidth - 10) x = window.innerWidth - r.width - 10;
    pop.style.left = `${x}px`; pop.style.top = `${y}px`;
  }
  function setBannerIcon(name) {
    const holder = document.querySelector(".banner-icon");
    holder.innerHTML = `<i data-lucide="${name}"></i>`;
    lucide.createIcons();
  }

  function renderHeaderDate() {
    document.getElementById("today-date").textContent = new Date().toLocaleDateString("en-MY",
      { weekday: "short", day: "numeric", month: "short", year: "numeric" });
  }

  // Supply shocks are listed once per place (incl. Penang Port), so any of them can be started from the top bar.
  // Option values: "S2" for a scenario, "S1:China" for a supply shock at one place.
  const PLACE_NOTE = { Malaysia: " (our import port)" };

  function selectValue(scenarioId, drivers) {
    if (!scenarioId) return "";
    return drivers && drivers.affected_country ? `${scenarioId}:${drivers.affected_country}` : scenarioId;
  }

  function renderScenarioSelect() {
    const sel = document.getElementById("scenario-select");
    const groups = state.baseline.scenarios.map((s) => {
      const places = s.drivers.affected_country ? s.drivers.affected_country.options : null;
      if (!places) return `<optgroup label="${esc(TYPE_LABEL[s.type] || "Scenario")}">
        <option value="${s.id}">${esc(s.name)}</option></optgroup>`;
      return `<optgroup label="${esc(TYPE_LABEL[s.type] || "Scenario")}: ${esc(s.name.toLowerCase())}">` + places.map((p) => {
        const epi = (s.epicentres || {})[p];
        return `<option value="${s.id}:${esc(p)}">${esc(p)}: ${esc(epi ? epi.name : "port closure")}${esc(PLACE_NOTE[p] || "")}</option>`;
      }).join("") + `</optgroup>`;
    }).join("");
    sel.innerHTML = `<option value="">Baseline (no shock)</option>` + groups;
    sel.value = selectValue(state.scenarioId, state.drivers);
    // switching re-runs the scenario with the settings the user last chose for it (defaults only the first time);
    // picking a place only changes the place
    sel.onchange = () => {
      if (!sel.value) return clearScenario();
      const [id, place] = sel.value.split(":");
      const drivers = { ...(state.driversBy[id] || {}) };
      if (place) drivers.affected_country = place;
      simulate(id, Object.keys(drivers).length ? drivers : null);
    };
  }

  // ---------------------------------------------------------------- navigation
  function showView(name) {
    document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${name}`));
    document.querySelectorAll(".nav-item").forEach((n) => n.classList.toggle("active", n.dataset.view === name));
    document.getElementById("page-title").textContent = VIEWS[name][0];
    document.getElementById("page-subtitle").textContent = VIEWS[name][1];
    setTimeout(() => { Charts.resizeAll(); MapView.invalidate(); }, 30);
  }

  function toast(msg) {
    const t = document.getElementById("toast");
    t.textContent = msg; t.classList.add("show");
    clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove("show"), 3200);
  }

  // ---------------------------------------------------------------- engine calls
  async function simulate(scenarioId, drivers) {
    document.querySelector(".main").classList.add("loading");
    try {
      const sim = await API.simulate(scenarioId, drivers || {});
      state.scenarioId = scenarioId;
      state.drivers = sim.scenario.drivers;           // resolved (validated) drivers from the API
      state.driversBy[scenarioId] = sim.scenario.drivers;
      state.sim = sim;
      document.getElementById("scenario-select").value = selectValue(scenarioId, sim.scenario.drivers);
      await decide();
      renderAll();
    } catch (e) {
      toast(`Simulation failed: ${e.message}`);
    } finally {
      document.querySelector(".main").classList.remove("loading");
    }
  }

  async function decide() {
    if (!state.scenarioId) return;
    state.decision = await API.decide(state.scenarioId, state.drivers, state.weights);
  }

  function clearScenario() {
    state.scenarioId = null; state.sim = null; state.decision = null; state.drivers = {};
    document.getElementById("scenario-select").value = "";
    renderAll();
  }

  function renderAll() {
    renderBanner();
    Overview.render(state);
    Simulator.render(state);
    Exposure.render(state);
    Decision.render(state);
    lucide.createIcons();
  }

  // ---------------------------------------------------------------- Ask ShockPoint panel
  function initAsk() {
    const panel = document.getElementById("ask-panel");
    document.getElementById("ask-open").onclick = () => panel.classList.add("open");
    document.getElementById("ask-close").onclick = () => panel.classList.remove("open");
    document.getElementById("ask-form").onsubmit = async (e) => {
      e.preventDefault();
      const input = document.getElementById("ask-input");
      const q = input.value.trim();
      if (q.length < 3) return;
      const log = document.getElementById("ask-log");
      log.insertAdjacentHTML("beforeend", `<div class="q">${esc(q)}</div>`);
      input.value = "";
      if (!state.scenarioId) {
        log.insertAdjacentHTML("beforeend", `<div class="a">Run a scenario first, then ask about its results.</div>`);
        return;
      }
      const holder = document.createElement("div");
      holder.className = "a"; holder.textContent = "Thinking...";
      log.appendChild(holder);
      try {
        const r = await API.ask(q, state.scenarioId, state.drivers, state.weights);
        holder.innerHTML = `<span class="ai-label ${r.source === "template" ? "template" : ""}">${esc(r.label)}</span><div>${esc(r.text)}</div>`;
      } catch (err) { holder.textContent = `Error: ${err.message}`; }
      log.scrollTop = log.scrollHeight;
    };
  }

  async function init() {
    renderHeaderDate();
    setInterval(renderHeaderDate, 60_000);
    document.querySelectorAll(".nav-item").forEach((n) => n.addEventListener("click", () => showView(n.dataset.view)));
    try {
      state.baseline = await API.baseline();
    } catch (e) {
      toast(`Could not load data: ${e.message}`);
      return;
    }
    state.weights = { ...state.baseline.default_weights };
    renderScenarioSelect();
    renderAssumptions();
    Simulator.init(state);
    Decision.init(state);
    Monitor.init(state);
    initAsk();
    renderAll();
  }

  return { state, fmt, esc, TYPE_LABEL, kpiCard, showInfo, showView, simulate, decide, clearScenario, renderAll, toast, init };
})();

window.addEventListener("DOMContentLoaded", SP.init);
