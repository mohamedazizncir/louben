// Live event bus (Server Sent Events from the hub). Owner: A.
// Usage: Bus.on("payment.status", ev => ...); Bus.on("security.*", ...); Bus.on("*", ...)
(function () {
  const handlers = [];
  const history = [];
  let es = null;

  function connect() {
    es = new EventSource("/stream");
    es.onopen = () => document.querySelectorAll(".live").forEach(el => el.classList.add("on"));
    es.onerror = () => document.querySelectorAll(".live").forEach(el => el.classList.remove("on"));
    es.onmessage = (m) => {
      let ev;
      try { ev = JSON.parse(m.data); } catch (e) { return; }
      history.push(ev);
      if (history.length > 1500) history.shift();
      for (const h of handlers) {
        if (h.p === "*" || ev.type === h.p || (h.p.endsWith("*") && ev.type.startsWith(h.p.slice(0, -1)))) {
          try { h.fn(ev); } catch (e) { console.error("[bus]", h.p, e); }
        }
      }
    };
  }

  window.Bus = {
    on(pattern, fn) { handlers.push({ p: pattern, fn }); },
    history() { return history.slice(); },
    start() { if (!es) connect(); },
  };

  // tiny helpers shared by all UI files
  window.UI = {
    esc(s) { return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); },
    money(v) { return (Math.round((v || 0) * 100) / 100).toLocaleString("fr-FR") + " TND"; },
    pct(v) { return ((v || 0) * 100).toFixed(1) + "%"; },
    time(ts) { try { return new Date(ts).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", second: "2-digit" }); } catch (e) { return ""; } },
    async get(url) { const r = await fetch(url); return r.json(); },
    async post(url, body) {
      const r = await fetch(url, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body || {}) });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) j._status = r.status;
      return j;
    },
    toast(msg, ms = 3500) {
      const t = document.createElement("div"); t.className = "toast"; t.innerHTML = msg;
      document.body.appendChild(t); setTimeout(() => t.remove(), ms);
    },
    debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; },
    colors: {
      customer: "#60a5fa", sales: "#22d3ee", intel: "#a78bfa", payment: "#f59e0b", analyst: "#34d399",
      strategy: "#f472b6", security: "#ef4444", redteam: "#fb7185", gate: "#fbbf24", hub: "#94a3b8", operator: "#e2e8f0",
    },
  };
})();
