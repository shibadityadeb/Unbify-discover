/* UNBIFY Discover — client for the Experience Orchestrator.
   Renders one interaction at a time; sends responses; the server decides
   everything else. Degrades gracefully when no server is running. */

(function () {
  "use strict";

  const API = "/v1/discover";
  const CHAPTER_LABELS = {
    SELF_DISCOVERY: "Chapter I · Self Discovery",
    SELF_DISCOVERY_CLOSING: "Chapter I · Self Discovery",
    REFLECTION: "Chapter II · Reflection",
    REFLECTION_CLOSING: "Chapter II · Reflection",
    ALIGNMENT: "Chapter III · Alignment",
    ALIGNMENT_CLOSING: "Chapter III · Alignment",
    TRANSFORMATION: "Chapter IV · Transformation",
    TRANSFORMATION_CLOSING: "Chapter IV · Transformation",
    STORY_COMPLETE: "The Story, Complete",
    DISCOVER_WORKSPACE: "My UNBIFY",
  };
  const STATE_TO_OPENER = {
    REFLECTION: "reflection", ALIGNMENT: "alignment", TRANSFORMATION: "transformation",
  };

  let root, stage, chapterEl, progressEl, fieldEl, threadEl;
  let assistTimer = null;
  let helpUsed = false;
  let sessionId = localStorage.getItem("unbify-discover-session") || null;
  let shownAt = 0;
  let busy = false;

  function ensureDom() {
    if (root) return;
    root = document.createElement("section");
    root.className = "dx";
    root.id = "dx";
    root.innerHTML = `
      <div class="dx-haze"></div>
      <div class="dx-field"></div>
      <div class="dx-brand"><img class="brand-img" src="assets/unbify-logo.png" alt="unbify"></div>
      <p class="dx-chapter"></p>
      <div class="dx-thread"></div>
      <div class="dx-stage"></div>
      <div class="dx-progress"></div>`;
    document.body.appendChild(root);
    stage = root.querySelector(".dx-stage");
    chapterEl = root.querySelector(".dx-chapter");
    progressEl = root.querySelector(".dx-progress");
    fieldEl = root.querySelector(".dx-field");
    threadEl = root.querySelector(".dx-thread");
  }

  async function api(path, body, method) {
    const res = await fetch(API + path, {
      method: method || "POST",
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!res.ok) throw new Error("api " + res.status);
    return res.json();
  }

  const CHAPTER_STATES = {
    self_discovery: "SELF_DISCOVERY", reflection: "REFLECTION",
    alignment: "ALIGNMENT", transformation: "TRANSFORMATION",
  };

  async function open(chapter, onUnavailable) {
    ensureDom();
    try {
      let data = await api("/sessions", { sessionId });
      sessionId = data.sessionId;
      localStorage.setItem("unbify-discover-session", sessionId);
      /* the chapter opener the user just walked through acknowledges the
         server-offered transition; illegal jumps are rejected server-side */
      const target = CHAPTER_STATES[chapter];
      if (data.interaction.type === "chapter_transition" && data.interaction.next === target) {
        data = await api(`/sessions/${sessionId}/advance`, { to: target });
      }
      document.body.classList.add("dx-open");
      handlePayload(data);
    } catch (e) {
      console.info("Discover experience needs the API server (see README) — continuing the cinematic journey.", e.message);
      if (onUnavailable) onUnavailable();
    }
  }

  function close() {
    document.body.classList.remove("dx-open");
    setTimeout(() => { stage.innerHTML = ""; }, 1000);
  }

  let respondRef = null;

  async function respond(interactionId, response) {
    if (respondRef) { const fn = respondRef; respondRef = null; return fn(interactionId, response); }
    return respondMain(interactionId, response);
  }

  async function respondMain(interactionId, response) {
    if (busy) return;
    busy = true;
    clearTimeout(assistTimer);
    root.querySelector(".dx-assist")?.remove();
    if (helpUsed && response && !response.helpUsed) response.helpUsed = true;
    const elapsedMs = Date.now() - shownAt;
    try {
      const data = await api(`/sessions/${sessionId}/responses`, { interactionId, response, elapsedMs });
      await leaveScene();
      handlePayload(data);
    } catch (e) {
      console.error(e);
    } finally {
      busy = false;
    }
  }

  const CHAPTER_ORDER = ["SELF_DISCOVERY", "REFLECTION", "ALIGNMENT", "TRANSFORMATION"];
  const BASE_STATE = s => (s || "").replace("_CLOSING", "");

  function updateField(fragments, chapter) {
    if (!fieldEl) return;
    const wanted = new Map((fragments || []).map(f => [f.t, f.s]));
    fieldEl.querySelectorAll(".dx-frag").forEach(el => {
      if (!wanted.has(el.dataset.t)) { el.classList.add("fading"); setTimeout(() => el.remove(), 2200); }
    });
    let salt = 0;
    for (const ch of (chapter || "")) salt += ch.charCodeAt(0);
    wanted.forEach((s, t) => {
      let el = fieldEl.querySelector(`.dx-frag[data-t="${CSS.escape(t)}"]`);
      if (!el) {
        el = document.createElement("span");
        el.className = "dx-frag";
        el.dataset.t = t;
        el.textContent = t;
        fieldEl.appendChild(el);
      }
      let h = salt;
      for (const ch of t) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
      el.style.left = (8 + (h % 80)) + "%";
      el.style.top = (12 + ((h >> 7) % 70)) + "%";
      el.style.opacity = Math.min(0.34, 0.1 + s * 0.28);
    });
  }

  function updateThread(state) {
    if (!threadEl) return;
    const idx = CHAPTER_ORDER.indexOf(BASE_STATE(state));
    if (idx < 0) { threadEl.innerHTML = ""; return; }
    const label = ["01 SELF DISCOVERY", "02 REFLECTION", "03 ALIGNMENT", "04 TRANSFORMATION"][idx];
    threadEl.innerHTML = `<span class="tl">${label}</span><span class="tline">` +
      CHAPTER_ORDER.map((_, i) => `<i class="${i <= idx ? "on" : ""}"></i>`).join("") + `</span>`;
  }

  function handlePayload(data) {
    const it = data.interaction;
    chapterEl.textContent = CHAPTER_LABELS[data.chapter] || "";
    progressEl.style.width = Math.round((data.estimatedProgress || 0) * 100) + "%";
    updateField(data.fragments, data.chapter);
    updateThread(data.state);

    if (it.type === "chapter_transition") {
      const opener = STATE_TO_OPENER[it.next];
      if (opener) {
        if (it.closing && it.closing.length) {
          renderClosing(newSceneFresh(), it.closing, () => {
            close();
            window.dispatchEvent(new CustomEvent("discover:chapter", { detail: { next: opener } }));
          });
          return;
        }
        close();
        window.dispatchEvent(new CustomEvent("discover:chapter", { detail: { next: opener } }));
      } else {
        /* PROLOGUE -> SELF_DISCOVERY happens inside the experience itself */
        api(`/sessions/${sessionId}/advance`, { to: it.next }).then(handlePayload);
      }
      return;
    }
    if (it.type === "chapter_closing") { renderChapterClosing(newSceneFresh(), it); return; }
    if (it.type === "story_close") { renderStoryClose(newSceneFresh(), it); return; }
    if (it.type === "workspace") { renderWorkspace(newSceneFresh(), it); return; }
    render(it);
  }

  /* ---------------- rendering ---------------- */

  function renderChapterClosing(scene, it) {
    stage.classList.add("dx-scroll");
    scene.classList.add("dx-closingpage");
    (it.sections || []).forEach(sec => {
      const block = document.createElement("div");
      block.className = "dx-close-sec";
      if (sec.label) {
        const l = document.createElement("p");
        l.className = "cs-label";
        l.textContent = sec.label;
        block.appendChild(l);
      }
      const t = document.createElement("p");
      t.className = "cs-text";
      t.textContent = sec.text;
      block.appendChild(t);
      scene.appendChild(block);
    });
    const btn = document.createElement("button");
    btn.className = "dx-commit ready dx-close-cta";
    btn.textContent = it.cta || "Continue →";
    scene.appendChild(btn);
    /* scroll reveals; content never disappears; only the click advances */
    const io = new IntersectionObserver(entries => {
      entries.forEach(e => { if (e.isIntersecting) e.target.classList.add("in"); });
    }, { threshold: 0.35 });
    scene.querySelectorAll(".dx-close-sec, .dx-close-cta").forEach(el => io.observe(el));
    btn.addEventListener("click", async () => {
      io.disconnect();
      stage.classList.remove("dx-scroll");
      const data = await api(`/sessions/${sessionId}/advance`, { to: it.next });
      const opener = STATE_TO_OPENER[it.next];
      if (opener) {
        close();
        window.dispatchEvent(new CustomEvent("discover:chapter", { detail: { next: opener } }));
      } else {
        handlePayload(data);
      }
    }, { once: true });
  }

  function renderClosing(scene, lines, done) {
    scene.classList.add("dx-final");
    const wrap = document.createElement("div");
    wrap.className = "dx-reveal-lines";
    lines.forEach((line, i) => {
      const p = document.createElement("p");
      p.className = "dx-reveal-line dx-closing-line";
      p.textContent = line;
      wrap.appendChild(p);
      setTimeout(() => p.classList.add("in"), 500 + i * 1350);
    });
    scene.appendChild(wrap);
    setTimeout(done, 500 + lines.length * 1350 + 1100);
  }

  /* gentle latency assist — configurable by interaction type; never pressure */
  const ASSIST_DELAY = { micro_reflection: 40000, forced_rank: 30000, object_sort: 30000, default: 20000 };

  function armAssist(it) {
    clearTimeout(assistTimer);
    helpUsed = false;
    if (["reveal", "possible_lives", "final", "workspace"].includes(it.type)) return;
    const delay = ASSIST_DELAY[it.type] || ASSIST_DELAY.default;
    assistTimer = setTimeout(() => showAssist(it), delay);
  }

  function showAssist(it) {
    if (!stage.firstElementChild || root.querySelector(".dx-assist")) return;
    const bar = document.createElement("div");
    bar.className = "dx-assist";
    bar.innerHTML = `<span>Taking a minute?</span>`;
    const helpBtn = document.createElement("button");
    helpBtn.textContent = "Help me choose";
    helpBtn.addEventListener("click", () => {
      helpUsed = true;
      bar.remove();
      const scene = stage.firstElementChild;
      if (scene && !scene.querySelector(".dx-help")) {
        const h = document.createElement("p");
        h.className = "dx-help";
        h.textContent = it.help || "Go with your first instinct — there's no better answer here.";
        const anchor = scene.querySelector(".dx-support") || scene.querySelector(".dx-headline");
        if (anchor) anchor.after(h); else scene.prepend(h);
      }
    });
    const skipBtn = document.createElement("button");
    skipBtn.textContent = "Skip this";
    skipBtn.addEventListener("click", () => { bar.remove(); respond(it.id, { skipped: true, helpUsed }); });
    bar.appendChild(helpBtn);
    bar.appendChild(skipBtn);
    root.appendChild(bar);
    requestAnimationFrame(() => bar.classList.add("in"));
  }

  function newSceneFresh() {
    stage.innerHTML = "";
    shownAt = Date.now();
    return newScene();
  }

  function renderStoryClose(scene, it) {
    scene.classList.add("dx-final");
    const wrap = document.createElement("div");
    wrap.className = "dx-reveal-lines";
    (it.lines || []).forEach((line, i) => {
      const p = document.createElement("p");
      p.className = "dx-reveal-line";
      p.textContent = line;
      wrap.appendChild(p);
      setTimeout(() => p.classList.add("in"), 600 + i * 1200);
    });
    scene.appendChild(wrap);
    const btn = document.createElement("button");
    btn.className = "dx-commit dx-continue";
    btn.textContent = it.cta || "See your Opportunity Map";
    scene.appendChild(btn);
    setTimeout(() => btn.classList.add("ready"), 600 + (it.lines || []).length * 1200 + 600);
    btn.addEventListener("click", async () => {
      const data = await api(`/sessions/${sessionId}/advance`, { to: "DISCOVER_WORKSPACE" });
      handlePayload(data);
    });
  }

  /* ---------------- PART TWO: the persistent workspace ---------------- */

  async function wsApi(path, body, method) {
    const res = await fetch("/v1/workspace/" + sessionId + path, {
      method: method || "GET",
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!res.ok) throw new Error("ws " + res.status);
    return res.json();
  }

  function renderWorkspace(scene, ws) {
    scene.classList.add("dx-ws");
    scene.innerHTML = `
      <div class="ws-head">
        <p class="ws-kicker">My UNBIFY</p>
        <p class="ws-clarity">Profile clarity · <em>${esc(ws.clarity)}</em></p>
      </div>
      <div class="ws-tabs">
        <button class="ws-tab active" data-tab="actions">Actions</button>
        <button class="ws-tab" data-tab="questions">Questions</button>
      </div>
      <div class="ws-body"></div>`;
    const body = scene.querySelector(".ws-body");
    const tabs = scene.querySelectorAll(".ws-tab");
    tabs.forEach(t => t.addEventListener("click", () => {
      tabs.forEach(x => x.classList.toggle("active", x === t));
      if (t.dataset.tab === "actions") showActions(body, ws);
      else showQuestions(body, ws);
    }));
    showActions(body, ws);
  }

  function showActions(body, ws) {
    body.innerHTML = "";
    const list = document.createElement("div");
    list.className = "ws-actions";
    (ws.actions || []).forEach((a, i) => {
      const row = document.createElement("button");
      row.className = "ws-action";
      row.style.animationDelay = (i * 70) + "ms";
      row.innerHTML = `<span class="lbl">${esc(a.label)}</span><span class="hint">${esc(a.hint)}</span>
        <svg viewBox="0 0 34 12" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"><path d="M0 6 H31 M26 1.5 L31.5 6 L26 10.5"/></svg>`;
      row.addEventListener("click", async () => {
        const detail = await wsApi("/actions/" + a.id);
        showActionDetail(body, ws, detail);
      });
      list.appendChild(row);
    });
    body.appendChild(list);
  }

  function backRow(body, ws) {
    const back = document.createElement("button");
    back.className = "dx-skip ws-back";
    back.textContent = "← Back to actions";
    back.addEventListener("click", () => showActions(body, ws));
    return back;
  }

  function showActionDetail(body, ws, d) {
    body.innerHTML = "";
    const wrap = document.createElement("div");
    wrap.className = "ws-detail";
    const h = document.createElement("h3");
    h.className = "ws-detail-head";
    h.textContent = d.headline;
    wrap.appendChild(h);

    if (d.kind === "map") {
      const sub = document.createElement("p");
      sub.className = "dx-support";
      sub.textContent = d.supportingText || "";
      wrap.appendChild(sub);
      const row = document.createElement("div");
      row.className = "dx-lives";
      (d.lives || []).forEach(l => {
        const card = document.createElement("div");
        card.className = "dx-life";
        const why = (l.whyThis || []).map(f =>
          `<span style="display:inline-block;margin:2px 6px 2px 0;">${f.value >= 0 ? "+" : "−"} ${esc(f.factor)}</span>`).join("");
        card.innerHTML = `
          <h3>${esc(l.name)}</h3>
          <p class="ess">${esc(l.essence)}</p>
          <dl>
            <dt>Why you</dt><dd>${esc(l.whyYou)}</dd>
            <dt>Why this, honestly</dt><dd>${why}</dd>
            <dt>Missing pieces</dt><dd>${esc(l.requires)}</dd>
            <dt>First experiment</dt><dd>${esc(l.firstExperiment)}</dd>
          </dl>
          <div class="meta"><span>risk · ${esc(l.risk)}</span><span>${esc(l.timeToValue)}</span><span>confidence ${esc(String(l.confidence))}%</span></div>
          <div class="ws-life-acts">
            <button class="dx-pill" data-act="save">Save</button>
            <button class="dx-pill" data-act="start">Start a first experiment</button>
          </div>`;
        card.querySelector('[data-act="save"]').addEventListener("click", async (e) => {
          e.target.classList.add("picked");
          fetch(`/v1/opportunities/${l.key}/save`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sessionId }) }).catch(() => {});
        });
        card.querySelector('[data-act="start"]').addEventListener("click", async (e) => {
          e.target.classList.add("picked");
          e.target.textContent = "Started — it's yours now";
          await api(`/sessions/${sessionId}/activate`, { action: "start", opportunityId: l.key }).catch(() => {});
          fetch(`/v1/opportunities/${l.key}/explore`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sessionId }) }).catch(() => {});
        });
        row.appendChild(card);
      });
      wrap.appendChild(row);
    } else if (d.kind === "list") {
      const ul = document.createElement("div");
      ul.className = "ws-list";
      (d.items || []).forEach(item => {
        const p = document.createElement("p");
        p.className = "ws-item";
        p.textContent = item;
        ul.appendChild(p);
      });
      wrap.appendChild(ul);
    } else if (d.kind === "compare") {
      const row = document.createElement("div");
      row.className = "dx-lives";
      [d.a, d.b].forEach(l => {
        const card = document.createElement("div");
        card.className = "dx-life";
        card.style.cursor = "default";
        const why = (l.whyThis || []).map(f =>
          `<span style="display:inline-block;margin:2px 6px 2px 0;">${f.value >= 0 ? "+" : "−"} ${esc(f.factor)}</span>`).join("");
        card.innerHTML = `<h3>${esc(l.name)}</h3><p class="ess">${esc(l.essence)}</p>
          <dl><dt>For you because</dt><dd>${esc(l.whyYou)}</dd>
          <dt>Factors</dt><dd>${why}</dd>
          <dt>Missing</dt><dd>${esc(l.requires)}</dd></dl>
          <div class="meta"><span>risk · ${esc(l.risk)}</span><span>${esc(l.timeToValue)}</span></div>`;
        row.appendChild(card);
      });
      wrap.appendChild(row);
    } else {
      const t = document.createElement("p");
      t.className = "ws-single-title";
      t.textContent = d.title || "";
      wrap.appendChild(t);
      const tx = document.createElement("p");
      tx.className = "ws-single-text";
      tx.textContent = d.text || "";
      wrap.appendChild(tx);
    }
    if (d.note) {
      const n = document.createElement("p");
      n.className = "ws-note";
      n.textContent = d.note;
      wrap.appendChild(n);
    }
    wrap.appendChild(backRow(body, ws));
    body.appendChild(wrap);
  }

  function showQuestions(body, ws) {
    body.innerHTML = "";
    const wrap = document.createElement("div");
    wrap.className = "ws-detail";
    const invite = document.createElement("p");
    invite.className = "ws-single-text";
    invite.textContent = ws.questions?.invite || "";
    wrap.appendChild(invite);
    if (ws.questions?.available > 0) {
      const btn = document.createElement("button");
      btn.className = "dx-commit ready";
      btn.textContent = "Continue";
      btn.addEventListener("click", () => nextQuestion(body, ws));
      wrap.appendChild(btn);
    }
    body.appendChild(wrap);
  }

  async function nextQuestion(body, ws) {
    const data = await wsApi("/questions/next", {}, "POST");
    const it = data.interaction;
    if (it.type === "workspace") { renderWorkspace(newSceneFresh(), it); return; }
    body.innerHTML = "";
    const holder = document.createElement("div");
    holder.className = "ws-question dx-scene entered";
    body.appendChild(holder);
    shownAt = Date.now();
    const scene = holder;
    /* render the question with the standard primitives, then return to the tab */
    const origRespond = respond;
    const localRespond = async (interactionId, response) => {
      if (busy) return;
      busy = true;
      try {
        const out = await api(`/sessions/${sessionId}/responses`, { interactionId, response, elapsedMs: Date.now() - shownAt });
        busy = false;
        if (out.interaction?.type === "workspace") renderWorkspace(newSceneFresh(), out.interaction);
      } catch (e) { busy = false; console.error(e); }
    };
    renderInto(scene, it, localRespond);
  }

  function renderInto(scene, it, respondFn) {
    const saved = respondRef;
    respondRef = respondFn;
    try {
      switch (it.type) {
        case "scenario_choice": renderScenario(scene, it); break;
        case "binary_tension":
        case "spectrum": renderSlider(scene, it); break;
        case "forced_rank":
        case "object_sort": renderChips(scene, it); break;
        case "micro_reflection": renderReflection(scene, it); break;
        default: scene.textContent = "…";
      }
    } finally {
      /* respondRef restored on next full render */
    }
  }

  function leaveScene() {
    return new Promise(resolve => {
      const scene = stage.firstElementChild;
      if (!scene) return resolve();
      scene.classList.add("leaving");
      setTimeout(() => { stage.innerHTML = ""; resolve(); }, 520);
    });
  }

  function newScene() {
    const scene = document.createElement("div");
    scene.className = "dx-scene entering";
    stage.appendChild(scene);
    requestAnimationFrame(() => requestAnimationFrame(() => {
      scene.classList.remove("entering");
      scene.classList.add("entered");
    }));
    return scene;
  }

  function headlineBlock(scene, it, { wordByWord = false } = {}) {
    if (it.headline) {
      const h = document.createElement("h2");
      h.className = "dx-headline";
      if (wordByWord) {
        it.headline.split(" ").forEach((w, i) => {
          const s = document.createElement("span");
          s.className = "dx-word";
          s.textContent = w + " ";
          setTimeout(() => s.classList.add("in"), 250 + i * 110);
          h.appendChild(s);
        });
      } else h.textContent = it.headline;
      scene.appendChild(h);
    }
    if (it.supportingText) {
      const p = document.createElement("p");
      p.className = "dx-support";
      p.textContent = it.supportingText;
      scene.appendChild(p);
    }
  }

  function render(it) {
    shownAt = Date.now();
    armAssist(it);
    const scene = newScene();
    if (it.bridge) {
      const b = document.createElement("p");
      b.className = "dx-bridge";
      b.textContent = it.bridge;
      scene.appendChild(b);
      setTimeout(() => b.classList.add("in"), 150);
    }
    switch (it.type) {
      case "visual_choice": return renderVisual(scene, it);
      case "scenario_choice": return renderScenario(scene, it);
      case "binary_tension":
      case "spectrum": return renderSlider(scene, it);
      case "forced_rank":
      case "object_sort": return renderChips(scene, it);
      case "micro_reflection": return renderReflection(scene, it);
      case "reveal": return renderReveal(scene, it);
      case "possible_lives": return renderLives(scene, it);
      case "final": return renderFinal(scene, it);
      default:
        scene.textContent = "…";
    }
  }

  function renderVisual(scene, it) {
    headlineBlock(scene, it, { wordByWord: true });
    const row = document.createElement("div");
    row.className = "dx-scenes";
    it.options.forEach(o => {
      const b = document.createElement("button");
      b.className = "dv-scene";
      b.innerHTML = `<span class="art m-${o.motif || "path"}"></span><span class="lbl">${esc(o.label)}</span>`;
      b.addEventListener("click", () => {
        b.classList.add("picked");
        setTimeout(() => respond(it.id, { optionId: o.id }), 420);
      });
      row.appendChild(b);
    });
    scene.appendChild(row);
  }

  function renderScenario(scene, it) {
    headlineBlock(scene, it, { wordByWord: true });
    const wrap = document.createElement("div");
    wrap.className = "dx-options";
    it.options.forEach((o, i) => {
      const b = document.createElement("button");
      b.className = "dx-opt";
      b.textContent = o.label;
      setTimeout(() => b.classList.add("in"), (it.bridge ? 1300 : 500) + i * 160);
      b.addEventListener("click", () => {
        b.classList.add("picked");
        setTimeout(() => respond(it.id, { optionId: o.id }), 380);
      });
      wrap.appendChild(b);
    });
    scene.appendChild(wrap);
  }

  function renderSlider(scene, it) {
    headlineBlock(scene, it);
    const w = document.createElement("div");
    w.className = "dx-slider";
    w.innerHTML = `
      <div class="dx-poles">
        <span class="dx-pole left">${esc(it.left.label)}</span>
        <span class="dx-pole right">${esc(it.right.label)}</span>
      </div>
      <div class="dx-track"><div class="dx-handle"></div></div>`;
    scene.appendChild(w);
    const commit = document.createElement("button");
    commit.className = "dx-commit";
    commit.textContent = "This feels right";
    scene.appendChild(commit);

    const track = w.querySelector(".dx-track");
    const handle = w.querySelector(".dx-handle");
    const poleL = w.querySelector(".dx-pole.left");
    const poleR = w.querySelector(".dx-pole.right");
    let value = 0, moved = false;

    function setValue(v) {
      value = Math.max(-1, Math.min(1, v));
      handle.style.left = ((value + 1) / 2 * 100) + "%";
      poleL.classList.toggle("active", value < -0.18);
      poleR.classList.toggle("active", value > 0.18);
    }
    function fromEvent(e) {
      const r = track.getBoundingClientRect();
      const x = (e.touches ? e.touches[0].clientX : e.clientX) - r.left;
      setValue((x / r.width) * 2 - 1);
      if (!moved) { moved = true; commit.classList.add("ready"); }
    }
    let dragging = false;
    const start = e => { dragging = true; fromEvent(e); e.preventDefault(); };
    const move = e => { if (dragging) fromEvent(e); };
    const end = () => { dragging = false; };
    handle.addEventListener("pointerdown", start);
    track.addEventListener("pointerdown", start);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", end);
    commit.addEventListener("click", () => respond(it.id, { value }));
    setValue(0);
  }

  function renderChips(scene, it) {
    headlineBlock(scene, it, { wordByWord: true });
    const max = it.maxSelect || 3;
    const wrap = document.createElement("div");
    wrap.className = "dx-chips";
    const held = new Set();
    const keep = document.createElement("p");
    keep.className = "dx-keep";
    const commit = document.createElement("button");
    commit.className = "dx-commit";
    commit.textContent = "These are mine";
    function sync() {
      keep.textContent = held.size === 0 ? `Choose ${max === 8 ? "what's true" : "up to " + max}` : `${held.size} held`;
      commit.classList.toggle("ready", held.size >= (it.minSelect || Math.min(3, max)));
    }
    it.options.forEach(o => {
      const b = document.createElement("button");
      b.className = "dx-chip";
      b.textContent = o.label;
      b.addEventListener("click", () => {
        if (held.has(o.id)) { held.delete(o.id); b.classList.remove("held"); }
        else if (held.size < max) { held.add(o.id); b.classList.add("held"); }
        sync();
      });
      wrap.appendChild(b);
    });
    scene.appendChild(wrap);
    scene.appendChild(keep);
    scene.appendChild(commit);
    sync();
    commit.addEventListener("click", () => respond(it.id, { optionIds: [...held] }));
  }

  function renderReflection(scene, it) {
    headlineBlock(scene, it, { wordByWord: true });
    const wrap = document.createElement("div");
    wrap.className = "dx-input-wrap";
    const input = document.createElement("input");
    input.className = "dx-input";
    input.type = "text";
    input.maxLength = 160;
    input.placeholder = it.placeholder || "One honest line…";
    wrap.appendChild(input);
    scene.appendChild(wrap);
    const commit = document.createElement("button");
    commit.className = "dx-commit";
    commit.textContent = "That's true";
    scene.appendChild(commit);
    const skip = document.createElement("button");
    skip.className = "dx-skip";
    skip.textContent = "Rather not say";
    scene.appendChild(skip);
    input.addEventListener("input", () => commit.classList.toggle("ready", input.value.trim().length > 2));
    input.addEventListener("keydown", e => { if (e.key === "Enter" && input.value.trim().length > 2) respond(it.id, { text: input.value.trim() }); });
    commit.addEventListener("click", () => respond(it.id, { text: input.value.trim() }));
    skip.addEventListener("click", () => respond(it.id, { skipped: true }));
    setTimeout(() => input.focus({ preventScroll: true }), 900);
  }

  function renderReveal(scene, it) {
    const wrap = document.createElement("div");
    wrap.className = "dx-reveal-lines";
    scene.appendChild(wrap);
    const timers = [];
    it.lines.forEach((line, i) => {
      const p = document.createElement("p");
      p.className = "dx-reveal-line";
      p.textContent = line;
      wrap.appendChild(p);
      timers.push(setTimeout(() => p.classList.add("in"), 600 + i * 1250));
    });
    /* tap anywhere to reveal everything at once — never gate reading on animation */
    scene.addEventListener("click", () => {
      timers.forEach(clearTimeout);
      wrap.querySelectorAll(".dx-reveal-line").forEach(p => p.classList.add("in"));
      calib.classList.add("in");
    }, { once: true });
    const calib = document.createElement("div");
    calib.className = "dx-calib";
    it.calibration.forEach(c => {
      const b = document.createElement("button");
      b.className = "dx-pill";
      b.textContent = c.label;
      b.addEventListener("click", () => {
        b.classList.add("picked");
        setTimeout(() => respond(it.id, { optionId: c.id }), 350);
      });
      calib.appendChild(b);
    });
    scene.appendChild(calib);
    setTimeout(() => calib.classList.add("in"), 600 + it.lines.length * 1250 + 400);
  }

  function renderLives(scene, it) {
    headlineBlock(scene, it, { wordByWord: true });
    const row = document.createElement("div");
    row.className = "dx-lives";
    it.lives.forEach(l => {
      const card = document.createElement("div");
      card.className = "dx-life";
      card.dataset.key = l.key;
      card.innerHTML = `
        <h3>${esc(l.name)}</h3>
        <p class="ess">${esc(l.essence)}</p>
        <dl>
          <dt>Why you</dt><dd>${esc(l.whyYou)}</dd>
          <dt>Why now</dt><dd>${esc(l.whyNow)}</dd>
          <dt>It would use</dt><dd>${esc(l.uses)}</dd>
          <dt>It would require</dt><dd>${esc(l.requires)}</dd>
          <dt>The honest friction</dt><dd>${esc(l.friction)}</dd>
        </dl>
        <div class="meta"><span>risk · ${esc(l.risk)}</span><span>${esc(l.timeToValue)}</span></div>`;
      row.appendChild(card);
    });
    scene.appendChild(row);
    const ask = document.createElement("p");
    ask.className = "dx-ask";
    ask.textContent = it.ask;
    scene.appendChild(ask);
    const pills = document.createElement("div");
    pills.className = "dx-pills";
    it.options.forEach(o => {
      const b = document.createElement("button");
      b.className = "dx-pill";
      b.textContent = o.label;
      b.addEventListener("click", () => {
        b.classList.add("picked");
        row.querySelectorAll(".dx-life").forEach(c => c.classList.toggle("picked", c.dataset.key === o.id));
        setTimeout(() => respond(it.id, { optionId: o.id }), 500);
      });
      pills.appendChild(b);
    });
    scene.appendChild(pills);
  }

  function renderFinal(scene, it) {
    scene.classList.add("dx-final");
    const opening = document.createElement("div");
    opening.className = "dx-reveal-lines";
    (it.opening || []).forEach((line, i) => {
      const p = document.createElement("p");
      p.className = "dx-reveal-line";
      p.textContent = line;
      opening.appendChild(p);
      setTimeout(() => p.classList.add("in"), 500 + i * 1100);
    });
    scene.appendChild(opening);
    const baseDelay = 500 + (it.opening || []).length * 1100 + 600;

    const mirror = document.createElement("div");
    mirror.className = "dx-mirror";
    (it.mirror || []).forEach((m, i) => {
      const item = document.createElement("div");
      item.className = "dx-mirror-item";
      item.innerHTML = `<p class="lbl">${esc(m.label)}</p><p class="txt">${esc(m.text)}</p>`;
      mirror.appendChild(item);
      setTimeout(() => item.classList.add("in"), baseDelay + i * 700);
    });
    scene.appendChild(mirror);

    const mapDelay = baseDelay + (it.mirror || []).length * 700 + 600;
    if (it.map && it.map.length) {
      const mapWrap = document.createElement("div");
      mapWrap.className = "dx-lives";
      mapWrap.style.opacity = "0";
      mapWrap.style.transition = "opacity 1.2s ease";
      it.map.forEach(l => {
        const card = document.createElement("div");
        card.className = "dx-life";
        card.style.cursor = "default";
        card.innerHTML = `
          <h3>${esc(l.name)}</h3>
          <p class="ess">${esc(l.essence)}</p>
          <dl>
            <dt>Existing advantages</dt><dd>${esc(l.uses)}</dd>
            <dt>Missing pieces</dt><dd>${esc(l.requires)}</dd>
            <dt>First experiment</dt><dd>${esc(l.firstExperiment)}</dd>
          </dl>
          <div class="meta"><span>risk · ${esc(l.risk)}</span><span>${esc(l.timeToValue)}</span><span>confidence ${esc(String(l.confidence))}%</span></div>`;
        mapWrap.appendChild(card);
      });
      scene.appendChild(mapWrap);
      setTimeout(() => { mapWrap.style.opacity = "1"; }, mapDelay);
    }

    const next = document.createElement("div");
    next.className = "dx-next";
    next.style.opacity = "0";
    next.style.transition = "opacity 1.2s ease";
    next.innerHTML = `
      <p class="lbl">${esc(it.nextAction?.headline || "One small next step")}</p>
      <p class="txt">${esc(it.nextAction?.text || "")}</p>
      <p class="note">${esc(it.nextAction?.note || "")}</p>`;
    scene.appendChild(next);
    setTimeout(() => { next.style.opacity = "1"; }, mapDelay + 900);

    const done = document.createElement("button");
    done.className = "dx-commit dx-continue";
    done.textContent = "Continue →";
    scene.appendChild(done);
    setTimeout(() => done.classList.add("ready"), mapDelay + 1200);
    done.addEventListener("click", () => respond(it.id, { done: true }));
  }

  function esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  window.UnbifyDiscover = { open, close };
})();
