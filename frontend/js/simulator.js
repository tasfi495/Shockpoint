/* Scenario Simulator: scenario picker, sliders per driver (from scenarios.json), Run Simulation, baseline vs scenario charts. */
const Simulator = (() => {
  const esc = (s) => SP.esc(s);
  let selected = null;     // scenario id chosen in the picker
  let values = {};         // slider values (sent to the API, which validates them)

  function scenarioDef(id) { return SP.state.baseline.scenarios.find((s) => s.id === id); }

  function renderPicker() {
    const el = document.getElementById("sim-picker");
    el.innerHTML = SP.state.baseline.scenarios.map((s) => `
      <button class="scenario-opt ${s.id === selected ? "selected" : ""}" data-id="${s.id}">
        <div class="so-type">${esc(SP.TYPE_LABEL[s.type] || s.type)}</div>
        <div class="so-name">${esc(s.name)}</div></button>`).join("");
    el.querySelectorAll(".scenario-opt").forEach((b) => b.onclick = () => select(b.dataset.id, null));
  }

  function select(id, drivers) {
    selected = id;
    const def = scenarioDef(id);
    values = {};
    const saved = drivers || SP.state.driversBy[id] || {};      // keep what the user last ran for this scenario
    Object.entries(def.drivers).forEach(([k, spec]) => { values[k] = k in saved ? saved[k] : spec.default; });
    renderPicker();
    document.getElementById("sim-desc").textContent = def.description;   // the precedent for the chosen country shows in the banner
    renderSliders(def);
  }

  // Malaysia means Penang Port, where every import lands, so say so in the picker.
  const PLACE_LABEL = { "Malaysia": "Malaysia (Penang Port, our import port)" };

  function renderSliders(def) {
    const el = document.getElementById("sim-sliders");
    el.innerHTML = "";
    Object.entries(def.drivers).forEach(([k, spec]) => {
      const wrap = document.createElement("div");
      wrap.className = "slider";
      if (spec.type === "select") {
        wrap.innerHTML = `<label>${esc(spec.label)}</label><select>${spec.options.map((o) =>
          `<option value="${esc(o)}" ${o === values[k] ? "selected" : ""}>${esc(PLACE_LABEL[o] || o)}</option>`).join("")}</select>`;
        wrap.querySelector("select").onchange = (e) => { values[k] = e.target.value; };
      } else {
        const unit = spec.unit === "%" ? "%" : ` ${spec.unit}`;
        wrap.innerHTML = `<label>${esc(spec.label)} <output>${values[k]}${esc(unit)}</output></label>
          <input type="range" min="${spec.min}" max="${spec.max}" step="${spec.step}" value="${values[k]}" />`;
        const out = wrap.querySelector("output");
        wrap.querySelector("input").oninput = (e) => { values[k] = Number(e.target.value); out.textContent = `${e.target.value}${unit}`; };
      }
      el.appendChild(wrap);
    });
  }

  function init(state) {
    select(state.baseline.scenarios[0].id, null);
    document.getElementById("run-btn").onclick = () => SP.simulate(selected, { ...values });
    document.getElementById("parse-btn").onclick = parseHeadline;
  }

  async function parseHeadline() {
    const h = document.getElementById("headline-input").value.trim();
    const out = document.getElementById("parse-result");
    if (h.length < 10) { out.textContent = "Paste a headline of at least 10 characters."; return; }
    out.textContent = "Reading headline...";
    try {
      const r = await API.parseEvent(h);
      if (!r.valid) { out.innerHTML = `<span class="tag tag-amber">Rejected</span> ${esc(r.errors.join(" "))}`; return; }
      const p = r.parsed;
      const def = scenarioDef(r.scenario_id);
      const place = r.scenario_id === "S1" ? ` · ${esc(p.affected_country)}` : "";
      const why = (p.evidence || []).map((e) =>
        `<li><b>${esc(e.setting)}</b>: ${esc(e.value)} <span class="muted">← ${esc(e.because)}</span></li>`).join("");
      const defaults = Object.keys(def.drivers).filter((k) => !(r.from_headline || []).includes(k))
        .map((k) => def.drivers[k].label.replace(/\s*\(.*\)$/, "")).join(", ");
      out.innerHTML = `<span class="ai-label ${r.source === "template" ? "template" : ""}">${esc(r.label)}</span>
        <div style="margin-top:6px">Mapped to <b>${esc(SP.TYPE_LABEL[def.type])}</b>${place}. The sliders now show every value.</div>
        ${why ? `<ul class="why-list">${why}</ul>` : ""}
        ${defaults ? `<div class="muted small">Not in the headline, so the default is used: ${esc(defaults)}.</div>` : ""}
        ${r.errors.length ? `<div class="muted small">${esc(r.errors.join(" "))}</div>` : ""}`;
      select(r.scenario_id, r.drivers);
      SP.simulate(r.scenario_id, r.drivers);
    } catch (e) { out.textContent = `Error: ${e.message}`; }
  }

  const ORDER = ["inventory_runway", "supply_gap", "production_stop_date", "cost_impact", "gross_margin",
                 "revenue_at_risk", "cash_position", "excess_inventory", "business_risk"];

  function render(state) {
    const sim = state.sim;
    const kpiRow = document.getElementById("sim-kpis");
    const table = document.getElementById("sim-kpi-table");
    if (sim && sim.scenario.id !== selected) select(sim.scenario.id, sim.scenario.drivers);
    if (!sim) {
      kpiRow.innerHTML = `<div class="card muted" style="grid-column:1/-1">Set the drivers and press <b>Run Simulation</b>.</div>`;
      Charts.compare("sim-compare", state.baseline.baseline.financials, null);
      Charts.stockProjection("sim-projection", null);
      table.innerHTML = "";
      return;
    }
    kpiRow.innerHTML = "";
    sim.kpi_cards.forEach((c) => kpiRow.appendChild(SP.kpiCard(c)));
    Charts.compare("sim-compare", sim.baseline.financials, sim.result.financials);
    if (sim.scenario.type === "supply") {
      document.getElementById("sim-proj-title").textContent = `Projected stock: ${sim.result.stock_projection.material_name}`;
      const top = state.decision && state.decision.ranking[0];
      const proj = { ...sim.result.stock_projection, strategy: top && top.stock_projection ? top.stock_projection.strategy : null };
      Charts.stockProjection("sim-projection", proj);
    } else {
      document.getElementById("sim-proj-title").textContent = "Excess inventory by material";
      Charts.excess("sim-projection", sim.result.materials, sim.result.kpis.excess_inventory.inputs.by_material_rm);
    }
    const b = sim.baseline.kpis, s = sim.result.kpis;
    table.innerHTML = `<thead><tr><th>KPI</th><th>Formula</th><th class="num">Baseline</th><th class="num">Scenario</th></tr></thead><tbody>` +
      ORDER.map((k) => `<tr data-k="${k}"><td><b>${esc(s[k].label)}</b></td><td class="muted small">${esc(s[k].formula)}</td>
        <td class="num">${esc(SP.fmt.value(b[k].value, b[k].unit))}</td><td class="num"><b>${esc(SP.fmt.value(s[k].value, s[k].unit))}</b></td></tr>`).join("") + "</tbody>";
    table.querySelectorAll("tbody tr").forEach((tr) => tr.onclick = (e) => { e.stopPropagation(); SP.showInfo(e, s[tr.dataset.k]); });
  }

  return { init, render };
})();
