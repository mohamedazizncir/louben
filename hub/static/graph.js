// Live agent collaboration graph + knowledge graph (Cytoscape.js, vendored). Owner: A.
(function () {
  const C = () => UI.colors;
  const ROLES = {
    customer: "Customer (voice/text)", sales: "Voice Sales", intel: "Customer Intel", payment: "Payment (sandbox)",
    analyst: "Financial Analyst", strategy: "Business Strategy", security: "Security & Fraud", redteam: "Red Team",
    gate: "Multisig Gate", operator: "Human operator",
  };
  const SHORT = {
    customer: "Customer\nvoice / text", sales: "Sales\nvoice + offers", intel: "Intel\nneeds · objections",
    payment: "Payment\nsandbox", analyst: "Analyst\nKPIs · co-signer", strategy: "Strategy\nrecommendations",
    security: "Security\nguard · fraud · co-signer", redteam: "Red Team\nattacks 24/7", gate: "Multisig Gate\n3 agents + human",
    operator: "Operator\nhuman key",
  };
  const POS = {
    intel: { x: 210, y: 0 }, analyst: { x: 420, y: 0 }, strategy: { x: 630, y: 0 },
    customer: { x: 0, y: 150 }, sales: { x: 210, y: 150 }, payment: { x: 420, y: 150 }, gate: { x: 630, y: 150 },
    redteam: { x: 0, y: 300 }, security: { x: 420, y: 300 }, operator: { x: 630, y: 300 },
  };

  function baseStyle() {
    return [
      { selector: "node", style: {
          "shape": "round-rectangle", "width": 168, "height": 60, "background-color": "#131d2e",
          "border-width": 2, "border-color": "data(color)", "label": "data(label)", "color": "#e6edf6",
          "font-size": 15, "font-weight": 600, "text-wrap": "wrap", "line-height": 1.25, "text-valign": "center", "text-halign": "center",
          "transition-property": "background-color, border-width", "transition-duration": "0.25s" } },
      { selector: "node.busy", style: { "background-color": "data(color)", "color": "#06121a", "border-width": 4 } },
      { selector: "node.dot", style: { "width": 16, "height": 16, "shape": "ellipse", "background-color": "data(color)",
          "border-width": 0, "label": "", "z-index": 99 } },
      { selector: "edge", style: {
          "width": 1.5, "line-color": "#24324a", "target-arrow-color": "#24324a", "target-arrow-shape": "triangle",
          "curve-style": "bezier", "arrow-scale": 0.9, "label": "data(label)", "font-size": 13, "color": "#e2e8f0",
          "text-background-color": "#0a0e16", "text-background-opacity": 0.85, "text-background-padding": 2,
          "text-rotation": "autorotate", "transition-property": "line-color, width, target-arrow-color",
          "transition-duration": "0.3s" } },
      { selector: "edge.attack", style: { "line-style": "dashed" } },
      { selector: "edge.ok", style: { "line-color": "#22c55e", "target-arrow-color": "#22c55e", "width": 4 } },
      { selector: "edge.refused", style: { "line-color": "#ef4444", "target-arrow-color": "#ef4444", "width": 4 } },
      { selector: "edge.error", style: { "line-color": "#f59e0b", "target-arrow-color": "#f59e0b", "width": 4 } },
      { selector: "node:selected", style: { "border-width": 5 } },
    ];
  }

  function mapCall(d) {
    let from = d.from, to = d.to;
    if (from === "hub") from = (d.skill === "chat" || d.skill === "end_session") ? "customer" : "operator";
    return { from, to };
  }

  // ------------------------------------------------------------------ agent graph
  function mountAgentGraph(wrap) {
    wrap.innerHTML = `
      <div class="keys"><div class="title">Multisig gate</div>
        <div class="row">
          <div class="key" data-k="payment"><span class="ic">🔑</span>Payment</div>
          <div class="key" data-k="security"><span class="ic">🔑</span>Security</div>
          <div class="key" data-k="analyst"><span class="ic">🔑</span>Analyst</div>
          <div class="key" data-k="human"><span class="ic">👤</span>Human</div>
        </div><div class="status">Waiting for a payment...</div></div>
      <div class="cyhost"><div class="cy"></div>
      <div class="legend"><span><i style="background:#22c55e"></i>ok</span><span><i style="background:#ef4444"></i>refused</span>
        <span><i style="background:#f59e0b"></i>error</span><span><i style="background:#fb7185;height:0;border-top:2px dashed #fb7185"></i>attack</span>
        <span class="count">0 A2A calls</span></div>
      <div class="side-panel"></div></div>`;
    const nodes = Object.keys(POS).map(id => ({ data: { id, color: C()[id] || "#94a3b8",
      label: SHORT[id] }, position: POS[id] }));
    const cy = cytoscape({ container: wrap.querySelector(".cy"), elements: nodes, style: baseStyle(), layout: { name: "preset" },
      userZoomingEnabled: true, boxSelectionEnabled: false, autoungrabify: false });
    const fit = () => { cy.resize(); cy.fit(cy.nodes().not(".dot"), 24); };
    fit(); new ResizeObserver(fit).observe(wrap.querySelector(".cyhost"));

    let count = 0, agentsInfo = null;
    const countEl = wrap.querySelector(".count");

    function edge(from, to) {
      const id = `${from}->${to}`;
      let e = cy.getElementById(id);
      if (e.empty()) e = cy.add({ group: "edges", data: { id, source: from, target: to, label: "" },
                                   classes: from === "redteam" ? "attack" : "" });
      return e;
    }
    // static topology from the least privilege ACL
    UI.get("/api/agents").then(r => {
      agentsInfo = r;
      edge("customer", "sales"); edge("sales", "customer"); edge("operator", "gate"); edge("operator", "redteam"); edge("operator", "strategy");
      for (const [caller, rules] of Object.entries(r.acl || {})) {
        if (caller === "hub") continue;
        for (const rule of rules) { const t = rule.split(":")[0]; if (POS[t] && POS[caller]) edge(caller, t); }
      }
    }).catch(() => {});

    function animate(from, to, status, skill) {
      if (!POS[from] || !POS[to]) return;
      const e = edge(from, to);
      e.removeClass("ok refused error").addClass(status);
      e.data("label", skill);
      clearTimeout(e.scratch("_t"));
      e.scratch("_t", setTimeout(() => { e.removeClass("ok refused error"); e.data("label", ""); }, 1800));
      const src = cy.getElementById(from), dst = cy.getElementById(to);
      const dot = cy.add({ group: "nodes", data: { id: `dot${Math.random()}`, color: status === "ok" ? "#22c55e" : status === "refused" ? "#ef4444" : "#f59e0b" },
                           position: { ...src.position() }, classes: "dot" });
      dot.animate({ position: { ...dst.position() } }, { duration: 650, easing: "ease-in-out-cubic", complete: () => dot.remove() });
      dst.addClass("busy"); setTimeout(() => dst.removeClass("busy"), 700);
    }

    // ---- multisig keys
    const keys = wrap.querySelector(".keys"), status = keys.querySelector(".status");
    const setKey = (k, cls) => { const el = keys.querySelector(`[data-k="${k}"]`); if (el) { el.classList.remove("approve", "refuse", "wait"); if (cls) el.classList.add(cls); } };

    // ---- playback queue: a full payment (intent, 3 signatures, execute) takes ~100 ms, far too fast to follow.
    // Events are buffered, put back in causal order (a2a.call is emitted when the call ENDS, so sort on started_ms)
    // and replayed at human speed. Panels that must stay in sync listen with Bus.onShown().
    const PLAY = new Set(["a2a.call", "interaction.message", "payment.intent_created", "gate.signature",
      "gate.pending_human", "gate.approved", "gate.rejected", "payment.status"]);
    let buf = [], queue = [], flushT = null, firstAt = 0, playing = false;
    Bus.setPlayer();
    Bus.on("*", (ev) => {
      if (!PLAY.has(ev.type)) { Bus.shown(ev); return; }
      buf.push(ev);
      firstAt = firstAt || Date.now();
      clearTimeout(flushT);
      flushT = setTimeout(flush, Math.max(0, Math.min(250, 800 - (Date.now() - firstAt))));
    });

    function order(items) {
      const calls = items.filter(e => e.type === "a2a.call" && e.data.started_ms);
      const startOf = (pred) => { const c = calls.find(pred); return c ? c.data.started_ms : null; };
      const first = calls.length ? Math.min(...calls.map(c => c.data.started_ms)) : 0;
      const last = calls.length ? Math.max(...calls.map(c => c.data.started_ms)) : 0;
      items.forEach((e, i) => {
        const d = e.data || {};
        let k;
        if (e.type === "a2a.call") k = d.started_ms || last + i;
        else if (e.type === "interaction.message") k = d.role === "customer" ? first - 2 : last + 1e5 + i;
        else if (e.type === "payment.intent_created") k = (startOf(c => c.data.to === "gate" && c.data.skill === "submit") ?? last) - 1;
        else if (e.type === "gate.signature") k = (startOf(c => c.data.from === "gate" && c.data.to === d.signer && c.data.skill === "sign") ?? last) + 0.5;
        else k = last + 1e4 + i;                                      // outcomes last, in arrival order
        e._k = k; e._i = i;
      });
      return items.sort((a, b) => a._k - b._k || a._i - b._i);
    }

    function flush() {
      firstAt = 0; queue.push(...order(buf)); buf = [];
      if (!playing) next();
    }

    function next() {
      const ev = queue.shift();
      if (!ev) { playing = false; return; }
      playing = true;
      const speed = queue.length > 12 ? 0.25 : queue.length > 6 ? 0.6 : 1;   // red team bursts: catch up
      setTimeout(next, show(ev) * speed);
    }

    function show(ev) {                                     // returns how long to wait before the next event
      const d = ev.data || {};
      Bus.shown(ev);
      switch (ev.type) {
        case "a2a.call": {
          countEl.textContent = `${++count} A2A calls`;
          if (d.from === "hub" && d.skill === "chat") return 0;          // drawn from interaction.message instead
          const { from, to } = mapCall(d);
          animate(from, to, d.status, d.skill);
          return 420;
        }
        case "interaction.message":
          if (d.role === "customer") animate("customer", "sales", "ok", "chat");
          else animate("sales", "customer", "ok", "reply");
          return 300;
        case "payment.intent_created":
          ["payment", "security", "analyst", "human"].forEach(k => setKey(k, null));
          status.textContent = `Intent ${UI.money(d.amount)}: collecting signatures...`;
          return 250;
        case "gate.signature":
          setKey(d.signer, d.decision === "approve" ? "approve" : "refuse");
          return 380;
        case "gate.pending_human":
          setKey("human", "wait"); status.innerHTML = `<b style="color:#fde68a">Human key needed</b>: ${UI.esc(d.reason)}`;
          return 300;
        case "gate.approved":
          status.innerHTML = `<b style="color:#86efac">Executed</b> · payment ${UI.esc(d.payment_status)} · ${UI.money(d.amount)}`;
          return 300;
        case "gate.rejected":
          status.innerHTML = `<b style="color:#fca5a5">Rejected</b> · ${UI.esc((d.reasons || []).join("; "))}`;
          return 300;
        default:
          return 150;
      }
    }

    // ---- side panel on click
    const panel = wrap.querySelector(".side-panel");
    cy.on("tap", "node", (e) => {
      const id = e.target.id(); if (id.startsWith("dot")) return;
      const info = agentsInfo && agentsInfo.agents && agentsInfo.agents[id];
      const calls = Bus.history().filter(ev => ev.type === "a2a.call" && [mapCall(ev.data).from, mapCall(ev.data).to].includes(id)).slice(-10).reverse();
      const skills = info && info.card ? info.card.skills.map(s => `<li><b>${UI.esc(s.id)}</b>: ${UI.esc(s.description)}</li>`).join("") : "";
      panel.innerHTML = `<button class="small close">x</button><h4 style="color:${C()[id]}">${UI.esc(ROLES[id] || id)}</h4>
        ${info ? `<div>${info.online ? '<span class="pill ok">online</span>' : '<span class="pill bad">offline</span>'}${info.verified ? '<span class="pill ok">signed card verified</span>' : ""}</div>
        <div class="muted" style="margin:6px 0">${UI.esc(info.card ? info.card.description : "")}</div>
        <b>Skills</b><ul>${skills}</ul>
        <b>Can call (least privilege)</b><div>${(info.can_call || []).map(r => `<span class="pill">${UI.esc(r)}</span>`).join("") || '<span class="muted">nobody</span>'}</div>
        <b>Called by</b><div>${(info.called_by || []).map(r => `<span class="pill">${UI.esc(r)}</span>`).join("") || '<span class="muted">-</span>'}</div>`
        : `<div class="muted">${id === "customer" ? "The customer talks to the Sales Agent through the voice/text UI." : "The human operator validates risky payments, rules and recommendations from the dashboard."}</div>`}
        <b style="display:block;margin-top:8px">Last messages</b>
        ${calls.map(c => `<div class="feed"><div class="row"><span class="t">${UI.time(c.ts)}</span><span class="txt"><span class="status-${c.data.status === "ok" ? "succeeded" : "refused"}">${UI.esc(mapCall(c.data).from)} → ${UI.esc(c.data.to)}</span> ${UI.esc(c.data.skill)} · ${UI.esc(c.data.summary)}</span></div></div>`).join("") || '<div class="muted">no calls yet</div>'}`;
      panel.classList.add("open");
      panel.querySelector(".close").onclick = () => panel.classList.remove("open");
    });
    cy.on("tap", (e) => { if (e.target === cy) panel.classList.remove("open"); });
    return cy;
  }

  // ------------------------------------------------------------------ knowledge graph
  const KG_STYLE = {
    customer: { color: "#60a5fa", shape: "ellipse", size: 22 },
    product: { color: "#22d3ee", shape: "round-rectangle", size: 58 },
    objection: { color: "#f59e0b", shape: "diamond", size: 44 },
    payment: { color: "#22c55e", shape: "round-tag", size: 24 },
    alert: { color: "#ef4444", shape: "triangle", size: 30 },
  };

  function mountKnowledgeGraph(wrap, getQuery) {
    wrap.innerHTML = `<div class="cy"></div>
      <div class="kg-tools">${Object.keys(KG_STYLE).map(t => `<span class="pill" data-t="${t}" style="border-color:${KG_STYLE[t].color}">${t}</span>`).join("")}
        <input class="kg-search" placeholder="Search node..." style="width:150px;padding:4px 8px" />
        <button class="small kg-reload">Refresh</button><span class="muted kg-count"></span></div>
      <div class="kg-info"></div>`;
    const cy = cytoscape({ container: wrap.querySelector(".cy"), style: [
      { selector: "node", style: { "background-color": "data(color)", "shape": "data(shape)", "width": "data(size)", "height": "data(size)",
          "label": "data(label)", "font-size": 11, "color": "#cbd5e1", "text-valign": "bottom", "text-margin-y": 3, "min-zoomed-font-size": 7 } },
      { selector: "node[type='product']", style: { "font-size": 14, "font-weight": 700, "color": "#e6edf6", "text-wrap": "wrap", "text-max-width": 110 } },
      { selector: "node[type='objection']", style: { "font-size": 14, "font-weight": 700, "color": "#fde68a" } },
      { selector: "node[status='refused']", style: { "background-color": "#ef4444" } },
      { selector: "node[status='pending']", style: { "background-color": "#f59e0b" } },
      { selector: "edge", style: { "width": 1, "line-color": "#2a3954", "curve-style": "haystack", "opacity": 0.7 } },
      { selector: "edge[relation='flagged']", style: { "line-color": "#ef4444", "width": 1.6 } },
      { selector: ".faded", style: { "opacity": 0.08 } },
      { selector: ".hl", style: { "opacity": 1, "border-width": 2, "border-color": "#fff" } },
      { selector: "edge.hl", style: { "line-color": "#e2e8f0", "width": 2 } },
    ] });
    const hidden = new Set();
    const info = wrap.querySelector(".kg-info");

    async function load() {
      const q = getQuery ? getQuery() : "";
      const g = await UI.get("/api/graph/knowledge" + (q ? "?" + q : ""));
      if (!g.nodes) return;
      cy.elements().remove();
      cy.add(g.nodes.map(n => ({ data: { ...n, ...KG_STYLE[n.type] } })));
      cy.add(g.edges.map((e, i) => ({ data: { id: `e${i}`, ...e } })));
      applyHidden();
      cy.layout({ name: "cose", animate: false, nodeRepulsion: 12000, idealEdgeLength: 70, gravity: 0.5, numIter: 1000, padding: 24 }).run();
      wrap.querySelector(".kg-count").textContent = `${g.nodes.length} nodes · ${g.edges.length} relations`;
    }
    function applyHidden() { cy.nodes().forEach(n => n.style("display", hidden.has(n.data("type")) ? "none" : "element")); }
    wrap.querySelectorAll(".kg-tools .pill").forEach(p => p.onclick = () => {
      const t = p.dataset.t; hidden.has(t) ? hidden.delete(t) : hidden.add(t); p.classList.toggle("off"); applyHidden();
    });
    wrap.querySelector(".kg-reload").onclick = load;
    wrap.querySelector(".kg-search").addEventListener("input", (e) => {
      const v = e.target.value.toLowerCase(); cy.elements().removeClass("faded hl");
      if (!v) return;
      const m = cy.nodes().filter(n => (n.data("label") || "").toLowerCase().includes(v) || n.id().toLowerCase().includes(v));
      if (m.nonempty()) { cy.elements().addClass("faded"); m.closedNeighborhood().removeClass("faded").addClass("hl"); }
    });
    cy.on("tap", "node", (e) => {
      const n = e.target, nb = n.closedNeighborhood();
      cy.elements().addClass("faded").removeClass("hl"); nb.removeClass("faded").addClass("hl");
      const rel = {}; n.connectedEdges().forEach(ed => { rel[ed.data("relation")] = (rel[ed.data("relation")] || 0) + 1; });
      const d = n.data();
      info.style.display = "block";
      info.innerHTML = `<b style="color:${d.color}">${UI.esc(d.type)}</b>: ${UI.esc(d.label)}<br>
        ${d.segment ? `segment: ${UI.esc(d.segment)}<br>` : ""}${d.status ? `status: <span class="status-${d.status}">${UI.esc(d.status)}</span><br>` : ""}
        ${d.severity ? `severity: ${UI.esc(d.severity)}<br>` : ""}
        <div style="margin-top:6px">${Object.entries(rel).map(([k, v]) => `<span class="pill">${UI.esc(k)}: ${v}</span>`).join("")}</div>
        <div class="muted" style="margin-top:6px">${n.degree()} connections. Click empty space to reset.</div>`;
    });
    cy.on("tap", (e) => { if (e.target === cy) { cy.elements().removeClass("faded hl"); info.style.display = "none"; } });
    const reload = UI.debounce(load, 4000);
    ["interaction.ended", "payment.status", "security.alert", "gate.rejected"].forEach(t => Bus.on(t, reload));
    load();
    return { cy, load };
  }

  window.AgentGraph = { mount: mountAgentGraph };
  window.KnowledgeGraph = { mount: mountKnowledgeGraph };
})();
