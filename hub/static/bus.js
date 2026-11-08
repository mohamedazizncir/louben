// Live event bus (Server Sent Events from the hub). Owner: A.
// Usage: Bus.on("payment.status", ev => ...); Bus.on("security.*", ...); Bus.on("*", ...)
(function () {
  const handlers = [];
  const shownHandlers = [];      // fired when the agent graph has played the event (or at once if no graph)
  const history = [];
  let player = false;
  const match = (p, ev) => p === "*" || ev.type === p || (p.endsWith("*") && ev.type.startsWith(p.slice(0, -1)));
  const dispatch = (list, ev) => {
    for (const h of list) if (match(h.p, ev)) { try { h.fn(ev); } catch (e) { console.error("[bus]", h.p, e); } }
  };
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
      dispatch(handlers, ev);
      if (!player) dispatch(shownHandlers, ev);
    };
  }

  window.Bus = {
    on(pattern, fn) { handlers.push({ p: pattern, fn }); },
    onShown(pattern, fn) { shownHandlers.push({ p: pattern, fn }); },
    setPlayer() { player = true; },
    shown(ev) { dispatch(shownHandlers, ev); },
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
      customer: "#2563eb", sales: "#0891b2", intel: "#7c3aed", payment: "#d97706", analyst: "#059669",
      strategy: "#db2777", security: "#dc2626", redteam: "#e11d48", gate: "#ca8a04", hub: "#64748b", operator: "#334155",
    },
    // stroke icons (24x24, lucide style): UI.icon("home")
    icon(name, cls = "ico") {
      const P = {
        home: '<path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"/>',
        chart: '<path d="M3 3v18h18"/><path d="m7 15 4-4 3 3 5-6"/>',
        users: '<circle cx="9" cy="8" r="4"/><path d="M2 21a7 7 0 0 1 14 0"/><path d="M17 4a4 4 0 0 1 0 8M22 21a7 7 0 0 0-4-6.3"/>',
        card: '<rect x="2" y="5" width="20" height="14" rx="3"/><path d="M2 10h20M6 15h4"/>',
        shield: '<path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6z"/><path d="m9 12 2 2 4-4"/>',
        graph: '<circle cx="6" cy="6" r="3"/><circle cx="18" cy="8" r="3"/><circle cx="9" cy="18" r="3"/><path d="m8.6 7.4 6.6.4M7 8.8l1.4 6.4M16.3 10.4l-5.4 5.6"/>',
        bot: '<rect x="4" y="8" width="16" height="12" rx="3"/><path d="M12 4v4M9 13v2M15 13v2M2 13v2M22 13v2"/>',
        mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
        wallet: '<path d="M19 7V5a2 2 0 0 0-2-2H5a2 2 0 0 0 0 4h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5"/><circle cx="16.5" cy="14" r="1.5"/>',
        trend: '<path d="m3 17 6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
        chat: '<path d="M21 12a8 8 0 0 1-11.6 7.1L3 21l1.9-6.4A8 8 0 1 1 21 12z"/>',
        heart: '<path d="M12 20s-7-4.4-9.2-9A5 5 0 0 1 12 6a5 5 0 0 1 9.2 5c-2.2 4.6-9.2 9-9.2 9z"/>',
        check: '<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',
        x: '<circle cx="12" cy="12" r="9"/><path d="m15 9-6 6M9 9l6 6"/>',
        clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
        alert: '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>',
        spark: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M5.6 18.4l2.8-2.8M15.6 8.4l2.8-2.8"/>',
        globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
        play: '<circle cx="12" cy="12" r="9"/><path d="m10 8 6 4-6 4z"/>',
        arrow: '<path d="M7 17 17 7M8 7h9v9"/>',
        lock: '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
      };
      return `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${P[name] || ""}</svg>`;
    },
  };
})();
