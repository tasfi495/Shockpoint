/* Live Monitor: play / next event; each event runs the normal simulation.
   Two sources: the demo feed (simulated events, always available) and real headlines from GDELT (last 7 days).
   If real headlines cannot be used, the API sends the demo feed back with a note, so the demo never breaks. */
const Monitor = (() => {
  const esc = (s) => SP.esc(s);
  let events = [], pos = -1, playing = null, source = "demo";

  async function load(src) {
    stop();
    pos = -1;
    const note = document.getElementById("mon-note");
    document.querySelectorAll("#mon-source .seg-btn").forEach((b) => b.classList.toggle("active", b.dataset.src === src));
    if (src === "live") {
      note.hidden = false; note.className = "small mon-note ok";
      note.textContent = "Fetching real headlines from the news service (can take about 10 seconds)...";
    }
    try {
      const r = await API.events(src);
      events = r.events;
      source = r.source;
      document.getElementById("mon-label").textContent = r.label;
      if (r.note) {
        note.hidden = false;
        note.className = `small mon-note ${r.source === src ? "ok" : ""}`;
        note.textContent = r.note;
      } else { note.hidden = true; }
      // the API fell back to the demo feed: show the toggle on the feed actually in use
      document.querySelectorAll("#mon-source .seg-btn").forEach((b) => b.classList.toggle("active", b.dataset.src === r.source));
    } catch (e) {
      SP.toast(`Could not load the feed: ${e.message}`);
      note.hidden = true;
    }
    renderFeed();
  }

  async function init() {
    document.getElementById("mon-play").onclick = togglePlay;
    document.getElementById("mon-next").onclick = next;
    document.getElementById("mon-reset").onclick = reset;
    document.querySelectorAll("#mon-source .seg-btn").forEach((b) => b.onclick = () => load(b.dataset.src));
    await load("demo");
  }

  function tag(e) {
    const type = e.scenario_id === "S1" ? "Supply shock" : "Demand shock";
    const place = e.scenario_id === "S1" && e.drivers && e.drivers.affected_country ? ` · ${e.drivers.affected_country}` : "";
    return `<span class="tag ${e.scenario_id === "S1" ? "tag-red" : "tag-amber"}">${esc(type + place)} · severity ${e.severity}%</span>`;
  }

  function renderFeed() {
    const ul = document.getElementById("mon-feed");
    ul.innerHTML = events.map((e, i) => {
      const t = new Date(e.timestamp);
      const ts = t.toLocaleString("en-MY", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
      const src = e.url ? `<span class="src">${esc(e.domain || "source")} · <a href="${esc(e.url)}" target="_blank" rel="noopener noreferrer">open article</a></span>` : "";
      return `<li class="${i <= pos ? "shown" : ""} ${i === pos ? "current" : ""}">
        <span class="ts">${esc(ts)}</span><span class="hl">${esc(e.headline)}${src}</span>
        <span>${tag(e)}</span></li>`;
    }).join("");
  }

  async function next() {
    if (pos >= events.length - 1) { stop(); SP.toast(source === "live" ? "End of the real headlines." : "End of demo feed."); return; }
    pos += 1;
    renderFeed();
    const e = events[pos];
    SP.toast(`New event: ${e.headline}`);
    await SP.simulate(e.scenario_id, e.drivers);
  }

  function togglePlay() {
    if (playing) { stop(); return; }
    const btn = document.getElementById("mon-play");
    btn.innerHTML = `<i data-lucide="pause"></i> Pause`;
    lucide.createIcons();
    next();
    playing = setInterval(next, 4500);
  }

  function stop() {
    clearInterval(playing); playing = null;
    const btn = document.getElementById("mon-play");
    if (btn) { btn.innerHTML = `<i data-lucide="play"></i> Play feed`; if (window.lucide) lucide.createIcons(); }
  }

  function reset() { stop(); pos = -1; renderFeed(); SP.clearScenario(); }

  return { init };
})();
