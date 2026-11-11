/* Impact map: MapLibre GL (WebGL) on free OpenFreeMap vector tiles (no API key).
   Place names are switched to English. Our layers on top: supplier routes with moving glow particles,
   supplier markers, customer trade lanes, major ports (colour-coded), our plant and the disruption marker.
   Display only: every business value comes from the API. If the tile service is unreachable, a plain
   offline map (frontend/data/world.json) is used so the demo never breaks. */
const MapView = (() => {
  const STYLE_URL = "https://tiles.openfreemap.org/styles/dark";
  const C = { red: "#ef4444", amber: "#f59e0b", blue: "#3b82f6", alt: "#38bdf8", violet: "#a78bfa",
              port: "#2dd4bf", home: "#ffffff" };

  // Major container ports (map geometry only, not business data). [name, lat, lon, country]
  const PORTS = [
    ["Yantian Port (Shenzhen)", 22.575, 114.268, "China"], ["Shekou Port (Shenzhen)", 22.48, 113.91, "China"],
    ["Port of Hong Kong", 22.34, 114.12, "Hong Kong"], ["Nansha Port (Guangzhou)", 22.65, 113.67, "China"],
    ["Port of Xiamen", 24.45, 118.07, "China"], ["Ningbo-Zhoushan Port", 29.94, 121.88, "China"],
    ["Port of Shanghai (Yangshan)", 30.62, 122.07, "China"], ["Port of Qingdao", 36.08, 120.32, "China"],
    ["Port of Tianjin", 38.97, 117.79, "China"], ["Kaohsiung Port", 22.613, 120.283, "Taiwan"],
    ["Keelung Port", 25.15, 121.74, "Taiwan"], ["Taichung Port", 24.29, 120.51, "Taiwan"],
    ["Busan Port", 35.104, 129.042, "South Korea"], ["Incheon Port", 37.45, 126.60, "South Korea"],
    ["Port of Tokyo", 35.62, 139.78, "Japan"], ["Port of Kobe", 34.67, 135.21, "Japan"],
    ["Penang Port", 5.42, 100.35, "Malaysia"], ["Port Klang", 2.99, 101.38, "Malaysia"],
    ["Port of Tanjung Pelepas", 1.36, 103.55, "Malaysia"], ["Port of Singapore", 1.26, 103.82, "Singapore"],
    ["Laem Chabang Port", 13.08, 100.88, "Thailand"], ["Cat Lai Port (Ho Chi Minh City)", 10.76, 106.79, "Vietnam"],
    ["Port of Haiphong", 20.86, 106.69, "Vietnam"], ["Port of Manila", 14.60, 120.95, "Philippines"],
    ["Tanjung Priok (Jakarta)", -6.10, 106.88, "Indonesia"], ["Port of Colombo", 6.95, 79.84, "Sri Lanka"],
    ["Chennai Port", 13.10, 80.30, "India"], ["Nhava Sheva (Mumbai)", 18.95, 72.95, "India"],
    ["Jebel Ali (Dubai)", 25.01, 55.06, "UAE"], ["Port of Rotterdam", 51.95, 4.14, "Netherlands"],
    ["Port of Antwerp-Bruges", 51.27, 4.35, "Belgium"], ["Port of Hamburg", 53.54, 9.97, "Germany"],
    ["Port of Los Angeles / Long Beach", 33.74, -118.24, "United States"],
    ["Port of New York and New Jersey", 40.68, -74.15, "United States"],
    ["Port Botany (Sydney)", -33.97, 151.21, "Australia"], ["Port of Melbourne", -37.84, 144.92, "Australia"],
  ];
  // Supplier ship routes name their port of loading; this maps those names to the ports above.
  const ROUTE_PORT = { "Yantian (Shenzhen)": "Yantian Port (Shenzhen)", "Xiamen": "Port of Xiamen",
    "Ningbo": "Ningbo-Zhoushan Port", "Kaohsiung": "Kaohsiung Port", "Busan": "Busan Port",
    "Kobe": "Port of Kobe", "Haiphong": "Port of Haiphong",
    "Cat Lai (HCMC)": "Cat Lai Port (Ho Chi Minh City)" };
  // Customer markets in the order book -> the port their shipments go to (map geometry only).
  const CUSTOMER_PORTS = { "Singapore": "Port of Singapore", "Thailand": "Laem Chabang Port", "Japan": "Port of Tokyo",
    "Netherlands": "Port of Rotterdam", "Germany": "Port of Hamburg", "United States": "Port of Los Angeles / Long Beach",
    "Australia": "Port Botany (Sydney)" };

  const CSS = `
    .maplibregl-popup-content { background: #0b1528; color: #e6edf8; border: 1px solid #1d2b49; border-radius: 10px;
      padding: 10px 12px; font: 12px/1.5 Inter, system-ui, sans-serif; box-shadow: 0 10px 30px rgba(0,0,0,.45); }
    .maplibregl-popup-tip { border-top-color: #0b1528 !important; border-bottom-color: #0b1528 !important; }
    .maplibregl-popup-close-button { color: #8797b3; font-size: 16px; }
    .maplibregl-ctrl-group { background: rgba(15,26,48,.92) !important; border: 1px solid #1d2b49; }
    .maplibregl-ctrl-group button + button { border-top: 1px solid #1d2b49 !important; }
    .maplibregl-ctrl-group button .maplibregl-ctrl-icon { filter: invert(1) brightness(1.4); }
    .maplibregl-ctrl-group button.sp-reset { color: #e6edf8; font-size: 16px; font-weight: 700; }
    .maplibregl-ctrl-attrib { background: rgba(7,13,26,.75) !important; color: #8797b3; font-size: 10px; }
    .maplibregl-ctrl-attrib a { color: #60a5fa; }
    .sp-port { display: flex; align-items: center; gap: 5px; cursor: pointer; transform: translateY(1px); }
    .sp-port .dot { width: 9px; height: 9px; border-radius: 2px; transform: rotate(45deg); border: 1.5px solid #071021;
      box-shadow: 0 0 8px var(--c); background: var(--c); flex: none; }
    .sp-port .nm { color: #d6e2f3; font: 600 11px Inter, system-ui, sans-serif; white-space: nowrap;
      text-shadow: 0 0 3px #050b17, 0 0 6px #050b17; }
    .sp-port.hide-name .nm { display: none; }
    .sp-port.hidden { display: none; }
    .sp-home { display: flex; flex-direction: column; align-items: center; gap: 4px; }
    .sp-home .sq { width: 14px; height: 14px; background: #fff; border-radius: 3px; box-shadow: 0 0 0 4px rgba(255,255,255,.2), 0 0 18px #93c5fd; }
    .sp-home .lb { color: #fff; font: 700 11px Inter, system-ui, sans-serif; text-shadow: 0 0 4px #050b17; white-space: nowrap; }
    .sp-epi { display: flex; align-items: center; gap: 10px; }`;

  let map = null, styleReady = null, pending = null, current = null, markers = [], anim = null, fitBox = null;

  // ------------------------------------------------------------------ setup
  function injectCss() {
    if (document.getElementById("sp-map-css")) return;
    const st = document.createElement("style");
    st.id = "sp-map-css"; st.textContent = CSS;
    document.head.appendChild(st);
  }

  // shapes that cross the date line draw stray lines in the offline map, so leave them out there
  const NO_WRAP = ["!", ["in", ["get", "name"], ["literal", ["Antarctica", "Fiji", "Russia"]]]];

  async function pickStyle() {
    // use the online vector map if it answers within 6 s; otherwise a plain offline map
    try {
      const ctl = new AbortController();
      const t = setTimeout(() => ctl.abort(), 6000);
      const r = await fetch(STYLE_URL, { signal: ctl.signal });
      clearTimeout(t);
      if (r.ok) return { style: STYLE_URL, online: true };
    } catch (_) { /* fall through */ }
    return {
      online: false,
      style: { version: 8, sources: { world: { type: "geojson", data: "/data/world.json" } },
        layers: [
          { id: "bg", type: "background", paint: { "background-color": "#071021" } },
          { id: "land", type: "fill", source: "world", filter: NO_WRAP, paint: { "fill-color": "#0f1d36" } },
          { id: "borders", type: "line", source: "world", filter: NO_WRAP, paint: { "line-color": "rgba(96,165,250,.25)", "line-width": 0.6 } },
        ] },
    };
  }

  // English place names: every label that shows a name uses the English name when the map has one
  function englishLabels() {
    const en = ["coalesce", ["get", "name:en"], ["get", "name_en"], ["get", "name:latin"], ["get", "name"]];
    for (const layer of map.getStyle().layers) {
      if (layer.type !== "symbol" || !layer.layout || !layer.layout["text-field"]) continue;
      if (!JSON.stringify(layer.layout["text-field"]).includes("name")) continue;   // keep road numbers etc.
      try { map.setLayoutProperty(layer.id, "text-field", en); } catch (_) { /* ignore */ }
    }
  }

  // darker navy water and land so it matches the dashboard
  function tint() {
    for (const layer of map.getStyle().layers) {
      try {
        if (layer.type === "background") map.setPaintProperty(layer.id, "background-color", "#0d1830");
        else if (layer.type === "fill" && /water|ocean|sea/.test(layer.id)) map.setPaintProperty(layer.id, "fill-color", "#060d1c");
      } catch (_) { /* ignore */ }
    }
  }

  function addOurLayers() {
    const empty = { type: "FeatureCollection", features: [] };
    ["routes", "lanes", "suppliers", "particles"].forEach((id) => map.addSource(id, { type: "geojson", data: empty }));
    map.addLayer({ id: "lanes", type: "line", source: "lanes", layout: { "line-cap": "round" },
      paint: { "line-color": ["get", "color"], "line-width": 1.4, "line-opacity": 0.55, "line-dasharray": [2, 3] } });
    map.addLayer({ id: "routes-glow", type: "line", source: "routes", layout: { "line-cap": "round" },
      paint: { "line-color": ["get", "color"], "line-width": ["get", "glow"], "line-opacity": 0.18, "line-blur": 4 } });
    map.addLayer({ id: "routes", type: "line", source: "routes", layout: { "line-cap": "round" },
      paint: { "line-color": ["get", "color"], "line-width": ["get", "width"], "line-opacity": ["get", "opacity"] } });
    map.addLayer({ id: "particles", type: "circle", source: "particles",
      paint: { "circle-radius": 2.6, "circle-color": ["get", "color"], "circle-blur": 0.4, "circle-opacity": 0.95 } });
    map.addLayer({ id: "suppliers-glow", type: "circle", source: "suppliers",
      paint: { "circle-radius": ["*", ["get", "r"], 2.2], "circle-color": ["get", "color"], "circle-opacity": 0.18, "circle-blur": 1 } });
    map.addLayer({ id: "suppliers", type: "circle", source: "suppliers",
      paint: { "circle-radius": ["get", "r"], "circle-color": ["get", "fill"], "circle-stroke-color": ["get", "color"],
               "circle-stroke-width": 1.8, "circle-opacity": 0.95 } });

    const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 10, maxWidth: "320px" });
    map.on("mouseenter", "suppliers", (e) => {
      map.getCanvas().style.cursor = "pointer";
      const f = e.features[0];
      popup.setLngLat(f.geometry.coordinates).setHTML(f.properties.html).addTo(map);
    });
    map.on("mouseleave", "suppliers", () => { map.getCanvas().style.cursor = ""; popup.remove(); });
  }

  function addControls() {
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-left");
    class ResetControl {
      onAdd() {
        const div = document.createElement("div");
        div.className = "maplibregl-ctrl maplibregl-ctrl-group";
        div.innerHTML = `<button type="button" class="sp-reset" title="Reset view">&#8634;</button>`;
        div.querySelector("button").onclick = () => { if (fitBox) map.fitBounds(fitBox, { padding: 50, maxZoom: 5, duration: 800 }); };
        return div;
      }
      onRemove() {}
    }
    map.addControl(new ResetControl(), "top-left");
  }

  function ensure() {
    if (styleReady) return styleReady;
    injectCss();
    styleReady = pickStyle().then(({ style, online }) => new Promise((resolve) => {
      map = new maplibregl.Map({
        container: "map-overview", style, center: [112, 18], zoom: 2.6, minZoom: 0.6, maxZoom: 12,
        dragRotate: false, pitchWithRotate: false, touchPitch: false, attributionControl: { compact: true },
        renderWorldCopies: true,
      });
      map.touchZoomRotate.disableRotation();
      map.on("load", () => {
        if (online) { englishLabels(); tint(); }
        addOurLayers();
        addControls();
        map.on("zoom", updatePortNames);
        resolve();
      });
    }));
    return styleReady;
  }

  // ------------------------------------------------------------------ geometry helpers (display only)
  const unwrap = (lon, ref) => { while (lon - ref > 180) lon -= 360; while (lon - ref < -180) lon += 360; return lon; };

  function curve(a, b, n = 48) {
    // a, b = [lon, lat]; b is shifted to the same world copy as a so long routes take the short way round
    const bx = unwrap(b[0], a[0]);
    const mx = (a[0] + bx) / 2, my = (a[1] + b[1]) / 2;
    const dx = bx - a[0], dy = b[1] - a[1];
    const cx = mx - dy * 0.22, cy = my + dx * 0.22;
    const pts = [];
    for (let i = 0; i <= n; i++) {
      const t = i / n;
      pts.push([(1 - t) * (1 - t) * a[0] + 2 * (1 - t) * t * cx + t * t * bx,
                (1 - t) * (1 - t) * a[1] + 2 * (1 - t) * t * cy + t * t * b[1]]);
    }
    return pts;
  }

  function pointAt(pts, t) {
    const f = t * (pts.length - 1), i = Math.floor(f), k = f - i;
    const p = pts[i], q = pts[Math.min(i + 1, pts.length - 1)];
    return [p[0] + (q[0] - p[0]) * k, p[1] + (q[1] - p[1]) * k];
  }

  function colorOf(s, scenario) {
    if (s.affected && scenario && scenario.type === "supply") return C.red;
    if (s.at_risk) return C.amber;
    return s.is_alternative ? C.alt : C.blue;
  }

  function tooltipHtml(s, scenario) {
    const esc = SP.esc;
    return `<b>${esc(s.name)}</b><br/>${esc(s.country)} · ${s.is_alternative ? "Alternative supplier" : "Current supplier"}<br/>
      ${esc(s.material_id)} ${esc(s.material_name)}<br/>
      Share of material: ${s.share_pct}% · Share of supply spend: ${s.share_of_total_spend_pct}%<br/>
      Lead time: ${s.lead_time_days} days · Capacity: ${SP.fmt.num(s.capacity_units_per_week)} /week<br/>
      Route: ${esc(s.ship_route)}${s.affected && scenario && scenario.type === "supply" ? `<br/><b style="color:#fca5a5">Affected by the scenario</b>` : ""}`;
  }

  // ------------------------------------------------------------------ ports
  function portRole(name, supplierPorts, epiName, customerPortNames) {
    if (epiName && name === epiName) return ["Closed by the scenario", C.red, 0];
    if (name === "Penang Port") return ["Our import / export port", C.home, 3];     // name only when zoomed in (it sits next to our plant)
    if (supplierPorts.has(name)) return ["Our suppliers ship from here", C.blue, 1];
    if (customerPortNames.has(name)) return ["Our customers receive here", C.violet, 1];
    return ["Major container port", C.port, 2];
  }

  function updatePortNames() {
    if (!map) return;
    const z = map.getZoom();
    markers.forEach((m) => {
      if (m.portTier === undefined) return;
      const el = m.getElement();
      // tier 0 always named; tier 1 (our ports) from zoom 3; tier 2 (other ports) shown from zoom 3, named from zoom 4.5
      el.classList.toggle("hidden", m.portTier === 2 && z < 3);
      el.classList.toggle("hide-name", (m.portTier === 1 && z < 3) || (m.portTier === 2 && z < 4.5) || (m.portTier === 3 && z < 6));
    });
  }

  // ------------------------------------------------------------------ draw
  async function drawMap(suppliers, scenario) {
    pending = [suppliers, scenario];
    await ensure();
    if (pending[0] !== suppliers || pending[1] !== scenario) return;   // a newer call is in progress
    current = pending;
    const esc = SP.esc;
    const exp = scenario && scenario.exposure;
    const company = exp ? exp.map.company : SP.state.baseline.exposure.map.company;
    const home = [company.lon, company.lat];
    const demand = scenario && scenario.type === "demand";
    const epi = scenario && exp && !demand ? exp.map.epicentre : null;
    const portByName = Object.fromEntries(PORTS.map((p) => [p[0], p]));

    // supplier routes + markers
    const supplierPorts = new Set();
    const routes = [], points = [];
    suppliers.forEach((s) => {
      const col = colorOf(s, scenario);
      const hit = s.affected && scenario && scenario.type === "supply";
      const from = String(s.ship_route || "").split("->")[0].trim();
      if (ROUTE_PORT[from] && !s.is_alternative) supplierPorts.add(ROUTE_PORT[from]);
      routes.push({ type: "Feature", properties: { color: col, width: hit ? 2.4 : s.is_alternative ? 1 : 1.6,
          glow: hit ? 9 : 6, opacity: s.is_alternative ? 0.35 : hit ? 0.95 : 0.6, particle: !s.is_alternative,
          period: hit ? 2600 : 4800 },
        geometry: { type: "LineString", coordinates: curve([s.lon, s.lat], home) } });
      const r = s.is_alternative ? 5 : 5 + Math.sqrt(s.share_of_total_spend_pct) * 1.3;
      points.push({ type: "Feature", properties: { color: col, fill: s.is_alternative ? "rgba(56,189,248,.15)" : col, r,
          html: tooltipHtml(s, scenario) },
        geometry: { type: "Point", coordinates: [s.lon, s.lat] } });
    });

    // customer trade lanes from Penang Port to each customer market (amber in a demand shock)
    const customerPortNames = new Set(Object.values(CUSTOMER_PORTS));
    const penang = portByName["Penang Port"];
    const lanes = Object.values(CUSTOMER_PORTS).map((pn) => {
      const p = portByName[pn];
      return { type: "Feature", properties: { color: demand ? C.amber : C.violet },
               geometry: { type: "LineString", coordinates: curve([penang[2], penang[1]], [p[2], p[1]], 64) } };
    });

    map.getSource("routes").setData({ type: "FeatureCollection", features: routes });
    map.getSource("suppliers").setData({ type: "FeatureCollection", features: points });
    map.getSource("lanes").setData({ type: "FeatureCollection", features: lanes });

    // HTML markers: ports, our plant, disruption
    markers.forEach((m) => m.remove());
    markers = [];
    PORTS.forEach(([name, lat, lon, country]) => {
      const [role, col, tier] = portRole(name, supplierPorts, epi && epi.name, customerPortNames);
      if (epi && name === epi.name) return;                      // drawn as the disruption marker below
      const el = document.createElement("div");
      el.className = "sp-port";
      el.style.setProperty("--c", col);
      el.innerHTML = `<span class="dot"></span><span class="nm">${esc(name)}</span>`;
      const m = new maplibregl.Marker({ element: el, anchor: "left", offset: [-5, 0] }).setLngLat([lon, lat])
        .setPopup(new maplibregl.Popup({ offset: 12, closeButton: false })
          .setHTML(`<b>${esc(name)}</b><br/>${esc(country)}<br/><span style="color:${col}">${esc(role)}</span>`))
        .addTo(map);
      m.portTier = tier;
      markers.push(m);
    });

    const homeEl = document.createElement("div");
    if (demand) {
      homeEl.className = "sp-epi";
      homeEl.innerHTML = `<div class="pulse amber"><div class="ring"></div><div class="ring r2"></div><div class="core"></div></div>
        <span class="map-tag amber">Our plant: customer orders falling</span>`;
    } else {
      homeEl.className = "sp-home";
      homeEl.innerHTML = `<div class="sq"></div><div class="lb">Our plant</div>`;
    }
    markers.push(new maplibregl.Marker({ element: homeEl, anchor: demand ? "left" : "top", offset: demand ? [-11, 0] : [0, -7] })
      .setLngLat(home).setPopup(new maplibregl.Popup({ offset: 12, closeButton: false })
        .setHTML(`<b>${esc(company.label)}</b><br/>${esc(company.name)}`)).addTo(map));

    if (epi) {
      const el = document.createElement("div");
      el.className = "sp-epi";
      el.innerHTML = `<div class="pulse"><div class="ring"></div><div class="ring r2"></div><div class="core"></div></div>
        <span class="map-tag">Port closure: ${esc(epi.name)}</span>`;
      markers.push(new maplibregl.Marker({ element: el, anchor: "left", offset: [-11, 0] }).setLngLat([epi.lon, epi.lat]).addTo(map));
    }
    updatePortNames();

    // frame the plant, the suppliers and the disruption
    const pts = [home, ...suppliers.map((s) => [s.lon, s.lat])];
    if (epi) pts.push([epi.lon, epi.lat]);
    fitBox = pts.reduce((b, p) => b.extend(p), new maplibregl.LngLatBounds(pts[0], pts[0]));
    map.fitBounds(fitBox, { padding: 50, maxZoom: 5, duration: 0 });

    startParticles(routes);
  }

  // moving glow dots along the current supplier routes
  function startParticles(routes) {
    cancelAnimationFrame(anim);
    const live = routes.filter((r) => r.properties.particle);
    let lastT = 0;
    const tick = (now) => {
      anim = requestAnimationFrame(tick);
      if (now - lastT < 33) return;                                // ~30 frames per second is plenty
      lastT = now;
      const feats = [];
      live.forEach((r, i) => {
        const pts = r.geometry.coordinates, period = r.properties.period;
        for (const off of [0, 0.5]) {
          const t = ((now / period) + i * 0.13 + off) % 1;
          const glow = { [C.red]: "#fecaca", [C.amber]: "#fde68a" }[r.properties.color] || "#bfdbfe";
          feats.push({ type: "Feature", properties: { color: glow },
                       geometry: { type: "Point", coordinates: pointAt(pts, t) } });
        }
      });
      const src = map.getSource("particles");
      if (src) src.setData({ type: "FeatureCollection", features: feats });
    };
    anim = requestAnimationFrame(tick);
  }

  function invalidate() {
    if (!map) return;
    map.resize();
  }

  return { drawMap, invalidate };
})();
