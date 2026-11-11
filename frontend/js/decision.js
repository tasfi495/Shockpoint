/* Decision Engine: strategy comparison table and chart, weight sliders, ranked recommendation, "Do nothing" row. */
const Decision = (() => {
  const esc = (s) => SP.esc(s);
  const KEYS = [["value", "Value protected", "extra gross profit vs doing nothing (RM)"],
                ["cost", "Cost", "upfront + ongoing cost of the strategy (RM), lower is better"],
                ["cash", "Cash impact", "cash position after the strategy, higher is better"],
                ["feasibility", "Feasibility", "time to take effect vs stockout date, and supplier capacity (0-1)"]];
  let timer = null;

  function init(state) {
    const el = document.getElementById("weights");
    el.innerHTML = KEYS.map(([k, label, hint]) => `<div class="slider">
        <label>${label} <output id="w-${k}-out"></output></label>
        <input type="range" min="0" max="100" step="5" id="w-${k}" />
        <div class="small muted">${hint}</div></div>`).join("");
    setSliders(state.weights);
    KEYS.forEach(([k]) => {
      document.getElementById(`w-${k}`).oninput = (e) => {
        SP.state.weights[k] = Number(e.target.value) / 100;
        document.getElementById(`w-${k}-out`).textContent = `${e.target.value}`;
        clearTimeout(timer);
        timer = setTimeout(rerank, 200);
      };
    });
    document.getElementById("reset-weights").onclick = () => {
      SP.state.weights = { ...SP.state.baseline.default_weights };
      setSliders(SP.state.weights);
      rerank();
    };
    document.getElementById("dec-ai-btn").onclick = brief;
  }

  function setSliders(w) {
    KEYS.forEach(([k]) => {
      const v = Math.round(w[k] * 100);
      document.getElementById(`w-${k}`).value = v;
      document.getElementById(`w-${k}-out`).textContent = `${v}`;
    });
  }

  async function rerank() {
    if (!SP.state.scenarioId) return;
    try {
      await SP.decide();
      render(SP.state);
      Overview.render(SP.state);
    } catch (e) { SP.toast(`Ranking failed: ${e.message}`); }
  }

  function render(state) {
    const d = state.decision;
    const reco = document.getElementById("dec-reco");
    const table = document.getElementById("dec-table");
    const btn = document.getElementById("dec-ai-btn");
    if (!d) {
      reco.classList.add("muted"); reco.textContent = "Run a scenario first.";
      table.innerHTML = ""; btn.disabled = true;
      document.getElementById("weights-used").textContent = "";
      document.getElementById("score-formula").textContent = "Score = sum(w_c x norm_c), weights sum to 1";
      Charts.strategies("dec-chart", { ranking: [], weights: state.weights });
      return;
    }
    btn.disabled = false;
    document.getElementById("weights-used").textContent = "Weights used (normalised by the engine): " +
      KEYS.map(([k, l]) => `${l} ${Math.round(d.weights[k] * 100)}%`).join(" · ");
    document.getElementById("score-formula").textContent = d.formula;

    const top = d.ranking[0];
    reco.classList.remove("muted");
    reco.innerHTML = `<div class="reco-name">#1 ${esc(top.name)}</div>
      <div class="reco-sentence">${esc(d.recommendation.sentence)}</div>
      <div class="reco-meta"><span class="chip">Score ${top.score.toFixed(3)}</span>
        <span class="chip">Revenue at risk avoided ${SP.fmt.rm(top.breakdown.revenue_at_risk_avoided_rm)}</span>
        <span class="chip">Gross profit vs do nothing ${SP.fmt.rm(top.breakdown.gross_profit_gain_rm)}</span>
        <span class="chip">Cash vs do nothing ${SP.fmt.rm(top.breakdown.cash_vs_do_nothing_rm)}</span></div>
      <p class="small muted" style="margin-top:12px">${esc(top.effect.notes || top.description)}</p>`;

    table.innerHTML = `<thead><tr><th>#</th><th>Strategy</th><th class="num">Value protected</th><th class="num">Cost</th>
      <th class="num">Cash position</th><th class="num">Feasibility</th><th class="num">Score</th></tr></thead><tbody>` +
      d.ranking.map((r) => `<tr class="${r.is_do_nothing ? "dn" : ""} ${r.rank === 1 ? "top" : ""}">
        <td><b>${r.rank}</b></td>
        <td><b>${esc(r.name)}</b>${r.is_do_nothing ? ` <span class="tag tag-grey">baseline row</span>` : ""}<div class="small muted">${esc(r.explanation)}</div></td>
        <td class="num">${SP.fmt.rm(r.criteria.value_protected_rm)}</td>
        <td class="num">${SP.fmt.rm(r.criteria.cost_rm)}</td>
        <td class="num">${SP.fmt.rm(r.criteria.cash_position_rm)}</td>
        <td class="num">${r.criteria.feasibility.toFixed(2)}</td>
        <td class="num"><b>${r.score.toFixed(3)}</b><div class="bar"><span style="width:${(r.score * 100).toFixed(0)}%"></span></div></td></tr>`).join("") + "</tbody>";
    Charts.strategies("dec-chart", d);
  }

  async function brief() {
    const st = SP.state;
    const btn = document.getElementById("dec-ai-btn");
    const txt = document.getElementById("dec-ai-text");
    const label = document.getElementById("dec-ai-label");
    btn.disabled = true; txt.textContent = "Writing briefing...";
    try {
      const r = await API.brief(st.scenarioId, st.drivers, st.weights);
      txt.textContent = r.text; txt.classList.remove("muted");
      label.textContent = r.label; label.classList.toggle("template", r.source === "template");
    } catch (e) { txt.textContent = `Error: ${e.message}`; }
    btn.disabled = false;
  }

  return { init, render };
})();
