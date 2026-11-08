// Trust panels: alerts, gate queue (live multisig keys + human key), immunity score,
// red team log, rules (vaccines), audit trail. Owner: B (first version by A).
// Panels mount on the ids listed in PLAN.md Section 10. The human token lives in memory only.
(function () {
  let token = null;
  const KEYS = ["payment", "security", "analyst", "human"];
  // visual updates follow the agent graph replay (A's Bus.onShown); data refreshes use Bus.on
  const shown = (t, fn) => (Bus.onShown || Bus.on).call(Bus, t, fn);

  function pinModal() {
    return new Promise((resolve) => {
      const bg = document.createElement("div");
      bg.className = "modal-bg open";
      bg.innerHTML = `<div class="modal small"><header><b>Human key: operator login</b></header><div class="content">
        <div class="muted">Risky actions need a human signature. Enter the operator PIN.</div>
        <input type="password" class="pin" placeholder="PIN" autocomplete="off" />
        <div style="display:flex;gap:8px;justify-content:flex-end"><button class="cancel">Cancel</button><button class="primary go">Sign in</button></div>
        <div class="err" style="color:#fca5a5;font-size:12px"></div></div></div>`;
      document.body.appendChild(bg);
      const pin = bg.querySelector(".pin"); setTimeout(() => pin.focus(), 50);
      const done = (v) => { bg.remove(); resolve(v); };
      bg.querySelector(".cancel").onclick = () => done(null);
      const go = async () => {
        const r = await UI.post("/api/login", { pin: pin.value });
        if (r.token) { token = r.token; setTimeout(() => { token = null; }, (r.expires_in || 1800) * 1000); done(token); }
        else bg.querySelector(".err").textContent = r.error || "Login failed";
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
    const set = (s, b, t) => {
      g.style.background = `conic-gradient(${s >= 90 ? "#22c55e" : s >= 70 ? "#f59e0b" : "#ef4444"} ${s}%, #1f2a3c 0)`;
      val.textContent = s + "%"; if (t) sum.textContent = `${b} of ${t} attacks blocked`;
    };
    el.querySelector(".run").onclick = async (e) => {
      e.target.disabled = true; e.target.textContent = "Attacking...";
      await UI.post("/api/redteam/run", { attacks: "all" });
      e.target.disabled = false; e.target.textContent = "Launch Red Team attack";
    };
    shown("redteam.score", (ev) => set(ev.data.immunity_score, ev.data.blocked, ev.data.total));
    UI.get("/api/redteam/score").then(r => {
      if (r.immunity_score === null || r.immunity_score === undefined) return;
      set(r.immunity_score, r.blocked ?? (r.results || []).filter(x => x.blocked).length, r.total ?? (r.results || []).length);
      if (r.from_history) sum.textContent += " (last campaign)";
    });
  }

  function mountRedteamLog(el) {
    el.classList.add("list");
    el.innerHTML = `<div class="empty">No attack yet.</div>`;
    shown("redteam.attack", (ev) => {
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
    it.className = `item sev-${UI.esc(d.severity || "medium")}`;
    const det = d.details ? (d.details.reason || d.details.excerpt || (d.details.reasons || []).join("; ") || "") : "";
    it.innerHTML = `<div class="top"><b>${UI.esc(d.type)}</b><span class="pill warn">${UI.esc(d.severity || "")}</span><span class="muted" style="font-size:11px">${UI.time(ev.ts)}</span></div>
      <div class="muted" style="font-size:12px;margin-top:3px">${UI.esc(ev.source)}${d.target ? " → " + UI.esc(d.target) : ""} ${UI.esc(String(det).slice(0, 120))}</div>`;
    return it;
  }
  function mountAlerts(el) {
    el.classList.add("list");
    // history from the audit log (survives restarts), newest first
    UI.get("/api/audit?type=security.alert&limit=15").then(r => {
      el.innerHTML = ""; (r.items || []).slice().reverse().forEach(ev => el.prepend(alertItem(ev)));
      if (!el.children.length) el.innerHTML = `<div class="empty">No alert. Everything is calm.</div>`;
    });
    shown("security.alert", (ev) => {
      const e = el.querySelector(".empty"); if (e) e.remove();
      const it = alertItem(ev); it.classList.add("flash"); el.prepend(it);
      while (el.children.length > 40) el.lastChild.remove();
    });
  }

  // ---------------------------------------------------------------- gate: live keys + human queue
  const keyPill = (signer, state) => {
    const cls = state === "approve" ? "ok" : state === "refuse" ? "bad" : state === "wait" ? "warn" : "";
    const icon = signer === "human" ? "👤" : "🔑";
    return `<span class="pill ${cls}" style="${cls ? "" : "opacity:.35"}" title="${UI.esc(signer)}">${icon} ${UI.esc(signer)}</span>`;
  };

  function mountGate(el) {
    el.classList.add("list");
    // actionable (needs human) first, so the Approve button is visible without scrolling on stage
    el.innerHTML = `<div class="pending"></div><div class="live-sign"></div>`;
    const live = el.querySelector(".live-sign"), pend = el.querySelector(".pending");
    const signing = new Map(); // intent_id -> {keys, status, amount}
    let pendingIds = new Set();

    const drawLive = () => {
      const rows = [...signing.entries()].filter(([id]) => !pendingIds.has(id)).slice(-3).reverse();
      live.innerHTML = rows.map(([id, s]) => `<div class="item ${s.status === "rejected" ? "sev-critical" : s.status === "executed" ? "sev-low" : "sev-medium"}">
        <div class="top"><b>Multisig ${s.amount ? "· " + UI.money(s.amount) : ""}</b><span class="pill ${s.status === "executed" ? "ok" : s.status === "rejected" ? "bad" : "warn"}">${UI.esc(s.status)}</span></div>
        <div>${KEYS.map(k => keyPill(k, s.keys[k])).join("")}</div>
        <div class="muted" style="font-size:11px">${UI.esc(id)}</div></div>`).join("");
    };
    const touch = (id) => { if (!signing.has(id)) signing.set(id, { keys: {}, status: "signing", amount: null }); if (signing.size > 6) signing.delete(signing.keys().next().value); return signing.get(id); };

    shown("payment.intent_created", (ev) => { const s = touch(ev.data.intent_id); s.amount = ev.data.amount; drawLive(); });
    shown("gate.signature", (ev) => { const s = touch(ev.data.intent_id); s.keys[ev.data.signer] = ev.data.decision; drawLive(); });
    shown("gate.pending_human", (ev) => { const s = touch(ev.data.intent_id); s.keys.human = "wait"; s.status = "waiting human"; s.amount = ev.data.amount; drawLive(); });
    shown("gate.approved", (ev) => { const s = touch(ev.data.intent_id); s.status = "executed"; s.amount = ev.data.amount; drawLive(); });
    shown("gate.rejected", (ev) => { const s = touch(ev.data.intent_id); s.status = "rejected"; s.amount = ev.data.amount; drawLive(); });

    const draw = async () => {
      const r = await UI.get("/api/gate/pending");
      const items = r.items || [];
      pendingIds = new Set(items.map(p => p.intent.intent_id)); drawLive();
      pend.innerHTML = items.map(p => `<div class="item sev-medium"><div class="top"><b>${UI.money(p.intent.amount)} · ${UI.esc(p.intent.product_id)}</b><span class="pill warn">needs human key</span></div>
        <div class="muted" style="font-size:12px;margin:3px 0 6px">${UI.esc(p.reason)}</div>
        <div>${p.signatures.map(s => keyPill(s.signer, s.decision)).join("")}${keyPill("human", "wait")}</div>
        <div style="display:flex;gap:8px;margin-top:8px"><button class="small ok" data-a="approve" data-id="${UI.esc(p.intent.intent_id)}">Approve with human key</button>
        <button class="small danger" data-a="reject" data-id="${UI.esc(p.intent.intent_id)}">Reject</button></div></div>`).join("")
        || (signing.size ? "" : `<div class="empty">No payment waiting for a human key.</div>`);
      pend.querySelectorAll("[data-a]").forEach(b => b.onclick = async () => {
        const t = await getToken(); if (!t) return;
        b.disabled = true;
        const res = await UI.post("/api/gate/decision", { intent_id: b.dataset.id, decision: b.dataset.a, token: t });
        if (res._status === 401) token = null;
        if (res.error) UI.toast("Refused: " + UI.esc(res.error));
        else UI.toast(`Gate: <b>${UI.esc(res.status)}</b> ${res.payment_status ? "· payment " + UI.esc(res.payment_status) : ""}`);
        draw();
      });
    };
    ["gate.pending_human", "gate.approved", "gate.rejected"].forEach(t => shown(t, UI.debounce(draw, 300)));
    draw();
  }

  // ---------------------------------------------------------------- rules (vaccines)
  function mountRules(el) {
    el.classList.add("list");
    const draw = async () => {
      const r = await UI.get("/api/rules");
      const items = (r.items || []).slice().reverse();
      el.innerHTML = items.map(x => `<div class="item"><div class="top"><b>${UI.esc(x.description)}</b>
        ${x.status === "proposed" ? `<button class="small ok" data-id="${UI.esc(x.rule_id)}" data-a="approve">Approve vaccine</button><button class="small danger" data-id="${UI.esc(x.rule_id)}" data-a="reject">Reject</button>`
          : `<span class="pill ${x.status === "approved" ? "ok" : "bad"}">${UI.esc(x.status)}</span>`}</div>
        <div class="muted" style="font-size:11.5px;font-family:monospace;margin-top:4px">${UI.esc(x.pattern)}</div></div>`).join("")
        || `<div class="empty">No vaccine proposed yet.</div>`;
      el.querySelectorAll("[data-a]").forEach(b => b.onclick = async () => {
        const t = await getToken(); if (!t) return;
        const res = await UI.post("/api/rules/decision", { rule_id: b.dataset.id, decision: b.dataset.a, token: t });
        if (res._status === 401) { token = null; UI.toast("Human login expired"); }
        else if (res.status === "approved") UI.toast("Vaccine approved: Security applies it now");
        draw();
      });
    };
    shown("rule.proposed", () => UI.toast("Red Team found a gap: <b>vaccine proposed</b>, waiting for a human"));
    ["rule.proposed", "rule.approved"].forEach(t => Bus.on(t, UI.debounce(draw, 300)));
    draw();
  }

  // ---------------------------------------------------------------- audit trail
  function mountAudit(el) {
    el.innerHTML = `<div style="display:flex;gap:8px;align-items:center;margin-bottom:8px;flex-wrap:wrap"><button class="small verify">Verify hash chain</button>
      <select class="atype"><option value="">All events</option><option value="security.*">security</option><option value="gate.*">gate</option><option value="payment.*">payment</option><option value="a2a.call">a2a.call</option><option value="redteam.*">redteam</option><option value="rule.*">rules</option></select>
      <input class="q" placeholder="search (customer, intent, type...)" style="flex:1;min-width:140px" />
      <span class="res muted" style="font-size:12px"></span></div><div class="feed rows"></div>`;
    const rows = el.querySelector(".rows"), q = el.querySelector(".q");
    let items = [];
    const render = () => {
      const needle = q.value.trim().toLowerCase();
      const shown = needle ? items.filter(e => JSON.stringify(e).toLowerCase().includes(needle)) : items;
      const describe = (e) => (window.Business && Business.describe ? Business.describe(e) : JSON.stringify(e.data || {})).slice(0, 80);
      rows.innerHTML = shown.map(e => `<div class="row"><span class="t">#${e.seq}</span><span class="src" style="color:${UI.colors[e.source] || "#94a3b8"}">${UI.esc(e.source)}</span>
        <span class="txt">${UI.esc(e.type)} · <span class="muted">${UI.esc(String(e.hash).slice(0, 12))}…</span> ${UI.esc(describe(e))}</span></div>`).join("")
        || `<div class="empty">No matching event.</div>`;
    };
    const draw = async () => {
      const t = el.querySelector(".atype").value;
      const r = await UI.get(`/api/audit?limit=200${t ? "&type=" + encodeURIComponent(t) : ""}`);
      items = r.items || []; render();
    };
    el.querySelector(".atype").onchange = draw;
    q.oninput = UI.debounce(render, 150);
    el.querySelector(".verify").onclick = async () => {
      const v = await UI.get("/api/audit/verify");
      el.querySelector(".res").innerHTML = v.ok ? `<span class="status-succeeded">Chain intact: ${v.checked} events verified</span>`
        : `<span class="status-refused">Chain BROKEN at #${UI.esc(v.broken_at)}</span>`;
    };
    draw(); ["security.alert", "gate.*", "payment.status"].forEach(t => Bus.on(t, UI.debounce(draw, 1500)));
  }

  function mountAll() {
    const m = (id, fn) => { const el = document.getElementById(id); if (el) fn(el); };
    m("immunity-score", mountImmunity); m("redteam-log", mountRedteamLog); m("security-alerts", mountAlerts);
    m("gate-queue", mountGate); m("rules-queue", mountRules); m("audit-trail", mountAudit);
  }

  window.Trust = { mountAll, getToken };
})();
