/* Business Exposure: supplier dependency, affected materials, stockout timeline, orders at risk, alternatives. */
const Exposure = (() => {
  const esc = (s) => SP.esc(s);
  let selectedId = null;

  function supplierStatus(s, sim) {
    if (s.is_alternative) return `<span class="tag tag-blue">Alternative</span>`;
    if (sim && s.affected && sim.scenario.type === "supply") return `<span class="tag tag-red">Affected</span>`;
    if (s.at_risk) return `<span class="tag tag-amber">At risk</span>`;
    return `<span class="tag tag-grey">Normal</span>`;
  }

  function renderDetail(s, sim) {
    const el = document.getElementById("ex-detail");
    el.innerHTML = `<div class="card-head"><h3><i data-lucide="info"></i> ${esc(s.name)}</h3>${supplierStatus(s, sim)}</div>
      <p class="muted small">${esc(s.country)} · ${esc(s.ship_route)}</p>
      <div class="detail-grid">
        <div><span>Material</span><b>${esc(s.material_id)}</b> <small>${esc(s.material_name)}</small></div>
        <div><span>Share of this material</span><b>${s.share_pct}%</b></div>
        <div><span>Share of supply spend</span><b>${SP.fmt.pct(s.share_of_total_spend_pct)}</b></div>
        <div><span>Spend in horizon</span><b>${SP.fmt.rm(s.spend_rm_horizon)}</b></div>
        <div><span>Lead time</span><b>${s.lead_time_days} days</b></div>
        <div><span>Capacity</span><b>${SP.fmt.num(s.capacity_units_per_week)}/wk</b></div>
        <div><span>Material runway</span><b>${s.material_runway_days} days</b></div>
        <div><span>Lead time in scenario</span><b>${s.material_new_lead_time_days} days</b></div>
        <div><span>Products using it</span><b>${esc(s.products_using.join(", "))}</b></div>
        <div><span>Orders depending on it</span><b>${SP.fmt.rm(s.orders_depending_rm)}</b></div>
        <div><span>Orders at risk</span><b>${SP.fmt.rm(s.orders_at_risk_rm)}</b></div>
        <div><span>Reliability${s.stress_score !== null && s.stress_score !== undefined ? " · stress" : ""}</span><b>${s.reliability}${s.stress_score !== null && s.stress_score !== undefined ? " · " + s.stress_score : ""}</b></div>
      </div>
      ${s.material_stops_production && !s.is_alternative && s.affected ? `<p class="small" style="color:#fca5a5;margin-top:12px">This material stops production in the scenario.</p>` : ""}`;
    lucide.createIcons();
  }

  function render(state) {
    const sim = state.sim;
    const exp = sim ? sim.exposure : state.baseline.exposure;
    const mats = sim ? sim.result.materials : state.baseline.baseline.materials;
    const highlight = sim && sim.scenario.type === "supply" ? sim.scenario.drivers.affected_country : null;
    Charts.donut("ex-donut", exp.dependency_by_country, highlight);
    Charts.runwayTimeline("ex-timeline", mats);

    // suppliers
    const t = document.getElementById("ex-suppliers");
    t.innerHTML = `<thead><tr><th>Supplier</th><th>Country</th><th>Material</th><th class="num">Spend share</th><th>Lead</th><th>Status</th></tr></thead><tbody>` +
      exp.suppliers.map((s) => `<tr data-id="${s.supplier_id}" class="${s.supplier_id === selectedId ? "sel" : ""}">
        <td><b>${esc(s.name)}</b></td><td>${esc(s.country)}</td><td>${esc(s.material_id)}</td>
        <td class="num">${s.is_alternative ? "-" : SP.fmt.pct(s.share_of_total_spend_pct)}</td><td>${s.lead_time_days} d</td>
        <td>${supplierStatus(s, sim)}</td></tr>`).join("") + "</tbody>";
    t.querySelectorAll("tbody tr").forEach((tr) => tr.onclick = () => {
      selectedId = tr.dataset.id;
      t.querySelectorAll("tr").forEach((r) => r.classList.toggle("sel", r.dataset.id === selectedId));
      renderDetail(exp.suppliers.find((s) => s.supplier_id === selectedId), sim);
    });
    const sel = exp.suppliers.find((s) => s.supplier_id === selectedId) || exp.suppliers.find((s) => s.affected) || exp.suppliers[0];
    selectedId = sel.supplier_id;
    t.querySelectorAll("tr").forEach((r) => r.classList.toggle("sel", r.dataset.id === selectedId));
    renderDetail(sel, sim);

    // affected materials
    const mt = document.getElementById("ex-materials");
    const affected = sim ? exp.affected_materials : mats;
    if (sim && sim.scenario.type === "demand") {
      const by = sim.result.kpis.excess_inventory.inputs.by_material_rm;
      mt.innerHTML = `<thead><tr><th>Material</th><th class="num">Stock</th><th class="num">Open POs</th><th class="num">Reduced usage/day</th><th class="num">Excess</th></tr></thead><tbody>` +
        affected.map((m) => `<tr><td><b>${esc(m.material_id)}</b> ${esc(m.name)}</td><td class="num">${SP.fmt.num(m.stock_units)}</td>
          <td class="num">${SP.fmt.num(m.open_po_units)}</td><td class="num">${SP.fmt.num(m.reduced_daily_usage_units, 1)}</td>
          <td class="num"><span class="tag tag-amber">${SP.fmt.rm(by[m.material_id])}</span></td></tr>`).join("") + "</tbody>";
    } else {
      mt.innerHTML = `<thead><tr><th>Material</th><th>Crit.</th><th class="num">Runway</th><th class="num">Lead time</th><th class="num">Gap</th><th>Stop date</th></tr></thead><tbody>` +
        (affected.length ? affected.map((m) => `<tr><td><b>${esc(m.material_id)}</b> ${esc(m.name)}</td><td>${m.criticality}</td>
          <td class="num">${m.runway_days} d</td><td class="num">${m.new_lead_time_days} d</td>
          <td class="num">${m.supply_gap_days > 0 ? `<span class="tag tag-red">${m.supply_gap_days} d</span>` : `<span class="tag tag-grey">none</span>`}</td>
          <td>${m.stop_date ? `<span class="tag tag-red">${esc(SP.fmt.date(m.stop_date))}</span>` : "-"}</td></tr>`).join("")
          : `<tr><td colspan="6" class="muted">No materials affected.</td></tr>`) + "</tbody>";
    }

    // orders at risk
    const ot = document.getElementById("ex-orders");
    const orders = sim ? exp.orders_at_risk : [];
    document.getElementById("ex-orders-total").textContent = sim ? `${orders.length} orders · ${SP.fmt.rm(exp.summary.revenue_at_risk_rm)} at risk` : "";
    ot.innerHTML = `<thead><tr><th>Order</th><th>Customer</th><th>Product</th><th>Due</th><th class="num">Value</th><th class="num">At risk</th></tr></thead><tbody>` +
      (orders.length ? orders.map((o) => `<tr><td>${esc(o.order_id)}</td><td>${esc(o.customer)}</td><td>${esc(o.product_id)}</td>
        <td>${esc(SP.fmt.date(o.due_date))}</td><td class="num">${SP.fmt.rm(o.value_rm)} <small>${esc(o.currency)}</small></td>
        <td class="num"><b>${SP.fmt.rm(o.at_risk_value_rm)}</b></td></tr>`).join("")
        : `<tr><td colspan="6" class="muted">${sim ? "No orders at risk." : "Run a scenario to see orders at risk."}</td></tr>`) + "</tbody>";

    // alternatives
    const at = document.getElementById("ex-alts");
    at.innerHTML = `<thead><tr><th>Alternative supplier</th><th>Country</th><th>Material</th><th class="num">Unit cost</th><th class="num">Lead time</th><th class="num">Capacity/wk</th><th class="num">Reliability</th></tr></thead><tbody>` +
      (exp.alternatives.length ? exp.alternatives.map((s) => `<tr><td><b>${esc(s.name)}</b></td><td>${esc(s.country)}</td>
        <td>${esc(s.material_id)} ${esc(s.material_name)}</td><td class="num">RM ${s.unit_cost_rm.toFixed(2)}</td>
        <td class="num">${s.lead_time_days} d</td><td class="num">${SP.fmt.num(s.capacity_units_per_week)}</td><td class="num">${s.reliability}</td></tr>`).join("")
        : `<tr><td colspan="7" class="muted">No qualified alternatives for the affected materials.</td></tr>`) + "</tbody>";
  }

  return { render };
})();
