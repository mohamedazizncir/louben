// Customer chat (voice + text). Owner: A.  Usage: ChatWidget.mount(element, { lang: "fr" })
(function () {
  const MIC = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>';
  const STOP = '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="7" y="7" width="10" height="10" rx="2"/></svg>';
  const rid = (p) => p + Math.random().toString(16).slice(2, 10);

  function mount(root, opts = {}) {
    const st = { lang: opts.lang || "fr", session: rid("s-"), customer: rid("cust-"), token: "tok_visa", busy: false, lastOffer: null };
    root.innerHTML = `
      <div class="chat">
        <div class="subbar">
          <span class="seg lang"><button data-l="fr">FR</button><button data-l="en">EN</button></span>
          <span class="seg card" title="Sandbox test card"><button data-t="tok_visa">Visa test</button><button data-t="tok_declined">Declined</button><button data-t="tok_pending">Pending</button></span>
          <span class="spacer"></span>
          <button class="small mute" title="Voice output">Sound on</button>
          <button class="small reset" title="End and analyze this conversation">New chat</button>
        </div>
        <div class="msgs"></div>
        <div class="interim"></div>
        <div class="controls">
          <button class="mic" title="Push to talk">${MIC}</button>
          <input class="text" placeholder="${Voice.canListen ? "Speak or type your message..." : "Type your message (voice not supported in this browser)"}" />
          <button class="primary send">Send</button>
        </div>
      </div>`;
    const $ = (s) => root.querySelector(s);
    const msgs = $(".msgs"), input = $(".text"), mic = $(".mic"), interim = $(".interim");

    function setSeg() {
      root.querySelectorAll(".lang button").forEach(b => b.classList.toggle("on", b.dataset.l === st.lang));
      root.querySelectorAll(".card button").forEach(b => b.classList.toggle("on", b.dataset.t === st.token));
    }
    setSeg();
    root.querySelectorAll(".lang button").forEach(b => b.onclick = () => { st.lang = b.dataset.l; setSeg(); });
    root.querySelectorAll(".card button").forEach(b => b.onclick = () => { st.token = b.dataset.t; setSeg(); });
    $(".mute").onclick = () => { Voice.muted = !Voice.muted; Voice.shutUp(); $(".mute").textContent = Voice.muted ? "Sound off" : "Sound on"; };
    $(".reset").onclick = () => endSession(true);

    function bubble(role, text, meta, cls = "") {
      const d = document.createElement("div");
      d.className = `bubble ${role} ${cls}`;
      d.innerHTML = UI.esc(text) + (meta ? `<span class="meta">${meta}</span>` : "");
      msgs.appendChild(d); msgs.scrollTop = msgs.scrollHeight;
      return d;
    }

    function offerCard(o) {
      const key = JSON.stringify(o);
      if (!o || key === st.lastOffer) return;
      st.lastOffer = key;
      const d = document.createElement("div");
      d.className = "offer-card";
      const each = o.installments > 1 ? ` · ${o.installments} x ${UI.money(o.final_price / o.installments)}` : "";
      d.innerHTML = `<div><div class="muted">Validated offer</div><b>${UI.money(o.final_price)}</b>${o.discount_pct ? ` <s>${UI.money(o.list_price)}</s>` : ""}</div>
        <div class="muted">${o.discount_pct ? `-${o.discount_pct}%` : "list price"}${each}<br><span class="pill ok">guardrail checked</span></div>`;
      msgs.appendChild(d); msgs.scrollTop = msgs.scrollHeight;
    }

    function greet() {
      msgs.innerHTML = "";
      st.lastOffer = null;
      const hi = st.lang === "fr"
        ? "Bonjour ! Appuyez sur le micro et parlez-moi de votre objectif (IA, data, web, PFE, stage)."
        : "Hello! Press the mic and tell me about your goal (AI, data, web, final year project, internship).";
      bubble("agent", hi, "Sales Agent");
    }

    async function send(text, channel) {
      text = (text || "").trim();
      if (!text || st.busy) return;
      st.busy = true; input.value = ""; interim.textContent = "";
      bubble("customer", text, channel === "voice" ? "voice" : "text");
      const typing = bubble("agent", "...", "");
      const t0 = performance.now();
      const r = await UI.post("/api/chat", { session_id: st.session, customer_id: st.customer, text, channel, payment_token: st.token });
      typing.remove();
      st.busy = false;
      if (r.error) { bubble("agent", st.lang === "fr" ? "Service momentanément indisponible." : "Service temporarily unavailable.", UI.esc(r.error), "blocked"); return; }
      if (r.lang) { st.lang = r.lang; setSeg(); }
      const ms = Math.round(performance.now() - t0);
      const intent = r.intent || {};
      let meta = `Sales Agent · ${r.stage} · ${ms} ms`;
      if (r.stage === "blocked") meta += " · blocked by Security Agent";
      if (intent.status) meta += ` · payment: ${intent.status}${intent.payment_status ? " / " + intent.payment_status : ""}`;
      bubble("agent", r.reply, meta, r.stage === "blocked" ? "blocked" : "");
      if (r.offer && r.stage !== "payment") offerCard(r.offer);
      Voice.speak(r.reply, st.lang);
    }

    async function endSession(restart) {
      const sid = st.session;
      st.session = rid("s-"); st.customer = rid("cust-");
      if (restart) greet();
      const r = await UI.post("/api/chat/end", { session_id: sid });
      if (r && r.intel) UI.toast(`Intel Agent: objections <b>${(r.intel.objections || []).join(", ") || "none"}</b>, sentiment ${r.intel.sentiment}, segment ${r.intel.segment}`);
    }

    function toggleMic() {
      if (!Voice.canListen) { UI.toast("Voice input needs Chrome or Edge. Use the text box."); return; }
      if (Voice.listening) { Voice.stop(); return; }
      mic.classList.add("listening"); mic.innerHTML = STOP;
      interim.textContent = st.lang === "fr" ? "Je vous écoute..." : "Listening...";
      Voice.listen(st.lang, (t) => { interim.textContent = t; }, (t) => send(t, "voice"),
        () => { mic.classList.remove("listening"); mic.innerHTML = MIC; if (!st.busy) interim.textContent = ""; });
    }

    mic.onclick = toggleMic;
    $(".send").onclick = () => send(input.value, "text");
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") send(input.value, "text"); });
    document.addEventListener("keydown", (e) => {
      if (e.code === "Space" && e.ctrlKey) { e.preventDefault(); toggleMic(); }   // Ctrl+Space = push to talk
    });
    window.addEventListener("beforeunload", () => {
      navigator.sendBeacon && navigator.sendBeacon("/api/chat/end", new Blob([JSON.stringify({ session_id: st.session })], { type: "application/json" }));
    });
    greet();
    return { send, endSession, state: st };
  }

  window.ChatWidget = { mount };
})();
