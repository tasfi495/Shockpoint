/* Overview: active scenario banner, impact map, 5 KPI cards baseline vs scenario, top recommendation, exposure summary. */
const Overview = (() => {
  const esc = (s) => SP.esc(s);

  function baselineCards(b) {
    return ["inventory_runway", "gross_margin", "cash_position", "revenue_at_risk", "business_risk"].map((k) => ({
      key: k, label: b.kpis[k].label, unit: b.kpis[k].unit, baseline: b.kpis[k].value, scenario: b.kpis[k].value,
      delta: null, formula: b.kpis[k].formula, inputs: b.kpis[k].inputs, source: b.kpis[k].source,
    }));
  }

  function render(state) {
    const sim = state.sim;
    const base = state.baseline;
    // map
    const exposure = sim ? sim.exposure : base.exposure;
    MapView.drawMap(exposure.suppliers, sim ? { type: sim.scenario.type, exposure } : null);
    document.getElementById("map-caption").textContent = sim
      ? `${exposure.summary.affected_suppliers} of ${exposure.summary.current_suppliers} current suppliers affected`
      : "Suppliers, shipping routes and our plant";

    // KPI cards
    const row = document.getElementById("ov-kpis");
    row.innerHTML = "";
    if (sim) sim.kpi_cards.forEach((c) => row.appendChild(SP.kpiCard(c)));
    else baselineCards(base.baseline).forEach((c) => row.appendChild(SP.kpiCard(c, { baselineOnly: true })));

    // recommendation
    const reco = document.getElementById("ov-reco");
    const aiBtn = document.getElementById("ov-ai-btn");
    if (sim && state.decision) {
      const d = state.decision;
      const top = d.ranking[0];
      const dn = d.do_nothing;
      reco.classList.remove("muted");
      reco.innerHTML = `<div class="reco-name">${esc(d.recommendation.name)}</div>
        <div class="reco-sentence">${esc(d.recommendation.sentence)}</div>
        <div class="reco-meta"><span class="chip">Score ${top.score.toFixed(2)}</span>
        <span class="chip">Cash ${SP.fmt.rm(top.criteria.cash_position_rm)}</span>
        <span class="chip">Do nothing: cash ${SP.fmt.rm(dn.criteria.cash_position_rm)}, rank #${dn.rank}</span></div>`;
      aiBtn.disabled = false;
    } else {
      reco.classList.add("muted");
      reco.textContent = "Run a scenario to get a recommendation.";
      aiBtn.disabled = true;
      document.getElementById("ov-ai-text").textContent = "The briefing uses only the engine's numbers.";
    }

    // exposure summary
    const s = exposure.summary;
    const highlight = sim && sim.scenario.type === "supply" ? sim.scenario.drivers.affected_country : null;
    Charts.donut("ov-donut", exposure.dependency_by_country, highlight);
    const list = document.getElementById("ov-exposure-list");
    if (sim) {
      list.innerHTML = `
        <li><span>Suppliers affected</span><b>${s.affected_suppliers} of ${s.current_suppliers}</b></li>
        <li><span>Supply spend affected</span><b>${SP.fmt.pct(s.affected_spend_share_pct)}</b></li>
        ${sim.scenario.type === "supply"
          ? `<li><span>Materials affected</span><b>${s.affected_materials} (${s.materials_stopping_production} stop production)</b></li>`
          : `<li><span>Materials with excess stock</span><b>${s.affected_materials}</b></li>`}
        <li><span>Orders at risk</span><b>${s.orders_at_risk} · ${SP.fmt.rm(s.revenue_at_risk_rm)}</b></li>
        <li><span>At-risk suppliers</span><b>${s.at_risk_suppliers.length ? esc(s.at_risk_suppliers.join(", ")) : "None"}</b></li>
        <li><span>Business risk</span><b>${esc(sim.risk_level)}</b></li>`;
    } else {
      list.innerHTML = exposure.dependency_by_country.map((d) =>
        `<li><span>${esc(d.country)}</span><b>${SP.fmt.pct(d.share_pct)}</b></li>`).join("") +
        `<li><span>Current suppliers</span><b>${s.current_suppliers}</b></li>`;
    }

    // baseline vs scenario chart
    Charts.compare("ov-compare", base.baseline.financials, sim ? sim.result.financials : null);
    document.getElementById("ov-horizon").textContent = `Next ${base.baseline.horizon_days} days`;
  }

  async function brief() {
    const st = SP.state;
    const btn = document.getElementById("ov-ai-btn");
    const txt = document.getElementById("ov-ai-text");
    const label = document.getElementById("ov-ai-label");
    btn.disabled = true; txt.textContent = "Writing briefing...";
    try {
      const r = await API.brief(st.scenarioId, st.drivers, st.weights);
      txt.textContent = r.text; txt.classList.remove("muted");
      label.textContent = r.label; label.classList.toggle("template", r.source === "template");
    } catch (e) { txt.textContent = `Error: ${e.message}`; }
    btn.disabled = false;
  }
  document.addEventListener("DOMContentLoaded", () => { document.getElementById("ov-ai-btn").onclick = brief; });

  return { render };
})();
