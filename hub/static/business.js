// KPI cards, charts, filters, drill downs, recommendations, live feed. Owner: A.
(function () {
  const F = {};                               // global filters
  const charts = {};
  let last = null;

  function query(extra) {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries({ ...F, ...(extra || {}) })) if (v) p.set(k, v);
    return p.toString();
  }

  // ------------------------------------------------------------------ drill down modal
  function ensureModal() {
    let bg = document.getElementById("drilldown");
    if (!bg) { bg = document.createElement("div"); bg.id = "drilldown"; document.body.appendChild(bg); }
    if (!bg.dataset.ready) {
      bg.className = "modal-bg"; bg.dataset.ready = "1";
      bg.innerHTML = `<div class="modal"><header><b class="dd-title"></b><span class="muted dd-count"></span>
        <button class="small dd-csv">Export CSV</button><button class="small dd-close">Close</button></header>
        <div class="content"><table class="dt"><thead></thead><tbody></tbody></table></div></div>`;
      bg.addEventListener("click", (e) => { if (e.target === bg) bg.classList.remove("open"); });
      bg.querySelector(".dd-close").onclick = () => bg.classList.remove("open");
      document.addEventListener("keydown", (e) => { if (e.key === "Escape") bg.classList.remove("open"); });
    }
    return bg;
  }

  async function drill(kpi, title, extra) {
    const bg = ensureModal();
    bg.querySelector(".dd-title").textContent = title || kpi;
    bg.querySelector("thead").innerHTML = ""; bg.querySelector("tbody").innerHTML = `<tr><td class="muted">Loading...</td></tr>`;
    bg.classList.add("open");
    const r = await UI.get(`/api/drilldown?kpi=${encodeURIComponent(kpi)}&${query(extra)}`);
    const cols = r.columns || [], rows = r.rows || [];
    bg.querySelector(".dd-count").textContent = `${rows.length} rows`;
    bg.querySelector("thead").innerHTML = `<tr>${cols.map((c, i) => `<th data-i="${i}">${UI.esc(c)}</th>`).join("")}</tr>`;
    const render = (rs) => bg.querySelector("tbody").innerHTML = rs.map(row => `<tr>${row.map((v, i) => {
      const c = cols[i]; let s = v === null ? "" : v;
      if (c === "status") s = `<span class="status-${v}">${UI.esc(v)}</span>`;
      else if (c === "amount") s = UI.money(v);
      else s = UI.esc(typeof v === "string" && v.startsWith("[") ? JSON.parse(v).join(", ") : s);
      return `<td>${s}</td>`; }).join("")}</tr>`).join("") || `<tr><td class="muted">No data for these filters</td></tr>`;
    render(rows);
    bg.querySelectorAll("th").forEach(th => th.onclick = () => {
      const i = +th.dataset.i, dir = th.dataset.dir = th.dataset.dir === "asc" ? "desc" : "asc";
      render([...rows].sort((a, b) => (a[i] > b[i] ? 1 : -1) * (dir === "asc" ? 1 : -1)));
    });
    bg.querySelector(".dd-csv").onclick = () => {
      const csv = [cols.join(","), ...rows.map(r => r.map(v => `"${String(v ?? "").replace(/"/g, '""')}"`).join(","))].join("\n");
      const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
      a.download = `${kpi.replace(":", "_")}.csv`; a.click();
    };
  }

  // ------------------------------------------------------------------ KPI cards
  function card(id, label, value, sub, kpi, title) {
    return `<div class="kpi" data-id="${id}" data-kpi="${kpi}" data-title="${UI.esc(title || label)}" title="Click for details">
      <div class="label">${label}</div><div class="value">${value}</div><div class="sub">${sub || ""}</div></div>`;
  }

  function cardsHTML(k, mini) {
    const p = k.payments, fc = (k.revenue_forecast_7d || []).reduce((s, x) => s + x.value, 0);
    const topAlert = Object.entries(k.alerts_by_type || {}).sort((a, b) => b[1] - a[1])[0];
    const all = [
      card("rev", "Revenue (simulated)", UI.money(k.revenue_simulated), `forecast 7d: ${UI.money(fc)}`, "revenue", "Succeeded payments"),
      card("conv", "Conversion", UI.pct(k.conversion_rate), `${p.succeeded} paid / ${k.interactions_total}`, "conversion", "Converted interactions"),
      card("int", "Interactions", k.interactions_total, `voice ${k.by_channel.voice || 0} · text ${k.by_channel.text || 0}`, "interactions", "All interactions"),
      card("intr", "Interested", k.interested_total, k.interactions_total ? UI.pct(k.interested_total / k.interactions_total) + " of leads" : "", "interested", "Interested customers"),
      card("ok", "Payments succeeded", p.succeeded, "sandbox", "payments:succeeded", "Succeeded payments"),
      card("ko", "Refused", p.refused, "bank or security", "payments:refused", "Refused payments"),
      card("pend", "Pending", p.pending, "incl. human validation", "payments:pending", "Pending payments"),
      card("sat", "Satisfaction", k.avg_satisfaction ? k.avg_satisfaction + " / 5" : "-", "from Intel Agent", "satisfaction", "Interactions with satisfaction"),
      card("al", "Security alerts", k.alerts_total, topAlert ? `top: ${topAlert[0]}` : "none", "alerts", "Security alerts"),
    ];
    return mini ? [all[0], all[1], all[4], all[8]].join("") : all.join("");
  }

  function bindCards(root) {
    root.querySelectorAll(".kpi[data-kpi]").forEach(el => el.onclick = () => drill(el.dataset.kpi, el.dataset.title));
  }

  function flashChanges(root, k) {
    if (!last) return;
    const changed = { rev: k.revenue_simulated !== last.revenue_simulated, conv: k.conversion_rate !== last.conversion_rate,
      int: k.interactions_total !== last.interactions_total, intr: k.interested_total !== last.interested_total,
      ok: k.payments.succeeded !== last.payments.succeeded, ko: k.payments.refused !== last.payments.refused,
      pend: k.payments.pending !== last.payments.pending, sat: k.avg_satisfaction !== last.avg_satisfaction,
      al: k.alerts_total !== last.alerts_total };
    for (const [id, c] of Object.entries(changed)) if (c) { const el = root.querySelector(`.kpi[data-id="${id}"]`); el && el.classList.add("flash"); }
  }

  // ------------------------------------------------------------------ charts
  function setupChartDefaults() {
    if (!window.Chart || Chart._louben) return;
    Chart._louben = true;
    Chart.defaults.color = "#8b9bb4"; Chart.defaults.borderColor = "#1c2638";
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
    Chart.defaults.plugins.legend.labels.boxWidth = 10;
    Chart.defaults.maintainAspectRatio = false;
    Chart.defaults.animation.duration = 450;
  }

  function chart(id, cfg, onPick) {
    const el = document.getElementById(id); if (!el) return;
    let cv = el.querySelector("canvas");
    if (!cv) { el.innerHTML = `<div class="chart-box"><canvas></canvas></div>`; cv = el.querySelector("canvas"); }
    cfg.options = cfg.options || {};
    cfg.options.onClick = (e, els) => { if (els.length && onPick) onPick(els[0].index, els[0].datasetIndex); };
    cfg.options.onHover = (e, els) => { e.native.target.style.cursor = els.length ? "pointer" : "default"; };
    if (charts[id]) { charts[id].data = cfg.data; charts[id].update(); return; }
    charts[id] = new Chart(cv, cfg);
  }

  const PAL = ["#22d3ee", "#a78bfa", "#f59e0b", "#34d399", "#f472b6", "#60a5fa", "#ef4444", "#fbbf24"];

  function renderCharts(k) {
    setupChartDefaults();
    const days = k.daily || [];
    chart("conversion-chart", { type: "bar", data: { labels: days.map(d => d.date.slice(5)), datasets: [
      { type: "bar", label: "Interactions", data: days.map(d => d.interactions), backgroundColor: "#1e3a5f", yAxisID: "y" },
      { type: "line", label: "Conversion %", data: days.map(d => +(d.rate * 100).toFixed(1)), borderColor: "#22d3ee", backgroundColor: "#22d3ee", tension: .35, yAxisID: "y1", pointRadius: 2 }] },
      options: { scales: { y: { beginAtZero: true }, y1: { position: "right", beginAtZero: true, grid: { display: false }, ticks: { callback: v => v + "%" } } } } },
      (i) => drill("interactions", `Interactions on ${days[i].date}`, { from: days[i].date, to: days[i].date }));

    const ob = k.top_objections || [];
    chart("objections-chart", { type: "bar", data: { labels: ob.map(o => o.label), datasets: [
      { label: "Objections", data: ob.map(o => o.count), backgroundColor: ob.map((_, i) => PAL[i % PAL.length]) }] },
      options: { indexAxis: "y", plugins: { legend: { display: false } } } },
      (i) => drill(`objections:${ob[i].label}`, `Interactions with objection: ${ob[i].label}`));

    const pl = ["succeeded", "refused", "pending"];
    chart("payments-chart", { type: "doughnut", data: { labels: pl, datasets: [
      { data: pl.map(s => k.payments[s]), backgroundColor: ["#22c55e", "#ef4444", "#f59e0b"], borderWidth: 0 }] },
      options: { cutout: "62%", plugins: { legend: { position: "bottom" } } } },
      (i) => drill(`payments:${pl[i]}`, `Payments ${pl[i]}`));

    const fc = k.revenue_forecast_7d || [];
    const labels = [...days.map(d => d.date), ...fc.map(f => f.date)].map(d => d.slice(5));
    chart("revenue-chart", { type: "line", data: { labels, datasets: [
      { label: "Revenue (TND)", data: [...days.map(d => d.revenue), ...fc.map(() => null)], borderColor: "#34d399", backgroundColor: "rgba(52,211,153,.12)", fill: true, tension: .3, pointRadius: 2 },
      { label: "Forecast 7d (ML)", data: [...days.map((d, i) => i === days.length - 1 ? d.revenue : null), ...fc.map(f => f.value)], borderColor: "#a78bfa", borderDash: [6, 4], pointRadius: 2, tension: .3 }] },
      options: { scales: { y: { beginAtZero: true } } } },
      (i) => { if (i < days.length) drill("revenue", `Revenue on ${days[i].date}`, { from: days[i].date, to: days[i].date }); });

    const sd = k.satisfaction_dist || {};
    chart("satisfaction-chart", { type: "bar", data: { labels: ["1", "2", "3", "4", "5"], datasets: [
      { label: "Customers", data: [1, 2, 3, 4, 5].map(i => sd[i] || 0), backgroundColor: ["#ef4444", "#f97316", "#f59e0b", "#84cc16", "#22c55e"] }] },
      options: { plugins: { legend: { display: false } } } },
      (i) => drill(`satisfaction:${i + 1}`, `Satisfaction ${i + 1}/5`));

    const seg = Object.entries(k.by_segment || {});
    chart("segment-chart", { type: "doughnut", data: { labels: seg.map(s => s[0]), datasets: [
      { data: seg.map(s => s[1]), backgroundColor: PAL, borderWidth: 0 }] },
      options: { cutout: "58%", plugins: { legend: { position: "bottom" } } } },
      (i) => drill(`segment:${seg[i][0]}`, `Segment: ${seg[i][0]}`));

    const al = Object.entries(k.alerts_by_type || {}).sort((a, b) => b[1] - a[1]);
    chart("alerts-chart", { type: "bar", data: { labels: al.map(a => a[0]), datasets: [
      { label: "Alerts", data: al.map(a => a[1]), backgroundColor: "#ef4444" }] },
      options: { plugins: { legend: { display: false } } } },
      (i) => drill(`alerts:${al[i][0]}`, `Alerts: ${al[i][0]}`));
  }

  // ------------------------------------------------------------------ refresh
  async function refresh(opts = {}) {
    const k = await UI.get("/api/kpis?" + query());
    if (k.error) return;
    const row = document.getElementById("kpi-row");
    if (row) { row.innerHTML = cardsHTML(k, opts.mini || row.dataset.mini === "1"); bindCards(row); flashChanges(row, k); }
    if (!opts.mini) renderCharts(k);
    last = k;
    document.dispatchEvent(new CustomEvent("kpis", { detail: k }));
    return k;
  }

  // ------------------------------------------------------------------ filters
  async function mountFilters(el, onChange) {
    const cat = await UI.get("/api/catalog");
    el.innerHTML = `<div class="filters">
      <label>From<input type="date" data-f="from"></label><label>To<input type="date" data-f="to"></label>
      <label>Segment<select data-f="segment"><option value="">All</option><option>student</option><option>professional</option><option>individual</option><option>company</option></select></label>
      <label>Product<select data-f="product_id"><option value="">All</option>${(cat.products || []).map(p => `<option value="${p.product_id}">${UI.esc(p.name)}</option>`).join("")}</select></label>
      <label>Channel<select data-f="channel"><option value="">All</option><option>voice</option><option>text</option></select></label>
      <label>&nbsp;<span><button class="small" data-q="7">Last 7 days</button> <button class="small" data-q="30">30 days</button> <button class="small reset">Reset</button></span></label>
    </div>`;
    const sync = () => { el.querySelectorAll("[data-f]").forEach(i => { F[i.dataset.f] = i.value || undefined; }); onChange && onChange(); };
    el.querySelectorAll("[data-f]").forEach(i => i.onchange = sync);
    el.querySelectorAll("[data-q]").forEach(b => b.onclick = () => {
      const d = new Date(); const from = new Date(d - (+b.dataset.q - 1) * 864e5);
      el.querySelector('[data-f="from"]').value = from.toISOString().slice(0, 10);
      el.querySelector('[data-f="to"]').value = d.toISOString().slice(0, 10); sync();
    });
    el.querySelector(".reset").onclick = () => { el.querySelectorAll("[data-f]").forEach(i => i.value = ""); sync(); };
  }

  // ------------------------------------------------------------------ recommendations
  async function mountRecommendations(el) {
    el.innerHTML = `<div style="display:flex;gap:8px;margin-bottom:10px"><button class="primary small gen">Ask Strategy Agent</button>
      <span class="muted" style="font-size:12px;align-self:center">Recommendations are applied only after human approval.</span></div><div class="list recs"></div>`;
    const list = el.querySelector(".recs");
    const items = new Map();
    const draw = () => {
      list.innerHTML = [...items.values()].reverse().slice(0, 6).map(r => `<div class="item">
        <div class="top"><b>${UI.esc(r.title)}</b>${r.status === "proposed"
          ? `<button class="small ok" data-a="approve" data-id="${r.rec_id}">Approve</button><button class="small danger" data-a="reject" data-id="${r.rec_id}">Reject</button>`
          : `<span class="pill ${r.status === "approved" ? "ok" : "bad"}">${r.status}</span>`}</div>
        <div class="muted" style="margin-top:4px">${UI.esc(r.rationale)}</div>
        ${r.expected_impact ? `<div style="margin-top:4px;font-size:12px">Expected impact: ${UI.esc(r.expected_impact)}</div>` : ""}</div>`).join("")
        || `<div class="empty">No recommendation yet. Click "Ask Strategy Agent".</div>`;
      list.querySelectorAll("[data-a]").forEach(b => b.onclick = async () => {
        const r = await UI.post("/api/recommendations/decision", { rec_id: b.dataset.id, decision: b.dataset.a });
        if (r.rec_id) { items.set(r.rec_id, r); draw(); }
      });
    };
    el.querySelector(".gen").onclick = async (e) => {
      e.target.disabled = true; e.target.textContent = "Thinking...";
      await UI.post("/api/recommendations/run?" + query(), {});
      e.target.disabled = false; e.target.textContent = "Ask Strategy Agent";
    };
    Bus.on("strategy.recommendation", (ev) => { (ev.data.items || []).forEach(r => items.set(r.rec_id, r)); draw(); });
    const r = await UI.get("/api/recommendations"); (r.items || []).forEach(x => items.set(x.rec_id, x));
    draw();
  }

  // ------------------------------------------------------------------ live feed
  function describe(ev) {
    const d = ev.data || {};
    switch (ev.type) {
      case "a2a.call": return `${d.from} → ${d.to} · ${d.skill} · ${d.status} (${d.latency_ms} ms) ${d.summary || ""}`;
      case "interaction.message": return `${d.role}: ${d.text}`;
      case "security.alert": return `ALERT ${d.type} (${d.severity}) ${d.details ? JSON.stringify(d.details).slice(0, 90) : ""}`;
      case "gate.signature": return `${d.signer} key: ${d.decision} · ${d.reason}`;
      case "payment.status": return `payment ${d.status} · ${UI.money(d.amount)}`;
      case "redteam.attack": return `${d.blocked ? "BLOCKED" : "PASSED"} ${d.name} → ${d.target}`;
      case "intel.report": return `objections: ${(d.objections || []).join(", ") || "none"} · sentiment ${d.sentiment} · segment ${d.segment}`;
      default: return JSON.stringify(d).slice(0, 140);
    }
  }

  function mountFeed(el, opts = {}) {
    el.classList.add("feed");
    const skip = new Set(opts.skip || ["input.checked"]);
    const add = (ev) => {
      if (skip.has(ev.type)) return;
      const row = document.createElement("div");
      row.className = "row";
      const color = UI.colors[ev.source] || "#94a3b8";
      row.innerHTML = `<span class="t">${UI.time(ev.ts)}</span><span class="src" style="color:${color}">${UI.esc(ev.source)}</span>
        <span class="txt" title="${UI.esc(ev.type)}"><span class="muted">${UI.esc(ev.type)}</span> ${UI.esc(describe(ev))}</span>`;
      el.prepend(row);
      while (el.children.length > (opts.max || 120)) el.lastChild.remove();
    };
    Bus.on("*", add);
    UI.get("/api/events?limit=80").then(r => (r.items || []).forEach(add)).catch(() => {});
  }

  // ------------------------------------------------------------------ public
  const autoRefresh = UI.debounce((mini) => refresh({ mini }), 1200);
  function liveRefresh(mini) {
    ["payment.status", "interaction.ended", "intel.report", "security.alert", "gate.rejected", "gate.pending_human"]
      .forEach(t => Bus.on(t, () => autoRefresh(mini)));
  }

  window.Business = { F, query, refresh, drill, mountFilters, mountRecommendations, mountFeed, liveRefresh, describe };
})();
