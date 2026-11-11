/* ECharts builders: one function per chart. They only draw values returned by the API. */
const Charts = (() => {
  const C = { blue: "#3b82f6", blue2: "#60a5fa", cyan: "#38bdf8", red: "#ef4444", amber: "#f59e0b", grey: "#475569",
              text: "#e6edf8", muted: "#8797b3", grid: "rgba(135,151,179,.12)", violet: "#a78bfa" };
  const instances = {};
  const base = {
    backgroundColor: "transparent",
    textStyle: { fontFamily: "Inter, sans-serif", color: C.text },
    tooltip: { backgroundColor: "#0b1528", borderColor: "#1d2b49", textStyle: { color: C.text, fontSize: 12 } },
  };
  const axis = (extra = {}) => ({ axisLine: { lineStyle: { color: C.grid } }, axisLabel: { color: C.muted, fontSize: 11 },
                                  splitLine: { lineStyle: { color: C.grid } }, ...extra });
  const rm = (v) => SP.fmt.rm(v);

  function get(el) {
    const node = typeof el === "string" ? document.getElementById(el) : el;
    if (!node) return null;
    if (!instances[node.id]) instances[node.id] = echarts.init(node, null, { renderer: "canvas" });
    return instances[node.id];
  }
  function resizeAll() { Object.values(instances).forEach((c) => c.resize()); }
  window.addEventListener("resize", resizeAll);

  // Baseline vs scenario money comparison
  function compare(el, baseFin, scenFin) {
    const labels = ["Revenue", "Gross profit", "Cash position", "Cost impact"];
    const keys = ["revenue_rm", "gross_profit_rm", "cash_position_rm", "cost_impact_rm"];
    const series = [{ name: "Baseline", type: "bar", data: keys.map((k) => baseFin[k]), itemStyle: { color: C.grey, borderRadius: [4, 4, 0, 0] }, barGap: "15%" }];
    if (scenFin) series.push({ name: "Scenario", type: "bar", data: keys.map((k) => scenFin[k]), itemStyle: { color: C.blue, borderRadius: [4, 4, 0, 0] } });
    get(el).setOption({ ...base, tooltip: { ...base.tooltip, trigger: "axis", valueFormatter: rm },
      legend: { textStyle: { color: C.muted }, top: 0, right: 0 },
      grid: { left: 70, right: 10, top: 30, bottom: 30 },
      xAxis: { type: "category", data: labels, ...axis() }, yAxis: { type: "value", ...axis({ axisLabel: { color: C.muted, formatter: rm } }) },
      series }, true);
  }

  // Projected stock of the most critical material
  function stockProjection(el, proj) {
    const chart = get(el);
    if (!proj) { chart.clear(); return; }
    const marks = [];
    if (proj.stop_day !== null && proj.stop_day !== undefined) {
      marks.push([{ xAxis: Math.floor(proj.stop_day), itemStyle: { color: "rgba(239,68,68,.15)" }, label: { show: true, formatter: "Production stopped", color: "#fca5a5", position: "insideTop" } },
                  { xAxis: Math.ceil(proj.restart_day) }]);
    }
    const series = [
      { name: "Baseline", type: "line", data: proj.baseline, showSymbol: false, lineStyle: { color: C.grey, width: 2 } },
      { name: "Scenario (do nothing)", type: "line", data: proj.scenario, showSymbol: false, lineStyle: { color: C.red, width: 3 }, markArea: { data: marks } },
    ];
    if (proj.strategy) series.push({ name: "With top strategy", type: "line", data: proj.strategy, showSymbol: false, lineStyle: { color: C.cyan, width: 2, type: "dashed" } });
    chart.setOption({ ...base, tooltip: { ...base.tooltip, trigger: "axis" },
      legend: { textStyle: { color: C.muted }, top: 0, right: 0 },
      grid: { left: 60, right: 14, top: 34, bottom: 34 },
      xAxis: { type: "category", data: proj.days, name: "days from today", nameLocation: "middle", nameGap: 24, nameTextStyle: { color: C.muted }, ...axis() },
      yAxis: { type: "value", name: "units", nameTextStyle: { color: C.muted }, ...axis() }, series }, true);
  }

  // Stockout timeline per material: runway vs (new) lead time
  function runwayTimeline(el, materials) {
    const names = materials.map((m) => `${m.material_id} ${m.name.split(" (")[0]}`);
    get(el).setOption({ ...base, tooltip: { ...base.tooltip, trigger: "axis",
        formatter: (p) => { const m = materials[p[0].dataIndex];
          return `<b>${m.material_id} ${m.name}</b><br/>Runway: ${m.runway_days} days<br/>Lead time: ${m.new_lead_time_days} days (base ${m.base_lead_time_days})<br/>` +
                 (m.stops_production ? `<span style="color:#fca5a5">Stops ${m.stop_date}, supply gap ${m.supply_gap_days} days</span>` : "Covered"); } },
      legend: { textStyle: { color: C.muted }, top: 0, right: 0 },
      grid: { left: 10, right: 30, top: 30, bottom: 24, containLabel: true },
      xAxis: { type: "value", name: "days", nameTextStyle: { color: C.muted }, ...axis() },
      yAxis: { type: "category", data: names, inverse: true, ...axis({ axisLabel: { color: C.muted, fontSize: 11, width: 170, overflow: "truncate" } }) },
      series: [
        { name: "Inventory runway", type: "bar", data: materials.map((m) => ({ value: m.runway_days, itemStyle: { color: m.stops_production ? C.red : C.blue } })), barWidth: 12, itemStyle: { borderRadius: 4 } },
        { name: "Lead time (scenario)", type: "scatter", symbol: "diamond", symbolSize: 14, data: materials.map((m) => m.new_lead_time_days), itemStyle: { color: C.amber } },
      ] }, true);
  }

  // Excess inventory by material (S2)
  function excess(el, materials, byMat) {
    get(el).setOption({ ...base, tooltip: { ...base.tooltip, trigger: "axis", valueFormatter: rm },
      grid: { left: 10, right: 30, top: 10, bottom: 24, containLabel: true },
      xAxis: { type: "value", splitNumber: 3, ...axis({ axisLabel: { color: C.muted, formatter: rm, hideOverlap: true } }) },
      yAxis: { type: "category", inverse: true, data: materials.map((m) => `${m.material_id} ${m.name.split(" (")[0]}`), ...axis({ axisLabel: { color: C.muted, fontSize: 11, width: 170, overflow: "truncate" } }) },
      series: [{ name: "Excess inventory", type: "bar", barWidth: 12, data: materials.map((m) => byMat[m.material_id]), itemStyle: { color: C.amber, borderRadius: 4 } }] }, true);
  }

  // Strategy comparison: weighted score split by criterion
  function strategies(el, decision) {
    const rows = decision.ranking;
    const crit = [["value", "Value protected", C.blue], ["cost", "Cost", C.cyan], ["cash", "Cash impact", C.violet], ["feasibility", "Feasibility", "#94a3b8"]];
    get(el).setOption({ ...base, tooltip: { ...base.tooltip, trigger: "axis", axisPointer: { type: "shadow" } },
      legend: { textStyle: { color: C.muted }, top: 0, right: 0 },
      grid: { left: 10, right: 30, top: 32, bottom: 24, containLabel: true },
      xAxis: { type: "value", max: 1, ...axis() },
      yAxis: { type: "category", inverse: true, data: rows.map((r) => `#${r.rank} ${r.name}`), ...axis({ axisLabel: { color: C.text, fontSize: 12, width: 300, overflow: "truncate" } }) },
      series: crit.map(([k, name, color]) => ({ name: `${name} (${Math.round(decision.weights[k] * 100)}%)`, type: "bar", stack: "s", barWidth: 16,
        data: rows.map((r) => r.score_parts[k]), itemStyle: { color } })) }, true);
  }

  // Supplier dependency donut (share of supply spend by country)
  function donut(el, deps, highlight) {
    const palette = { China: C.blue, Taiwan: C.cyan, "South Korea": C.violet, Japan: "#f472b6", Vietnam: "#34d399", Malaysia: "#fbbf24" };
    get(el).setOption({ ...base, tooltip: { ...base.tooltip, trigger: "item", formatter: (p) => `${p.name}: ${p.data.share}%` },
      // legend in a column on the right, so five or more countries never sit on top of the ring
      legend: { orient: "vertical", right: 0, top: "middle", itemWidth: 10, itemHeight: 10, itemGap: 8,
        textStyle: { color: C.muted, fontSize: 11 },
        formatter: (n) => { const d = deps.find((x) => x.country === n); return d ? `${n} ${d.share_pct}%` : n; } },
      series: [{ type: "pie", radius: ["40%", "64%"], center: ["30%", "50%"], padAngle: 2, itemStyle: { borderRadius: 6 },
        label: { show: false },
        data: deps.map((d) => ({ name: d.country, value: d.share_pct, share: d.share_pct,
          itemStyle: { color: highlight && (highlight === d.country || highlight === "Malaysia") ? C.red : palette[d.country] || C.grey } })) }] }, true);
  }

  return { compare, stockProjection, runwayTimeline, excess, strategies, donut, resizeAll };
})();
