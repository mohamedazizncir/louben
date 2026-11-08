// Embeddable advisor widget. One line to install on any website:
//   <script src="http://127.0.0.1:8000/static/widget.js" data-org="9antra" data-lang="fr"></script>
// Owner: A.
(function () {
  const me = document.currentScript;
  const base = new URL(me.src).origin;
  const lang = me.dataset.lang || "fr";
  const color = me.dataset.color || "#22d3ee";
  const css = `
    .lb-btn{position:fixed;right:22px;bottom:22px;width:62px;height:62px;border-radius:50%;background:${color};border:none;
      box-shadow:0 10px 30px rgba(0,0,0,.35);cursor:pointer;z-index:99998;display:grid;place-items:center;transition:transform .15s}
    .lb-btn:hover{transform:scale(1.06)} .lb-btn svg{width:28px;height:28px}
    .lb-badge{position:fixed;right:92px;bottom:38px;background:#0f172a;color:#e2e8f0;font:13px system-ui;padding:8px 12px;
      border-radius:10px;z-index:99998;box-shadow:0 6px 20px rgba(0,0,0,.3)}
    .lb-frame{position:fixed;right:22px;bottom:96px;width:390px;height:600px;max-height:calc(100vh - 120px);max-width:calc(100vw - 30px);
      border:1px solid #1f2a3c;border-radius:16px;overflow:hidden;z-index:99999;box-shadow:0 20px 60px rgba(0,0,0,.45);display:none;background:#0a0e16}
    .lb-frame.open{display:block} .lb-frame iframe{width:100%;height:100%;border:0}`;
  const st = document.createElement("style"); st.textContent = css; document.head.appendChild(st);
  const btn = document.createElement("button"); btn.className = "lb-btn"; btn.title = "Talk to an advisor";
  btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="#04232b" stroke-width="2.2" stroke-linecap="round"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>';
  const badge = document.createElement("div"); badge.className = "lb-badge";
  badge.textContent = lang === "fr" ? "Une question ? Parlez à notre conseiller" : "Questions? Talk to our advisor";
  const frame = document.createElement("div"); frame.className = "lb-frame";
  frame.innerHTML = `<iframe src="${base}/client?embed=1&lang=${lang}" allow="microphone; autoplay"></iframe>`;
  btn.onclick = () => { frame.classList.toggle("open"); badge.remove(); };
  document.body.append(frame, badge, btn);
})();
