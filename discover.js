/* UNBIFY Discover — client for the Experience Orchestrator.
   Renders one interaction at a time; sends responses; the server decides
   everything else. Degrades gracefully when no server is running. */

(function () {
  "use strict";

  const API = "/api/discover";
  const CHAPTER_LABELS = {
    self_discovery: "Chapter I · Self Discovery",
    reflection: "Chapter II · Reflection",
    alignment: "Chapter III · Alignment",
    transformation: "Chapter IV · Transformation",
  };

  let root, stage, chapterEl, progressEl;
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
      <div class="dx-brand"><img class="brand-img" src="assets/unbify-logo.png" alt="unbify"></div>
      <p class="dx-chapter"></p>
      <div class="dx-stage"></div>
      <div class="dx-progress"></div>`;
    document.body.appendChild(root);
    stage = root.querySelector(".dx-stage");
    chapterEl = root.querySelector(".dx-chapter");
    progressEl = root.querySelector(".dx-progress");
  }

  async function api(path, body) {
    const res = await fetch(API + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error("api " + res.status);
    return res.json();
  }

  async function open(chapter, onUnavailable) {
    ensureDom();
    try {
      const data = await api("/session", { sessionId, chapter });
      sessionId = data.sessionId;
      localStorage.setItem("unbify-discover-session", sessionId);
      document.body.classList.add("dx-open");
      handlePayload(data);
    } catch (e) {
      console.info("Discover experience needs the node server (npm start) — continuing the cinematic journey.", e.message);
      if (onUnavailable) onUnavailable();
    }
  }

  function close() {
    document.body.classList.remove("dx-open");
    setTimeout(() => { stage.innerHTML = ""; }, 1000);
  }

  async function respond(interactionId, response) {
    if (busy) return;
    busy = true;
    const elapsedMs = Date.now() - shownAt;
    try {
      const data = await api("/respond", { sessionId, interactionId, response, elapsedMs });
      await leaveScene();
      handlePayload(data);
    } catch (e) {
      console.error(e);
    } finally {
      busy = false;
    }
  }

  function handlePayload(data) {
    const it = data.interaction;
    chapterEl.textContent = CHAPTER_LABELS[data.chapter] || "";
    progressEl.style.width = Math.round((data.estimatedProgress || 0) * 100) + "%";

    if (it.type === "chapter_transition") {
      close();
      window.dispatchEvent(new CustomEvent("discover:chapter", { detail: { next: it.next } }));
      return;
    }
    if (it.type === "journey_complete") {
      close();
      window.dispatchEvent(new CustomEvent("discover:complete"));
      return;
    }
    render(it);
  }

  /* ---------------- rendering ---------------- */

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
    const scene = newScene();
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
      setTimeout(() => b.classList.add("in"), 500 + i * 160);
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
    it.lines.forEach((line, i) => {
      const p = document.createElement("p");
      p.className = "dx-reveal-line";
      p.textContent = line;
      wrap.appendChild(p);
      setTimeout(() => p.classList.add("in"), 600 + i * 1250);
    });
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
    done.className = "dx-commit ready dx-continue";
    done.textContent = "Carry it forward";
    scene.appendChild(done);
    done.addEventListener("click", () => respond(it.id, { done: true }));
  }

  function esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  window.UnbifyDiscover = { open, close };
})();
