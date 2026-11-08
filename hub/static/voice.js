// Voice: Web Speech API (speech to text + speech synthesis).
// Works in Chrome and Edge (speech recognition needs internet in Chrome). Text input is always the fallback.
(function () {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  let rec = null;
  let voices = [];
  const loadVoices = () => { voices = window.speechSynthesis ? speechSynthesis.getVoices() : []; };
  if (window.speechSynthesis) { loadVoices(); speechSynthesis.onvoiceschanged = loadVoices; }

  function pickVoice(lang) {
    const want = lang === "fr" ? "fr" : "en";
    const list = voices.filter(v => v.lang && v.lang.toLowerCase().startsWith(want));
    return list.find(v => /natural|online|google|microsoft/i.test(v.name)) || list[0] || null;
  }

  window.Voice = {
    canListen: !!SR,
    canSpeak: !!window.speechSynthesis,
    listening: false,
    muted: false,

    listen(lang, onInterim, onFinal, onEnd) {
      if (!SR) return false;
      this.stop();
      rec = new SR();
      rec.lang = lang === "fr" ? "fr-FR" : "en-US";
      rec.interimResults = true;
      rec.continuous = false;
      rec.maxAlternatives = 1;
      let finalText = "";
      rec.onresult = (e) => {
        let interim = "";
        for (let i = e.resultIndex; i < e.results.length; i++) {
          const t = e.results[i][0].transcript;
          if (e.results[i].isFinal) finalText += t; else interim += t;
        }
        onInterim && onInterim(finalText + interim);
      };
      rec.onerror = (e) => { console.warn("[voice]", e.error); if (e.error === "not-allowed") UI.toast("Microphone blocked: allow it in the browser."); };
      rec.onend = () => {
        this.listening = false;
        if (finalText.trim()) onFinal && onFinal(finalText.trim());
        onEnd && onEnd();
      };
      window.speechSynthesis && speechSynthesis.cancel();
      rec.start();
      this.listening = true;
      return true;
    },

    stop() { try { rec && rec.stop(); } catch (e) {} this.listening = false; },

    speak(text, lang, onEnd) {
      if (!window.speechSynthesis || this.muted) { onEnd && onEnd(); return; }
      speechSynthesis.cancel();
      const clean = text.replace(/[«»"*]/g, "").replace(/TND/g, lang === "fr" ? "dinars" : "dinars");
      const u = new SpeechSynthesisUtterance(clean);
      u.lang = lang === "fr" ? "fr-FR" : "en-US";
      const v = pickVoice(lang); if (v) u.voice = v;
      u.rate = 1.05; u.pitch = 1;
      u.onend = () => onEnd && onEnd();
      speechSynthesis.speak(u);
    },

    shutUp() { window.speechSynthesis && speechSynthesis.cancel(); },
  };
})();
