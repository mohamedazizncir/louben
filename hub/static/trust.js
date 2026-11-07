// Trust panels: alerts, gate queue (human key), immunity score, red team log, rules (vaccines), audit trail.
// PHASE 0 VERSION written by A, owned by B after CP0. Panels mount on the ids listed in PLAN.md Section 10.
(function () {
  let token = null;

  function pinModal() {
    return new Promise((resolve) => {
      const bg = document.createElement("div");
      bg.className = "modal-bg open";
      bg.innerHTML = `<div class="modal small"><header><b>Human key: operator login</b></header><div class="content">
        <div class="muted">Risky actions need a human signature. Enter the operator PIN.</div>
        <input type="password" class="pin" placeholder="PIN" autofocus />
        <div style="display:flex;gap:8px;justify-content:flex-end"><button class="cancel">Cancel</button><button class="primary go">Sign in</button></div>
        <div class="err" style="color:#fca5a5;font-size:12px"></div></div></div>`;
      document.body.appendChild(bg);
      const pin = bg.querySelector(".pin"); setTimeout(() => pin.focus(), 50);
      const done = (v) => { bg.remove(); resolve(v); };
      bg.querySelector(".cancel").onclick = () => done(null);
      const go = async () => {
        const r = await UI.post("/api/login", { pin: pin.value });
        if (r.token) { token = r.token; done(token); } else bg.querySelector(".err").textContent = r.error || "Login failed";
      };
      bg.querySelector(".go").onclick = go;
      pin.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
    });
  }
  async function getToken() { return token || await pinModal(); }

  // ---------------------------------------------------------------- immunity score
  function mountImmunity(el) {
    el.innerHTML = `<div class="immunity"><div class="gauge" style="--v:0"><div class="val">-</div></div>
      <div style="flex:1"><div style="font-weight:700;font-size:15px">Immunity score</div>
      <div class="muted sum" style="font-size:12px;margin:3px 0 8px">Red Team attacks blocked / total</div>
      <button class="primary small run">Launch Red Team attack</button></div></div>`;
    const g = el.querySelector(".gauge"), val = el.querySelector(".val"), sum = el.querySelector(".sum");
    const set = (s, b, t) => { g.style.background = `conic-gradient(${s >= 90 ? "#22c55e" : s >= 70 ? "#f59e0b" : "#ef4444"} ${s}%, #1f2a3c 0)`; val.textContent = s + "%"; if (t) sum.textContent = `${b} of ${t} attacks blocked`; };
    el.querySelector(".run").onclick = async (e) => {
      e.target.disabled = true; e.target.textContent = "Attacking...";
      await UI.post("/api/redteam/run", { attacks: "all" });
      e.target.disabled = false; e.target.textContent = "Launch Red Team attack";
    };
    Bus.on("redteam.score", (ev) => set(ev.data.immunity_score, ev.data.blocked, ev.data.total));
    UI.get("/api/redteam/score").then(r => { if (r.immunity_score !== null && r.immunity_score !== undefined) set(r.immunity_score, r.results.filter(x => x.blocked).length, r.results.length); });
  }

  function mountRedteamLog(el) {
    el.classList.add("list");
    el.innerHTML = `<div class="empty">No attack yet.</div>`;
    Bus.on("redteam.attack", (ev) => {
      const d = ev.data; if (el.querySelector(".empty")) el.innerHTML = "";
      const it = document.createElement("div"); it.className = `item ${d.blocked ? "sev-low" : "sev-critical"}`;
      it.innerHTML = `<div class="top"><b>${UI.esc(d.name)}</b><span class="pill ${d.blocked ? "ok" : "bad"}">${d.blocked ? "blocked" : "PASSED"}</span></div>
        <div class="muted" style="font-size:12px">${UI.esc(d.category)} → ${UI.esc(d.target)} · ${UI.esc(d.blocked_by || "vaccine proposed")}</div>`;
      el.prepend(it); while (el.children.length > 30) el.lastChild.remove();
    });
  }

  // ---------------------------------------------------------------- alerts
  function alertItem(ev) {
    const d = ev.data || {};
    const it = document.createElement("div");
    it.className = `item sev-${d.severity || "medium"}`;
    const det = d.details ? (d.details.reason || d.details.excerpt || (d.details.reasons || []).join("; ") || "") : "";
    it.innerHTML = `<div class="top"><b>${UI.esc(d.type)}</b><span class="pill warn">${UI.esc(d.severity || "")}</span><span class="muted" style="font-size:11px">${UI.time(ev.ts)}</span></div>
      <div class="muted" style="font-size:12px;margin-top:3px">${UI.esc(ev.source)}${d.target ? " → " + UI.esc(d.target) : ""} ${UI.esc(String(det).slice(0, 120))}</div>`;
    return it;
  }
  function mountAlerts(el) {
    el.classList.add("list");
    UI.get("/api/events?type=security.alert&limit=15").then(r => {
      el.innerHTML = ""; (r.items || []).forEach(ev => el.prepend(alertItem(ev)));
      if (!el.children.length) el.innerHTML = `<div class="empty">No alert. Everything is calm.</div>`;
    });
    Bus.on("security.alert", (ev) => { const e = el.querySelector(".empty"); if (e) e.remove(); el.prepend(alertItem(ev)); while (el.children.length > 40) el.lastChild.remove(); });
  }

  // ---------------------------------------------------------------- gate queue
  function mountGate(el) {
    el.classList.add("list");
    const draw = async () => {
      const r = await UI.get("/api/gate/pending");
      const items = r.items || [];
      el.innerHTML = items.map(p => `<div class="item sev-medium"><div class="top"><b>${UI.money(p.intent.amount)} · ${UI.esc(p.intent.product_id)}</b></div>
        <div class="muted" style="font-size:12px;margin:3px 0 6px">${UI.esc(p.reason)}</div>
        <div>${p.signatures.map(s => `<span class="pill ${s.decision === "approve" ? "ok" : "bad"}">🔑 ${s.signer}</span>`).join("")}<span class="pill warn">👤 human</span></div>
        <div style="display:flex;gap:8px;margin-top:8px"><button class="small ok" data-a="approve" data-id="${p.intent.intent_id}">Approve with human key</button>
        <button class="small danger" data-a="reject" data-id="${p.intent.intent_id}">Reject</button></div></div>`).join("")
        || `<div class="empty">No payment waiting for a human key.</div>`;
      el.querySelectorAll("[data-a]").forEach(b => b.onclick = async () => {
        const t = await getToken(); if (!t) return;
        const res = await UI.post("/api/gate/decision", { intent_id: b.dataset.id, decision: b.dataset.a, token: t });
        if (res.error) UI.toast("Refused: " + UI.esc(res.error)); else UI.toast(`Gate: <b>${res.status}</b> ${res.payment_status ? "· payment " + res.payment_status : ""}`);
        draw();
      });
    };
    ["gate.pending_human", "gate.approved", "gate.rejected"].forEach(t => Bus.on(t, UI.debounce(draw, 300)));
    draw();
  }

  // ---------------------------------------------------------------- rules (vaccines)
  function mountRules(el) {
    el.classList.add("list");
    const draw = async () => {
      const r = await UI.get("/api/rules");
      const items = (r.items || []).slice().reverse();
      el.innerHTML = items.map(x => `<div class="item"><div class="top"><b>${UI.esc(x.description)}</b>
        ${x.status === "proposed" ? `<button class="small ok" data-id="${x.rule_id}" data-a="approve">Approve vaccine</button><button class="small danger" data-id="${x.rule_id}" data-a="reject">Reject</button>`
          : `<span class="pill ${x.status === "approved" ? "ok" : "bad"}">${x.status}</span>`}</div>
        <div class="muted" style="font-size:11.5px;font-family:monospace;margin-top:4px">${UI.esc(x.pattern)}</div></div>`).join("")
        || `<div class="empty">No vaccine proposed yet.</div>`;
      el.querySelectorAll("[data-a]").forEach(b => b.onclick = async () => {
        const t = await getToken(); if (!t) return;
        await UI.post("/api/rules/decision", { rule_id: b.dataset.id, decision: b.dataset.a, token: t }); draw();
      });
    };
    ["rule.proposed", "rule.approved"].forEach(t => Bus.on(t, UI.debounce(draw, 300)));
    draw();
  }

  // ---------------------------------------------------------------- audit trail
  function mountAudit(el) {
    el.innerHTML = `<div style="display:flex;gap:8px;align-items:center;margin-bottom:8px"><button class="small verify">Verify hash chain</button>
      <select class="atype"><option value="">All events</option><option value="security.*">security</option><option value="gate.*">gate</option><option value="payment.*">payment</option><option value="a2a.call">a2a.call</option><option value="redteam.*">redteam</option></select>
      <span class="res muted" style="font-size:12px"></span></div><div class="feed rows"></div>`;
    const rows = el.querySelector(".rows");
    const draw = async () => {
      const t = el.querySelector(".atype").value;
      const r = await UI.get(`/api/audit?limit=60${t ? "&type=" + encodeURIComponent(t) : ""}`);
      rows.innerHTML = (r.items || []).map(e => `<div class="row"><span class="t">#${e.seq}</span><span class="src" style="color:${UI.colors[e.source] || "#94a3b8"}">${UI.esc(e.source)}</span>
        <span class="txt">${UI.esc(e.type)} · <span class="muted">${UI.esc(e.hash.slice(0, 12))}…</span> ${UI.esc(Business ? Business.describe(e).slice(0, 80) : "")}</span></div>`).join("");
    };
    el.querySelector(".atype").onchange = draw;
    el.querySelector(".verify").onclick = async () => {
      const v = await UI.get("/api/audit/verify");
      el.querySelector(".res").innerHTML = v.ok ? `<span class="status-succeeded">Chain intact: ${v.checked} events verified</span>` : `<span class="status-refused">Chain BROKEN at #${v.broken_at}</span>`;
    };
    draw(); Bus.on("security.alert", UI.debounce(draw, 1500));
  }

  function mountAll() {
    const m = (id, fn) => { const el = document.getElementById(id); if (el) fn(el); };
    m("immunity-score", mountImmunity); m("redteam-log", mountRedteamLog); m("security-alerts", mountAlerts);
    m("gate-queue", mountGate); m("rules-queue", mountRules); m("audit-trail", mountAudit);
  }

  window.Trust = { mountAll, getToken };
})();
