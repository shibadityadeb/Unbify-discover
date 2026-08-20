/* UNBIFY Discover — client for the Experience Orchestrator.
   Renders one interaction at a time; sends responses; the server decides
   everything else. Degrades gracefully when no server is running. */

(function () {
  "use strict";

  const API = "/v1/discover";
  const DEV = /^(localhost|127\.0\.0\.1|\[::1\])$/.test(location.hostname);
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
  /* No persistence until there is an account to attach it to.

     A resumed session is only meaningful if we know whose it is. With no auth,
     the stored id belongs to "whoever last used this browser" — so a reload
     dropped people back into Chapter IV of someone else's half-finished run,
     with no way to start over and no signed-in identity that would justify it.
     Every page load now begins a new session; the id lives in memory for the
     length of the visit, which is what keeps one journey coherent.

     Trade-off, deliberately taken: refreshing mid-journey loses progress. When
     accounts exist, resume belongs behind them. */
  try { localStorage.removeItem("unbify-discover-session"); } catch (e) { /* private mode */ }
  let sessionId = null;
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
      <div class="dx-progress"></div>
      <p class="dx-live" role="status" aria-live="polite" aria-atomic="true"></p>`;
    document.body.appendChild(root);
    stage = root.querySelector(".dx-stage");
    chapterEl = root.querySelector(".dx-chapter");
    progressEl = root.querySelector(".dx-progress");
    fieldEl = root.querySelector(".dx-field");
    threadEl = root.querySelector(".dx-thread");
  }

  async function api(path, body, opts) {
    const { method, timeoutMs } = opts || {};
    const controller = timeoutMs ? new AbortController() : null;
    const timer = controller ? setTimeout(() => controller.abort(), timeoutMs) : null;
    try {
      const res = await fetch(API + path, {
        method: method || "POST",
        headers: { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller ? controller.signal : undefined,
      });
      if (!res.ok) throw new Error("api " + res.status);
      return res.json();
    } finally {
      if (timer) clearTimeout(timer);
    }
  }

  const CHAPTER_STATES = {
    self_discovery: "SELF_DISCOVERY", reflection: "REFLECTION",
    alignment: "ALIGNMENT", transformation: "TRANSFORMATION",
  };

  async function open(chapter, onUnavailable) {
    ensureDom();
    clearTimeout(closeTimer);          // never let a previous close() blank us
    closeTimer = null;
    try {
      let data = await api("/sessions", { sessionId });
      sessionId = data.sessionId;
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

  let closeTimer = null;

  /* ---------------- a wait that is visible and exclusive ----------------

     Chapter entry plays an animation and then makes a network call. On a slow
     link that is several seconds during which the page silently swallows every
     scroll and click: input that vanishes reads as a broken page, not a busy
     one. So the wait greys the page out, says what is happening, and takes the
     input itself instead of dropping it.

     It only appears after a short delay — flashing a veil over a 40ms operation
     is worse than showing nothing at all. */
  const BUSY_SHOW_AFTER_MS = 400;
  const BUSY_LONG_MS = 4000;
  let busyEl = null, busyTimers = [], busyDepth = 0;
  const BUSY_BLOCKED = ["wheel", "touchmove", "keydown", "click", "pointerdown"];

  function busyBlock(e) {
    if (!busyEl) return;
    e.stopPropagation();
    if (e.cancelable) e.preventDefault();
  }

  function busyOn(message) {
    busyDepth += 1;
    if (busyEl || busyTimers.length) return;
    busyTimers.push(setTimeout(() => {
      if (busyDepth <= 0) return;
      busyEl = document.createElement("div");
      busyEl.className = "dx-busy";
      busyEl.setAttribute("role", "status");
      busyEl.setAttribute("aria-live", "polite");
      busyEl.innerHTML = `<div class="dx-busy-inner">
          <span class="dx-busy-pulse" aria-hidden="true"></span>
          <p class="dx-busy-text"></p></div>`;
      busyEl.querySelector(".dx-busy-text").textContent = message || "Taking a moment…";
      document.body.appendChild(busyEl);
      document.body.classList.add("dx-busy-on");
      document.body.setAttribute("aria-busy", "true");
      BUSY_BLOCKED.forEach(t => window.addEventListener(t, busyBlock, { capture: true, passive: false }));
      /* Force a reflow and set the visible state synchronously. Going through
         requestAnimationFrame left the veil at opacity 0 whenever rAF was
         throttled (a backgrounded tab), which is the worst possible state: it
         blocks every input while showing nothing at all. */
      void busyEl.offsetWidth;
      busyEl.classList.add("in");
      busyTimers.push(setTimeout(() => {
        const p = busyEl && busyEl.querySelector(".dx-busy-text");
        if (p) p.textContent = "Still working — this one's taking longer than usual.";
      }, BUSY_LONG_MS));
    }, BUSY_SHOW_AFTER_MS));
  }

  function busyOff() {
    busyDepth = Math.max(0, busyDepth - 1);
    if (busyDepth > 0) return;               // another wait is still running
    busyTimers.forEach(clearTimeout);
    busyTimers = [];
    BUSY_BLOCKED.forEach(t => window.removeEventListener(t, busyBlock, { capture: true }));
    document.body.classList.remove("dx-busy-on");
    document.body.removeAttribute("aria-busy");
    if (!busyEl) return;
    const el = busyEl;
    busyEl = null;
    el.classList.remove("in");
    setTimeout(() => el.remove(), 420);
  }

  /* Wrap any promise in the blocking wait; always releases, even on failure. */
  async function withBusy(message, work) {
    busyOn(message);
    try { return await work(); }
    finally { busyOff(); }
  }

  function close() {
    document.body.classList.remove("dx-open");
    /* The wipe is deferred so the fade-out has something to fade. If the next
       chapter opens inside that window the timer would blank a scene that had
       already rendered — rare while every request took seconds, likely once
       they are instant. open() cancels it. */
    clearTimeout(closeTimer);
    closeTimer = setTimeout(() => { stage.innerHTML = ""; closeTimer = null; }, 1000);
  }

  let respondRef = null;

  async function respond(interactionId, response, chosenEl) {
    if (respondRef) { const fn = respondRef; respondRef = null; return fn(interactionId, response, chosenEl); }
    return respondMain(interactionId, response, chosenEl);
  }

  /* ---------------- perceived latency ----------------
     Computation must never look like unresponsiveness. The selection is
     acknowledged locally within a frame, the leave choreography starts
     immediately, and the network request runs alongside it — so animation
     time and network time overlap instead of queueing. */

  const REDUCED_MOTION = window.matchMedia
    ? window.matchMedia("(prefers-reduced-motion: reduce)").matches : false;

  /* latency tiers: below FAST nothing is said, and each escalation must stay
     on screen long enough to actually be read */
  const TIER_NORMAL_MS = 500;      /* ambient motion only, no words          */
  const TIER_NOTICEABLE_MS = 2000; /* one honest, event-derived line         */
  const TIER_LONG_MS = 5000;       /* explicit transparency                  */
  const THINKING_MIN_VISIBLE_MS = 900;
  const REQUEST_TIMEOUT_MS = 30000;

  let thinking = null;

  function announce(message) {
    const live = root.querySelector(".dx-live");
    if (live && message) live.textContent = message;
  }

  function startThinking() {
    stopThinking();
    const el = document.createElement("div");
    el.className = "dx-thinking";
    el.innerHTML = `<span class="dx-thinking-pulse" aria-hidden="true"></span>
                    <p class="dx-thinking-text"></p>`;
    root.appendChild(el);
    const state = { el, shownTextAt: 0, timers: [], done: false };
    thinking = state;

    /* NORMAL: ambient motion only — the screen is alive, nothing is claimed */
    state.timers.push(setTimeout(() => {
      if (!state.done) el.classList.add("ambient");
    }, TIER_NORMAL_MS));

    /* NOTICEABLE: acknowledge that work is happening, in plain language */
    state.timers.push(setTimeout(() => {
      if (state.done) return;
      setThinkingText(state, "Working through that…");
    }, TIER_NOTICEABLE_MS));

    /* LONG: be transparent rather than leaving someone inside an animation */
    state.timers.push(setTimeout(() => {
      if (state.done) return;
      setThinkingText(state, "This one's taking a little longer. We're checking what your answer changes.");
    }, TIER_LONG_MS));
    return state;
  }

  function setThinkingText(state, text) {
    if (!state || state.done) return;
    const p = state.el.querySelector(".dx-thinking-text");
    if (!p || p.textContent === text) return;
    p.textContent = text;
    state.el.classList.add("with-text");
    state.shownTextAt = Date.now();
    announce(text);
  }

  /* the backend says what actually changed; we only borrow those words when
     something real changed, which is what keeps them meaningful */
  function noteChange(state, processing) {
    if (!state || !processing || !processing.changed || !processing.note) return;
    if (Date.now() - state.startedAt < TIER_NOTICEABLE_MS) return;
    setThinkingText(state, processing.note);
  }

  function stopThinking() {
    if (!thinking) return Promise.resolve();
    const state = thinking;
    thinking = null;
    state.done = true;
    state.timers.forEach(clearTimeout);
    const shownFor = state.shownTextAt ? Date.now() - state.shownTextAt : Infinity;
    const wait = state.shownTextAt && shownFor < THINKING_MIN_VISIBLE_MS
      ? THINKING_MIN_VISIBLE_MS - shownFor : 0;
    return new Promise(resolve => setTimeout(() => {
      state.el.classList.add("out");
      setTimeout(() => state.el.remove(), 320);
      resolve();
    }, wait));
  }

  /* acknowledge within a frame: the chosen thing settles, the rest softens */
  /* Chapter transitions went through a bare `await` with no acknowledgement:
     the click did nothing visible until the response landed, and a failure left
     a dead button on a frozen page. The thinking indicator already existed for
     exactly this — it was only ever wired to answering a question, never to
     moving between chapters. */
  async function commitAdvance(btn, request) {
    if (btn.dataset.busy === "1") return null;      // a second click must not advance twice
    btn.dataset.busy = "1";
    btn.classList.add("picked");
    btn.setAttribute("aria-disabled", "true");
    const label = btn.textContent;
    startThinking();
    busyOn("Opening the next chapter…");
    try {
      const data = await request();
      await stopThinking();
      return data;
    } catch (e) {
      await stopThinking();
      btn.dataset.busy = "";
      btn.classList.remove("picked");
      btn.removeAttribute("aria-disabled");
      btn.textContent = "That didn't go through — tap to try again";
      setTimeout(() => { btn.textContent = label; }, 3200);
      return null;
    } finally {
      busyOff();
    }
  }

  function acknowledgeSelection(chosenEl) {
    const scene = stage.firstElementChild;
    if (!scene) return;
    scene.classList.add("dx-answered");
    if (chosenEl) chosenEl.classList.add("dx-chosen");
    scene.querySelectorAll(
      ".dx-option, .dx-opt, .dx-chip, .dx-cal-opt, .dx-pill, button.dx-choice"
    ).forEach(el => {
      if (el !== chosenEl) el.classList.add("dx-softened");
      el.setAttribute("aria-disabled", "true");
      el.tabIndex = -1;
    });
  }

  function showRetry(interactionId, response, chosenEl) {
    const scene = stage.firstElementChild;
    if (!scene) return;
    /* There is only ever one retry. Each failure used to append another block,
       so a few attempts left a column of identical "That didn't go through /
       Try again" pairs and no way to tell which button was live. */
    scene.querySelectorAll(".dx-retry").forEach(el => el.remove());
    const box = document.createElement("div");
    box.className = "dx-retry";
    box.innerHTML = `<p class="dx-retry-text">That didn't go through.</p>`;
    const again = document.createElement("button");
    again.className = "dx-commit ready";
    again.textContent = "Try again";
    again.addEventListener("click", () => {
      box.remove();
      scene.classList.remove("dx-failed");
      respondMain(interactionId, response, chosenEl);   /* answer is preserved */
    }, { once: true });
    box.appendChild(again);
    scene.classList.add("dx-failed");
    scene.appendChild(box);
    announce("That didn't go through. Try again.");
    again.focus({ preventScroll: true });
  }

  async function respondMain(interactionId, response, chosenEl) {
    if (busy) return;
    busy = true;
    const marks = { tap: performance.now() };
    disarmAssist();
    root.querySelector(".dx-assist")?.remove();
    if (helpUsed && response && !response.helpUsed) response.helpUsed = true;
    const elapsedMs = Date.now() - shownAt;

    /* 1. instant local acknowledgement — no backend confirmation needed */
    acknowledgeSelection(chosenEl);
    marks.acknowledged = performance.now();

    /* 2. leave choreography and the request start together */
    const state = startThinking();
    state.startedAt = Date.now();
    const leaving = REDUCED_MOTION ? Promise.resolve() : leaveScene({ keepMemory: true });
    const request = api(`/sessions/${sessionId}/responses`,
                        { interactionId, response, elapsedMs },
                        { timeoutMs: REQUEST_TIMEOUT_MS });

    try {
      const data = await request;
      marks.responded = performance.now();
      noteChange(state, data.processing);
      await leaving;
      await stopThinking();
      clearStage();
      handlePayload(data);
      marks.painted = performance.now();
      logTimeline(marks, data);
    } catch (e) {
      await stopThinking();
      console.error(e);
      showRetry(interactionId, response, chosenEl);
    } finally {
      busy = false;
    }
  }

  function logTimeline(marks, data) {
    if (!DEV) return;
    const ms = (a, b) => Math.round(marks[b] - marks[a]);
    console.info("[discover] latency", {
      acknowledgement: ms("tap", "acknowledged") + "ms",
      network: ms("acknowledged", "responded") + "ms",
      render: ms("responded", "painted") + "ms",
      perceived: ms("tap", "painted") + "ms",
      server: data && data.timings ? data.timings : undefined,
    });
  }

  const CHAPTER_ORDER = ["SELF_DISCOVERY", "REFLECTION", "ALIGNMENT", "TRANSFORMATION"];
  const BASE_STATE = s => (s || "").replace("_CLOSING", "");

  /* Left and right gutters only — the centre belongs to the question. Ordered
     so consecutive slots are far apart, which keeps a run of collisions from
     clustering everything into one corner. */
  const FRAG_SLOTS = [
    [8, 12], [92, 12], [15, 23], [85, 23], [8, 34], [92, 34], [15, 45],
    [85, 45], [8, 56], [92, 56], [15, 67], [85, 67], [8, 78], [92, 78],
    [15, 89], [85, 89],
  ];

  function updateField(fragments, chapter) {
    if (!fieldEl) return;
    const wanted = new Map((fragments || []).map(f => [f.t, f.s]));
    fieldEl.querySelectorAll(".dx-frag").forEach(el => {
      if (!wanted.has(el.dataset.t)) { el.classList.add("fading"); setTimeout(() => el.remove(), 2200); }
    });
    let salt = 0;
    for (const ch of (chapter || "")) salt += ch.charCodeAt(0);
    /* Positions used to come straight from a hash of the fragment text, with
       nothing stopping two fragments landing on the same spot — and when they
       did they rendered exactly on top of each other as unreadable overlapping
       glyphs. Fragments are now placed into fixed, well-separated slots: the
       hash picks a starting slot and we walk to the next free one, so the
       layout stays stable and deterministic but can never collide.
       The slots also avoid the middle column, where the question itself sits. */
    const taken = new Set();
    const sorted = [...wanted.keys()].sort();          // stable regardless of Map order
    sorted.forEach(t => {
      const s = wanted.get(t);
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
      let slot = h % FRAG_SLOTS.length;
      for (let i = 0; i < FRAG_SLOTS.length && taken.has(slot); i++) {
        slot = (slot + 1) % FRAG_SLOTS.length;
      }
      taken.add(slot);
      const [x, y] = FRAG_SLOTS[slot];
      /* Anchor by the edge the fragment sits against, never by its centre.
         Centring meant half the word extended past the gutter and was sliced
         off by the field's overflow:hidden — which is what produced stray
         part-words like "ing" hanging off the left edge. */
      if (x < 50) { el.style.left = x + "%"; el.style.right = "auto"; }
      else { el.style.right = (100 - x) + "%"; el.style.left = "auto"; }
      el.style.top = y + "%";
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
    if (it.type === "materialization") { renderMaterialization(newSceneFresh(), it); return; }
    if (it.type === "workspace") { renderWorkspace(newSceneFresh(), it); return; }
    render(it);
  }

  /* ---------------- rendering ---------------- */

  /* ---- chapter closings: four different grammars, one scroll ritual ---- */

  function sectionBeat(sec) {
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
    return block;
  }

  function sectionFragments(sec) {
    /* Chapter 2: earlier answers return visually, then organize */
    const block = document.createElement("div");
    block.className = "dx-close-sec dx-close-frags";
    (sec.items || []).forEach((f, i) => {
      const s = document.createElement("span");
      s.className = "dx-cfrag";
      s.style.transitionDelay = (i * 380) + "ms";
      s.textContent = f;
      block.appendChild(s);
    });
    return block;
  }

  function sectionEvidence(sec) {
    /* Chapter 3: professional context as structured evidence */
    const block = document.createElement("div");
    block.className = "dx-close-sec dx-close-evidence";
    if (sec.heading) {
      const h = document.createElement("p");
      h.className = "cs-label";
      h.textContent = sec.heading;
      block.appendChild(h);
    }
    (sec.rows || []).forEach(r => {
      const row = document.createElement("div");
      row.className = "dx-ev-row";
      row.innerHTML = `<span class="dx-ev-label"></span><span class="dx-ev-value"></span>`;
      row.querySelector(".dx-ev-label").textContent = r.label;
      row.querySelector(".dx-ev-value").textContent = String(r.value).replace(/_/g, " ");
      block.appendChild(row);
    });
    return block;
  }

  function sectionMirror(sec) {
    /* Chapter 4: the user first — the converging mirror */
    const block = document.createElement("div");
    block.className = "dx-close-sec dx-close-mirror";
    (sec.items || []).forEach(m => {
      const item = document.createElement("div");
      item.className = "dx-mirror-item";
      item.innerHTML = `<p class="cs-label"></p><p class="dx-mirror-text"></p>`;
      item.querySelector(".cs-label").textContent = m.label;
      item.querySelector(".dx-mirror-text").textContent = m.text;
      block.appendChild(item);
    });
    return block;
  }

  function sectionSurprise(sec) {
    const block = document.createElement("div");
    block.className = "dx-close-sec dx-close-surprise";
    block.innerHTML = `<p class="cs-label"></p><p class="cs-text dx-surprise-text"></p>`;
    block.querySelector(".cs-label").textContent = sec.heading || "";
    block.querySelector(".dx-surprise-text").textContent = sec.text || "";
    return block;
  }

  function sectionResonance(sec) {
    const block = document.createElement("div");
    block.className = "dx-close-sec dx-resonance";
    const h = document.createElement("p");
    h.className = "cs-label dx-res-heading";
    h.textContent = sec.heading;
    block.appendChild(h);
    if (sec.empty) {
      const t = document.createElement("p");
      t.className = "cs-text dx-res-empty";
      t.textContent = sec.text;
      block.appendChild(t);
      return block;
    }
    (sec.matches || []).forEach(m => {
      const card = document.createElement("div");
      card.className = "dx-res-card";
      card.innerHTML = `
        <div class="dx-res-top"><span class="dx-res-name"></span><span class="dx-res-strength"></span></div>
        <p class="dx-res-overlap"></p>
        <div class="dx-res-cols">
          <div><p class="dx-res-col-label">Your evidence</p><ul class="dx-res-yours"></ul></div>
          <div><p class="dx-res-col-label">What we actually know</p><p class="dx-res-theirs"></p><p class="dx-res-source"></p></div>
        </div>
        <div class="dx-res-feedback">
          <button data-v="see_it">I see it</button>
          <button data-v="not_sure">Not sure</button>
          <button data-v="not_relevant">Doesn't feel relevant</button>
        </div>`;
      card.querySelector(".dx-res-name").textContent = m.figure;
      card.querySelector(".dx-res-strength").textContent = m.strength;
      card.querySelector(".dx-res-overlap").textContent = "The overlap: " + m.overlap;
      const yours = card.querySelector(".dx-res-yours");
      (m.yourEvidence || []).forEach(e => {
        const li = document.createElement("li");
        li.textContent = e;
        yours.appendChild(li);
      });
      card.querySelector(".dx-res-theirs").textContent = m.theirEvidence;
      const src = m.source || {};
      card.querySelector(".dx-res-source").textContent =
        src.title ? `Source: ${src.title}${src.publisher ? " — " + src.publisher : ""}` : "";
      card.querySelectorAll(".dx-res-feedback button").forEach(b => {
        b.addEventListener("click", async () => {
          card.querySelectorAll(".dx-res-feedback button").forEach(x => x.disabled = true);
          b.classList.add("chosen");
          try {
            await api(`/sessions/${sessionId}/resonance/feedback`,
              { figureId: m.figureId, patternId: m.patternId, verdict: b.dataset.v });
          } catch (e) { /* feedback is best-effort */ }
        }, { once: true });
      });
      block.appendChild(card);
    });
    if (sec.disclaimer) {
      const d = document.createElement("p");
      d.className = "dx-res-disclaimer";
      d.textContent = sec.disclaimer;
      block.appendChild(d);
    }
    return block;
  }

  function sectionQuote(sec) {
    /* editorial, not an inspirational poster: the user's evidence explains
       why this appeared, and the source is inspectable */
    const block = document.createElement("div");
    block.className = "dx-close-sec dx-quote";
    block.innerHTML = `
      <p class="cs-label">${esc(sec.heading)}</p>
      <blockquote class="dx-quote-text">${esc(sec.text)}</blockquote>
      <p class="dx-quote-attr">— ${esc(sec.person)}<span class="dx-quote-desc">${
        sec.descriptor ? ", " + esc(sec.descriptor) : ""}</span></p>
      <button class="dx-source-toggle" aria-expanded="false">Source</button>
      <div class="dx-source-detail" hidden>
        <p>${esc(sec.source?.title || "")}${sec.source?.publisher ? " · " + esc(sec.source.publisher) : ""}${
          sec.source?.year ? " · " + esc(sec.source.year) : ""}</p>
        ${sec.context ? `<p class="dx-quote-context">${esc(sec.context)}</p>` : ""}
        ${sec.source?.url ? `<p><a href="${esc(sec.source.url)}" target="_blank" rel="noopener">Open source</a></p>` : ""}
      </div>
      <p class="dx-quote-why">${esc(sec.whyHere)}</p>
      ${sec.disclaimer ? `<p class="dx-quote-note">${esc(sec.disclaimer)}</p>` : ""}`;
    const toggle = block.querySelector(".dx-source-toggle");
    const detail = block.querySelector(".dx-source-detail");
    toggle.addEventListener("click", () => {
      const open = detail.hasAttribute("hidden");
      detail.toggleAttribute("hidden", !open);
      toggle.setAttribute("aria-expanded", String(open));
    });
    return block;
  }

  function sectionSamePrinciple(sec) {
    /* two people, deliberately from different worlds, one shared principle */
    const block = document.createElement("div");
    block.className = "dx-close-sec dx-principle";
    const people = (sec.people || []).map(p => `
      <div class="dx-principle-person">
        <p class="dx-pp-name">${esc(p.name)}</p>
        <p class="dx-pp-field">${esc(p.field)}${p.descriptor ? " · " + esc(p.descriptor) : ""}</p>
        <blockquote class="dx-pp-quote">${esc(p.text)}</blockquote>
        <p class="dx-pp-source">${esc(p.source?.title || "")}${p.source?.year ? ", " + esc(p.source.year) : ""}</p>
      </div>`).join("");
    block.innerHTML = `
      <p class="cs-label">${esc(sec.heading)}</p>
      <p class="dx-principle-theme">${esc((sec.theme || "").replace(/_/g, " "))}</p>
      <div class="dx-principle-grid">${people}</div>
      <p class="dx-principle-overlap">${esc(sec.overlap)}</p>
      <p class="dx-quote-note">${esc(sec.honesty)}</p>
      <p class="dx-quote-why">${esc(sec.whyHere)}</p>`;
    return block;
  }

  const SECTION_BUILDERS = {
    beat: sectionBeat, thread: sectionBeat,
    fragments: sectionFragments, evidence: sectionEvidence,
    mirror: sectionMirror, surprise: sectionSurprise, resonance: sectionResonance,
    quote: sectionQuote, same_principle: sectionSamePrinciple,
  };

  function renderChapterClosing(scene, it) {
    stage.classList.add("dx-scroll");
    scene.classList.add("dx-closingpage");
    if (it.layout) scene.classList.add("dx-layout-" + it.layout);
    (it.beats || it.sections || []).forEach(sec => {
      const builder = SECTION_BUILDERS[sec.kind] || sectionBeat;
      scene.appendChild(builder(sec));
    });
    const btn = document.createElement("button");
    btn.className = "dx-commit ready dx-close-cta";
    btn.textContent = it.cta || "Continue →";
    scene.appendChild(btn);
    /* scroll reveals; content never disappears; only the click advances */
    const io = new IntersectionObserver(entries => {
      entries.forEach(e => { if (e.isIntersecting) e.target.classList.add("in"); });
    }, { threshold: 0.35 });
    scene.querySelectorAll(".dx-close-sec, .dx-close-cta, .dx-res-card").forEach(el => io.observe(el));
    btn.addEventListener("click", async () => {
      const data = await commitAdvance(btn, () => api(`/sessions/${sessionId}/advance`, { to: it.next }));
      if (!data) return;                       // failed: the retry stays on screen
      io.disconnect();
      stage.classList.remove("dx-scroll");
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

  /* Offer help when the person has actually stalled — not when a clock ran out.
     The old version armed a fixed timer the moment a question appeared, so it
     interrupted people who were still reading the question, dragging a slider,
     or halfway through typing a sentence. Now the countdown restarts on any
     real activity, and only genuine stillness reaches the end of it. */
  const IDLE_MS = { micro_reflection: 90000, forced_rank: 75000, object_sort: 75000, default: 60000 };

  /* "Busy" means working on the answer — dragging the slider, typing in the
     field, picking through the options. It does not mean the mouse moved.
     Watching the whole page meant idle drift, a stray scroll or a hand resting
     on the mouse kept resetting the countdown, so the offer of help never
     arrived for anyone who was actually sitting there thinking. Listeners are
     therefore scoped to the answer controls, and to events that only happen
     when someone is using them. */
  const ANSWER_CONTROLS =
    ".dx-slider, .dx-track, .dx-handle, .dx-input, .dx-input-wrap, .dx-opt, " +
    ".dx-chip, .dx-options, .dx-chips, .dx-commit, .dx-keep, .dx-pill";
  const ACTIVITY = ["pointerdown", "pointerup", "keydown", "input", "touchstart"];
  let assistTeardown = null;

  function armAssist(it) {
    disarmAssist();
    helpUsed = false;
    if (["reveal", "possible_lives", "final", "workspace"].includes(it.type)) return;
    const wait = IDLE_MS[it.type] || IDLE_MS.default;
    let lastActive = Date.now();
    const bump = () => { lastActive = Date.now(); };
    /* only when the event actually lands on something you answer with */
    const onControl = e => {
      const t = e.target;
      if (t && t.closest && t.closest(ANSWER_CONTROLS)) bump();
    };
    /* a drag in progress keeps the slider alive even between pointerdown and
       pointerup, which can easily exceed the idle window on its own */
    const onDrag = e => {
      if (e.buttons > 0 || e.pressure > 0) bump();
    };
    const tick = () => {
      /* a backgrounded tab is someone who left, not someone who is stuck —
         waiting there would just have the prompt sitting stale on return */
      if (document.hidden) { bump(); return; }
      if (Date.now() - lastActive >= wait) { disarmAssist(); showAssist(it); }
    };
    ACTIVITY.forEach(e => root.addEventListener(e, onControl, { passive: true, capture: true }));
    root.addEventListener("pointermove", onDrag, { passive: true, capture: true });
    document.addEventListener("visibilitychange", bump);
    assistTimer = setInterval(tick, 1000);
    assistTeardown = () => {
      ACTIVITY.forEach(e => root.removeEventListener(e, onControl, { capture: true }));
      root.removeEventListener("pointermove", onDrag, { capture: true });
      document.removeEventListener("visibilitychange", bump);
    };
  }

  function disarmAssist() {
    if (assistTimer) { clearInterval(assistTimer); assistTimer = null; }
    if (assistTeardown) { assistTeardown(); assistTeardown = null; }
  }

  function showAssist(it) {
    if (!stage.firstElementChild || root.querySelector(".dx-assist")) return;
    const bar = document.createElement("div");
    bar.className = "dx-assist";
    bar.innerHTML = `<span>Taking a minute? Need some help?</span>`;
    const helpBtn = document.createElement("button");
    helpBtn.textContent = "Show me what this means";
    /* No skip. Skipping a hard question produces the worst kind of evidence —
       an answer given to make a prompt go away — and the question is hard
       because the choice is close, which is exactly the useful part. */
    helpBtn.addEventListener("click", async () => {
      helpUsed = true;
      helpBtn.disabled = true;
      helpBtn.textContent = "One moment…";
      let help;
      try {
        help = await api(`/sessions/${sessionId}/interactions/${it.id}/help`, {});
      } catch (e) {
        help = null;
      }
      bar.remove();
      showHelpScene(help);
    });
    bar.appendChild(helpBtn);
    root.appendChild(bar);
    requestAnimationFrame(() => bar.classList.add("in"));
  }

  /* The help is a scene, not a hint: somewhere ordinary the choice actually
     happens, and what each side costs once you're standing in it. */
  function showHelpScene(help) {
    const scene = stage.firstElementChild;
    if (!scene || scene.querySelector(".dx-help")) return;
    const box = document.createElement("div");
    box.className = "dx-help";
    if (!help || !help.moment) {
      box.innerHTML = `<p class="dx-help-close">Say it the way you'd say it out loud. The first version is usually the honest one.</p>`;
    } else {
      const rows = (help.options || []).map(o =>
        `<div class="dx-help-opt"><span class="dx-help-opt-label">${esc(o.label)}</span>
           <span class="dx-help-opt-means">${esc(o.means)}</span></div>`).join("");
      box.innerHTML = `
        <p class="dx-help-label">Say you're here</p>
        <p class="dx-help-moment">${esc(help.moment)}</p>
        ${rows ? `<div class="dx-help-opts">${rows}</div>` : ""}
        <p class="dx-help-close">${esc(help.close || "")}</p>`;
    }
    const anchor = scene.querySelector(".dx-support") || scene.querySelector(".dx-headline");
    if (anchor) anchor.after(box); else scene.prepend(box);
    requestAnimationFrame(() => box.classList.add("in"));
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
      const data = await commitAdvance(btn,
        () => api(`/sessions/${sessionId}/advance`, { to: it.next || "MATERIALIZATION" }));
      if (data) handlePayload(data);
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
    /* The workspace is a list that routinely runs past the fold, and it was the
       one renderer that never enabled scrolling — the materialization CTA even
       removes dx-scroll on its way here, so it arrived pinned. */
    stage.classList.add("dx-scroll");
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
        /* These can take real time — the first action in a session runs the
           whole recommendation pipeline, and against a distant database that is
           tens of seconds. The click used to await it in silence with no error
           path, so a slow action and a broken one looked identical: nothing
           happened, and nothing ever would. */
        if (row.dataset.busy === "1") return;
        row.dataset.busy = "1";
        row.classList.add("loading");
        let detail = null;
        try {
          detail = await withBusy("Working that out…", () => wsApi("/actions/" + a.id));
        } catch (e) {
          detail = null;
        }
        row.dataset.busy = "";
        row.classList.remove("loading");
        if (detail) { showActionDetail(body, ws, detail); return; }
        const failed = document.createElement("p");
        failed.className = "ws-action-failed";
        failed.textContent = "That didn't load. Tap again to retry.";
        row.after(failed);
        setTimeout(() => failed.remove(), 5000);
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

    if (d.kind === "live_map") {
      const sub = document.createElement("p");
      sub.className = "dx-support";
      sub.textContent = d.supportingText || "";
      wrap.appendChild(sub);
      if (d.changeSummary) {
        const chg = document.createElement("p");
        chg.className = "dx-change-note";
        chg.textContent = d.changeSummary;
        wrap.appendChild(chg);
      }
      if (d.evidenceNote) {
        const note = document.createElement("p");
        note.className = "dx-evidence-note";
        note.textContent = d.evidenceNote;
        wrap.appendChild(note);
      }
      const fresh = document.createElement("p");
      fresh.className = "dx-freshness";
      const sigs = Object.entries((d.marketFreshness || {}).signals || {})
        .map(([k, v]) => `${k.replace(/_/g, " ")}: ${v.label}`).join(" · ");
      fresh.textContent = `Market evidence — ${(d.marketFreshness || {}).state || "unknown"}${sigs ? " · " + sigs : ""}`;
      wrap.appendChild(fresh);
      d = { ...d, kind: "map" };   /* reuse the explainable card grammar below */
    }
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
            ${l.whyNow ? `<dt>Why now</dt><dd>${esc(l.whyNow)}</dd>` : ""}
            ${l.friction ? `<dt>The honest friction</dt><dd>${esc(l.friction)}</dd>` : ""}
            <dt>Why this, honestly</dt><dd>${why}</dd>
            <dt>Missing pieces</dt><dd>${esc(l.requires)}</dd>
            <dt>First experiment</dt><dd>${esc(l.firstExperiment)}</dd>
          </dl>
          <div class="meta"><span>risk · ${esc(l.risk)}</span><span>${esc(l.timeToValue)}</span><span>${esc(l.confidenceLabel || ("confidence " + String(l.confidence) + "%"))}</span>${l.evidenceFreshness ? `<span>${esc(l.evidenceFreshness)}</span>` : ""}</div>
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
      if ((d.possibilities || []).length) {
        const more = document.createElement("div");
        more.className = "ws-possibilities";
        more.innerHTML = `<p class="ws-poss-head">Everything else we can rank</p>
          <p class="ws-poss-note">${esc(d.rankedBy || "")}</p>`;
        d.possibilities.forEach((x, i) => {
          const r = document.createElement("div");
          r.className = "ws-poss";
          const demandKnown = x.demand && x.demand.status === "known";
          r.innerHTML = `
            <span class="ws-poss-n">${i + 1}</span>
            <div class="ws-poss-main">
              <p class="ws-poss-name">${esc(x.label)} <span class="ws-poss-path">${esc(x.pathway || "")}</span></p>
              <p class="ws-poss-ai">${esc(x.ai ? x.ai.reading : "")}</p>
              ${(x.youAlreadyHave || []).length
                ? `<p class="ws-poss-have">You already have: ${esc(x.youAlreadyHave.join(", "))}</p>` : ""}
            </div>
            <div class="ws-poss-meta">
              <span class="ws-poss-fit">${esc(x.fitLabel || "")}</span>
              <span class="ws-poss-demand ${demandKnown ? "known" : "unknown"}">${
                esc(demandKnown ? x.demand.label : "demand unknown")}</span>
              ${x.licensed ? `<span class="ws-poss-lic">licence needed</span>` : ""}
            </div>`;
          more.appendChild(r);
        });
        if (d.honesty) {
          const h = document.createElement("p");
          h.className = "ws-poss-honesty";
          h.textContent = d.honesty;
          more.appendChild(h);
        }
        wrap.appendChild(more);
      }
    } else if (d.kind === "plan") {
      /* a week you could actually approve: what you do, what it settles, what
         kills it, and what tools change about doing it now */
      const pl = d.plan || {};
      const box = document.createElement("div");
      box.className = "ws-plan";
      const line = (k, v) => v ? `<div class="ws-plan-row"><span class="ws-plan-k">${esc(k)}</span>
          <span class="ws-plan-v">${esc(v)}</span></div>` : "";
      box.innerHTML =
        `<p class="ws-plan-do">${esc(pl.whatYouDo || "")}</p>` +
        line("What it settles", pl.proves) +
        line("What would kill it", pl.rulesOut) +
        line("What AI changes", pl.aiAngle) +
        line("Done looks like", pl.successLooks) +
        line("If it works", pl.ifItWorks) +
        line("If it doesn't", pl.ifItDoesnt) +
        line("What it costs", pl.cost) +
        ((pl.missing || []).length
          ? line("Still missing", pl.missing.join(", ")) : "");
      wrap.appendChild(box);
    } else if (d.kind === "list") {
      const ul = document.createElement("div");
      ul.className = "ws-list";
      /* several list actions now carry a subject; without it the reader sees a
         set of statements with nothing saying what they are about */
      if (d.title) {
        const t = document.createElement("p");
        t.className = "ws-list-title";
        t.textContent = d.title;
        ul.appendChild(t);
      }
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
        case "clarification": renderScenario(scene, it); break;
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

  function leaveScene(opts) {
    const { keepMemory = false } = opts || {};
    return new Promise(resolve => {
      const scene = stage.firstElementChild;
      if (!scene) return resolve();
      scene.classList.add("leaving");
      setTimeout(() => {
        /* keepMemory: the answer stays on screen while the backend works, so
           processing has context instead of a blank page */
        if (!keepMemory) stage.innerHTML = "";
        resolve();
      }, 520);
    });
  }

  function clearStage() {
    stage.innerHTML = "";
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
      case "clarification": return renderScenario(scene, it);
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
        setTimeout(() => respond(it.id, { optionId: o.id }, card), 420);
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
        setTimeout(() => respond(it.id, { optionId: o.id }, b), 380);
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
    commit.addEventListener("click", () => respond(it.id, { value }, commit));
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
    commit.addEventListener("click", () => respond(it.id, { optionIds: [...held] }, commit));
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
    input.addEventListener("keydown", e => { if (e.key === "Enter" && input.value.trim().length > 2) respond(it.id, { text: input.value.trim() }, commit); });
    commit.addEventListener("click", () => respond(it.id, { text: input.value.trim() }, commit));
    skip.addEventListener("click", () => respond(it.id, { skipped: true }, skip));
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
        setTimeout(() => respond(it.id, { optionId: c.id }, b), 350);
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
      /* a row is only worth its label if it carries content — an "n/a" printed
         under a heading reads as a broken form, not as honesty */
      const row_ = (dt, v) => v ? `<dt>${dt}</dt><dd>${esc(v)}</dd>` : "";
      const meta = [l.risk ? "risk · " + esc(l.risk) : "", l.timeToValue ? esc(l.timeToValue) : ""]
        .filter(Boolean).map(x => `<span>${x}</span>`).join("");
      card.innerHTML = `
        <h3>${esc(l.name)}</h3>
        <p class="ess">${esc(l.essence)}</p>
        <dl>
          ${row_("Why you", l.whyYou)}
          ${row_("Why now", l.whyNow)}
          ${row_("It would use", l.uses)}
          ${row_("It would require", l.requires)}
          ${row_("The honest friction", l.friction)}
        </dl>
        ${meta ? `<div class="meta">${meta}</div>` : ""}`;
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
        setTimeout(() => respond(it.id, { optionId: o.id }, b), 500);
      });
      pills.appendChild(b);
    });
    scene.appendChild(pills);
  }

  /* ---- Final Mirror: scroll-paced, evidence beats, no prescription ---- */

  function renderFinal(scene, it) {
    stage.classList.add("dx-scroll");
    scene.classList.add("dx-final", "dx-finalpage");

    const mirror = document.createElement("div");
    mirror.className = "dx-mirror";
    (it.beats || it.mirror || []).forEach(m => {
      const item = document.createElement("div");
      item.className = "dx-mirror-item dx-close-sec";
      item.innerHTML = `<p class="lbl">${esc(m.label)}</p><p class="txt">${esc(m.text)}</p>`;
      mirror.appendChild(item);
    });
    scene.appendChild(mirror);

    const closing = document.createElement("div");
    closing.className = "dx-final-closing";
    (it.closing || []).forEach(line => {
      const p = document.createElement("p");
      p.className = "dx-close-sec cs-text";
      p.textContent = line;
      closing.appendChild(p);
    });
    scene.appendChild(closing);

    const done = document.createElement("button");
    done.className = "dx-commit ready dx-close-cta";
    done.textContent = it.cta || "See what this can become →";
    scene.appendChild(done);

    const io = new IntersectionObserver(entries => {
      entries.forEach(e => { if (e.isIntersecting) e.target.classList.add("in"); });
    }, { threshold: 0.3 });
    scene.querySelectorAll(".dx-close-sec, .dx-close-cta").forEach(el => io.observe(el));
    done.addEventListener("click", () => {
      io.disconnect();
      stage.classList.remove("dx-scroll");
      respond(it.id, { done: true }, done);
    }, { once: true });
  }

  /* ---- Materialization: the story becomes objects you can act on ---- */

  async function objectStatus(kind, key, status, reason) {
    try {
      return await api(`/sessions/${sessionId}/objects/status`, { kind, key, status, reason });
    } catch (e) { return null; }
  }

  function matSection(title, note) {
    const s = document.createElement("section");
    s.className = "dx-mat-sec dx-close-sec";
    s.innerHTML = `<h3 class="dx-mat-h">${esc(title)}</h3>` +
      (note ? `<p class="dx-mat-note">${esc(note)}</p>` : "");
    return s;
  }

  /* The operator probe: one question at a time, in a modal, each answer
     re-routing the surfaces immediately so the questions visibly do work. */
  function openProbe(step, readOut, paintSurfaces, cta) {
    const back = document.createElement("div");
    back.className = "dx-probe-back";
    const box = document.createElement("div");
    box.className = "dx-probe";
    back.appendChild(box);
    document.body.appendChild(back);

    const close = () => { back.remove(); };
    const paintStep = st => {
      box.innerHTML = `<p class="dx-probe-step">Question ${st.stepIndex}</p>
        <h3 class="dx-probe-q">${esc(st.question)}</h3>`;
      const opts = document.createElement("div");
      opts.className = "dx-probe-opts";
      st.options.forEach(o => {
        const b = document.createElement("button");
        b.className = "dx-pill";
        b.textContent = o.label;
        b.addEventListener("click", async () => {
          b.classList.add("picked");
          opts.querySelectorAll("button").forEach(x => { x.disabled = true; });
          let res;
          try {
            res = await api(`/sessions/${sessionId}/venture/probe`,
                            { stepId: st.id, optionId: o.id });
          } catch (e) {
            box.innerHTML = `<p class="dx-probe-q">That didn't save. You can close this and keep going — nothing is lost.</p>`;
            return;
          }
          if (res.read) readOut.textContent = res.read;
          paintSurfaces(res.surfaces);
          if (res.next) paintStep(res.next);
          else {
            box.innerHTML = `<h3 class="dx-probe-q">That's enough to work with.</h3>
              <p class="dx-probe-done">${esc(res.read || "")}</p>`;
            const d = document.createElement("button");
            d.className = "dx-pill";
            d.textContent = "See what fits →";
            d.addEventListener("click", close);
            box.appendChild(d);
            if (cta) { cta.textContent = "Answered"; cta.classList.add("picked"); }
          }
        });
        opts.appendChild(b);
      });
      box.appendChild(opts);
      const skip = document.createElement("button");
      skip.className = "dx-pill dx-pill-quiet";
      skip.textContent = "Not now";
      skip.addEventListener("click", close);
      box.appendChild(skip);
    };
    paintStep(step);
    back.addEventListener("click", e => { if (e.target === back) close(); });
  }

  /* The follow-up, a few seconds after the page settles.

     It waits deliberately: arriving with the page would read as a form to fill
     in before you are allowed to see anything, and the point is that the audit
     is already yours. Which question appears is decided by the model from the
     assessed situation — a founder is asked about their company, someone
     employed about whether they want out, someone between roles about what they
     can commit — so there is no branch here to keep in sync. */
  let probeTimer = null;

  function scheduleProbe(it) {
    clearTimeout(probeTimer);
    if (!it.situationProbe) return;
    probeTimer = setTimeout(() => openProbeModal(it.situationProbe),
                            typeof it.probeDelayMs === "number" ? it.probeDelayMs : 3000);
  }

  function openProbeModal(q) {
    if (!q || document.querySelector(".dx-probe-back")) return;
    const back = document.createElement("div");
    back.className = "dx-probe-back";
    const box = document.createElement("div");
    box.className = "dx-probe dx-situation";
    back.appendChild(box);
    document.body.appendChild(back);
    const close = () => back.remove();

    const paint = step => {
      box.innerHTML = `<p class="dx-probe-step">One thing before you go on</p>
        <h3 class="dx-probe-q">${esc(step.question)}</h3>
        ${step.why ? `<p class="dx-probe-why">${esc(step.why)}</p>` : ""}`;
      const opts = document.createElement("div");
      opts.className = "dx-probe-opts";
      (step.options || []).forEach(o => {
        const b = document.createElement("button");
        b.className = "dx-pill";
        b.textContent = o.label;
        b.addEventListener("click", async () => {
          b.classList.add("picked");
          opts.querySelectorAll("button").forEach(x => { x.disabled = true; });
          let res;
          try {
            res = await api(`/sessions/${sessionId}/situation`,
                            { key: step.key, optionId: o.id, label: o.label,
                              question: step.question });
          } catch (e) {
            box.innerHTML = `<p class="dx-probe-q">That didn't save — you can close this and carry on.</p>`;
            return;
          }
          if (res && res.next) paint(res.next);
          else {
            box.innerHTML = `<h3 class="dx-probe-q">Noted.</h3>
              <p class="dx-probe-done">That sharpens what we can say next.</p>`;
            const d = document.createElement("button");
            d.className = "dx-pill";
            d.textContent = "Back to the page";
            d.addEventListener("click", close);
            box.appendChild(d);
          }
        });
        opts.appendChild(b);
      });
      box.appendChild(opts);
      const later = document.createElement("button");
      later.className = "dx-pill dx-pill-quiet";
      later.textContent = "Not now";
      later.addEventListener("click", close);
      box.appendChild(later);
    };
    paint(q);
    back.addEventListener("click", e => { if (e.target === back) close(); });
  }

  function renderMaterialization(scene, it) {
    stage.classList.add("dx-scroll");
    scene.classList.add("dx-matpage");
    scheduleProbe(it);

    /* One masthead, not five stacked screens. The opener and the intro were
       saying the same thing four different ways, each line occupying a full
       viewport, so the actual findings began several scrolls down. */
    const head = document.createElement("header");
    head.className = "dx-close-sec dx-mat-masthead";
    head.innerHTML = `
      <p class="dx-mat-eyebrow">What this is worth</p>
      <h2 class="dx-mat-claim">You don't need another personality result.
        <strong>You need to know what this is worth.</strong></h2>
      <p class="dx-mat-sub"></p>`;
    head.querySelector(".dx-mat-sub").textContent =
      (it.intro || []).join(" ") || "Here's what four chapters actually produced.";
    scene.appendChild(head);

    /* Panels sit side by side instead of end to end: the page is a summary to
       take in, not a document to read through. */
    const cols = document.createElement("div");
    cols.className = "dx-mat-columns";
    scene.appendChild(cols);
    const place = sec => cols.appendChild(sec);

    /* YOUR PICTURE */
    const pos = it.position || {};
    if ((pos.context || []).length || (pos.evidence || []).length) {
      const s = matSection(pos.heading || "Where you stand");
      const rows = document.createElement("div");
      rows.className = "dx-mat-rows";
      [...(pos.context || []), ...(pos.evidence || [])].forEach(r => {
        const row = document.createElement("div");
        row.className = "dx-ev-row";
        row.innerHTML = `<span class="dx-ev-label"></span><span class="dx-ev-value"></span>`;
        row.querySelector(".dx-ev-label").textContent = r.label;
        row.querySelector(".dx-ev-value").textContent = r.value;
        rows.appendChild(row);
      });
      s.appendChild(rows);
      if ((pos.unclear || []).length) {
        const u = document.createElement("p");
        u.className = "dx-mat-unclear";
        u.textContent = "Still unclear: " + pos.unclear.join(" · ");
        s.appendChild(u);
      }
      place(s);
    }

    /* CAPABILITIES */
    if ((it.capabilities || []).length) {
      const s = matSection("What you can actually do", "Each one, and what in your answers backs it up.");
      const grid = document.createElement("div");
      grid.className = "dx-mat-grid";
      it.capabilities.forEach(c => {
        const card = document.createElement("div");
        card.className = "dx-mat-card";
        card.innerHTML = `
          <div class="dx-mat-top"><span class="dx-mat-name">${esc(c.label)}</span>
            <span class="dx-mat-strength">${esc(c.strength)}</span></div>
          ${(c.supportedBy || []).length
              ? `<p class="dx-mat-support">from ${esc(c.supportedBy.join(", "))}</p>` : ""}`;
        grid.appendChild(card);
      });
      s.appendChild(grid);
      place(s);
    }

    /* YOUR LEVERAGE */
    if ((it.leverage || []).length) {
      const s = matSection("What you already have", "You're not starting from nothing.");
      const grid = document.createElement("div");
      grid.className = "dx-mat-grid";
      it.leverage.forEach(l => {
        const card = document.createElement("div");
        card.className = "dx-mat-card dx-mat-lev";
        card.innerHTML = `
          <div class="dx-mat-top"><span class="dx-mat-name">${esc(l.label)}</span></div>
          <p class="dx-mat-support">${esc(l.note)}</p>
          <p class="dx-mat-basis">${esc(l.basis)}</p>`;
        grid.appendChild(card);
      });
      s.appendChild(grid);
      place(s);
    }

    /* WHAT IS STILL MISSING */
    if ((it.gaps || []).length) {
      const s = matSection("What we still don't know", "Not things you're bad at — things we haven't asked yet.");
      const list = document.createElement("div");
      list.className = "dx-mat-gaps";
      it.gaps.forEach(g => {
        const row = document.createElement("div");
        row.className = "dx-mat-gap";
        row.innerHTML = `<p class="dx-gap-label">${esc(g.label)}</p>
          <p class="dx-gap-why">${esc(g.why)}</p>`;
        list.appendChild(row);
      });
      s.appendChild(list);
      place(s);
    }

    /* DIRECTIONS + their experiments — withheld on this page. Chapter IV is the
       audit; recommending roles here was the page trying to conclude something
       it has not earned. They remain available where someone asks for them, in
       the workspace's Explore action. */
    if (it.showDirections !== false && (it.directions || []).length) {
      const s = matSection("Worth a look",
                           "Not predictions. Each one shows why it came up and the cheapest way to check it.");
      const row = document.createElement("div");
      row.className = "dx-lives dx-mat-directions";
      it.directions.forEach(d => {
        const card = document.createElement("div");
        card.className = "dx-life";
        card.dataset.key = d.key;
        const have = (d.whatYouHave || []).join(", ");
        const missing = (d.missing || []).join(", ");
        card.innerHTML = `
          <h3>${esc(d.label)}</h3>
          <dl>
            <dt>Why this appeared</dt><dd>${esc(d.whyThisAppeared)}</dd>
            ${have ? `<dt>What you already have</dt><dd>${esc(have)}</dd>` : ""}
            ${missing ? `<dt>What's missing</dt><dd>${esc(missing)}</dd>` : ""}
            <dt>What makes it realistic</dt><dd>${esc(d.whatMakesItRealistic)}</dd>
            <dt>What makes it risky</dt><dd>${esc(d.whatMakesItRisky)}</dd>
            <dt>Market evidence</dt><dd>${esc(d.marketEvidence)}</dd>
            <dt>Cheapest way to test it</dt><dd>${esc(d.experiment?.action || "")}<br>
              <span class="dx-teaches">Tells you ${esc(d.experiment?.teaches || "")} · ${esc(d.experiment?.effort || "")}</span></dd>
          </dl>
          <div class="meta"><span>${esc(d.confidenceLabel)}</span>${
            typeof d.evidenceFreshness === "number" ? `<span>evidence ${esc(String(d.evidenceFreshness))}d old</span>` : ""}</div>
          <div class="ws-life-acts">
            <button class="dx-pill" data-act="save">Save</button>
            <button class="dx-pill" data-act="test">Test this</button>
            <button class="dx-pill dx-pill-quiet" data-act="dismiss">Not for me</button>
          </div>`;
        card.querySelector('[data-act="save"]').addEventListener("click", async e => {
          e.target.classList.add("picked"); e.target.textContent = "Saved";
          await objectStatus("direction", d.key, "saved");
        });
        card.querySelector('[data-act="test"]').addEventListener("click", async e => {
          e.target.classList.add("picked"); e.target.textContent = "Testing";
          try { await api(`/sessions/${sessionId}/experiments/${encodeURIComponent(d.key)}/start`, {}); }
          catch (err) { /* best effort */ }
        });
        card.querySelector('[data-act="dismiss"]').addEventListener("click", async e => {
          card.classList.add("dismissed");
          await objectStatus("direction", d.key, "dismissed", "not relevant");
        });
        row.appendChild(card);
      });
      s.appendChild(row);
      scene.appendChild(s);
    }

    /* WHAT WE KNOW ABOUT YOUR FIELD — real numbers and named gaps, side by side.
       An unavailable insight is styled as clearly missing rather than quietly
       dropped: which half of the picture is absent is itself the finding. */
    const ins = it.insights;
    if (ins && (ins.insights || []).length) {
      const s2 = matSection(
        ins.field ? `Your field · ${ins.field}` : "What we know about your field",
        `${ins.supported} backed by data · ${ins.unavailable} we can't answer yet`);
      const list = document.createElement("div");
      list.className = "dx-ins-list";
      ins.insights.forEach(x => {
        const row = document.createElement("div");
        row.className = "dx-ins" + (x.status === "supported" ? " ok" : " missing");
        row.innerHTML = `
          <p class="dx-ins-head">${esc(x.headline)}</p>
          <p class="dx-ins-detail">${esc(x.detail)}</p>
          <p class="dx-ins-basis">${x.status === "supported" ? "" : "Needs: "}${esc(x.basis)}</p>`;
        list.appendChild(row);
      });
      s2.appendChild(list);
      place(s2);
    }
    /* the old inline job-or-build branch is gone: the follow-up is now one
       model-chosen question in a modal a few seconds after the page settles */
    if (false && it.directionQuestion) {
      const q = it.directionQuestion;
      const s3 = matSection("First, which question are you asking?");
      const p2 = document.createElement("p");
      p2.className = "dx-mat-note";
      p2.textContent = q.question;
      s3.appendChild(p2);
      const opts = document.createElement("div");
      opts.className = "dx-ins-opts";
      q.options.forEach(o => {
        const b = document.createElement("button");
        b.className = "dx-pill";
        b.textContent = o.label;
        b.addEventListener("click", async () => {
          b.classList.add("picked");
          opts.querySelectorAll("button").forEach(x => { x.disabled = true; });
          try {
            await api(`/sessions/${sessionId}/insights/direction`, { optionId: o.id });
            const fresh = await api(`/sessions/${sessionId}/materialization`, undefined, { method: "GET" });
            handlePayload(fresh);
          } catch (e) { b.textContent = "Didn't save — tap another"; }
        });
        opts.appendChild(b);
      });
      s3.appendChild(opts);
      place(s3);
    }

    /* OPERATOR: strengths, thin spots, and what the market evidence actually
       supports. Role directions are absent by design for this audience. */
    const v = it.venture;
    if (v) {
      if ((v.strengths || []).length) {
        const s = matSection(v.heading || "What you're actually strong at", v.supportingText);
        const grid = document.createElement("div");
        grid.className = "dx-mat-grid";
        v.strengths.forEach(c => {
          const card = document.createElement("div");
          card.className = "dx-mat-card";
          card.innerHTML = `
            <div class="dx-mat-top"><span class="dx-mat-name">${esc(c.label)}</span>
              <span class="dx-mat-strength">${esc(c.strength)}</span></div>
            <p class="dx-mat-support">${esc(c.inYourBusiness)}</p>`;
          grid.appendChild(card);
        });
        s.appendChild(grid);
        place(s);
      }
      if ((v.thinSpots || []).length) {
        const s = matSection("Where you're exposed",
                             "Not failings — things we haven't seen yet that change what you should do next.");
        const list = document.createElement("div");
        list.className = "dx-mat-gaps";
        v.thinSpots.forEach(t => {
          const row = document.createElement("div");
          row.className = "dx-mat-gap";
          row.innerHTML = `<p class="dx-gap-label">${esc(t.label)}</p>
            <p class="dx-gap-why">${esc(t.why)}</p>`;
          list.appendChild(row);
        });
        s.appendChild(list);
        place(s);
      }
      const m = v.market;
      if (m) {
        const s = matSection(m.heading, m.occupation ? `For ${m.occupation}.` : null);
        if (m.note) {
          const n = document.createElement("p");
          n.className = "dx-mkt-abstain";
          n.textContent = m.note;
          s.appendChild(n);
        }
        /* the numbers stay visible even when they are not strong enough to be
           stated as fact — hiding them would make the abstention unverifiable */
        (m.readings || []).forEach(r => {
          const row = document.createElement("div");
          row.className = "dx-mkt-row" + (r.usable ? " usable" : "");
          const prov = `${r.sourceCount} source${r.sourceCount === 1 ? "" : "s"}` +
            (r.freshnessDays !== null && r.freshnessDays !== undefined ? ` · ${r.freshnessDays}d old` : "");
          row.innerHTML = `
            <div class="dx-mkt-head"><span class="dx-mkt-label">${esc(r.label)}</span>
              <span class="dx-mkt-verdict">${esc(r.reading || "not enough evidence to say")}</span></div>
            <p class="dx-mkt-prov">${esc(prov)}${r.sources && r.sources.length ? " · " + esc(r.sources.join(", ")) : ""}</p>`;
          s.appendChild(row);
        });
        place(s);
      }
    }

    /* EXPLORE — the opt-in. Nothing is recommended until the person asks. */
    if (it.explore) {
      const s = document.createElement("section");
      s.className = "dx-mat-sec dx-close-sec dx-explore";
      s.innerHTML = `<p class="dx-explore-note">${esc(it.explore.note || "")}</p>`;
      const surfaces = document.createElement("div");
      surfaces.className = "dx-surfaces";
      const readOut = document.createElement("p");
      readOut.className = "dx-explore-read";

      const paintSurfaces = list => {
        surfaces.innerHTML = "";
        (list || []).forEach(x => {
          const card = document.createElement("div");
          card.className = "dx-surface";
          card.innerHTML = `
            <div class="dx-surface-top"><span class="dx-surface-name">${esc(x.name)}</span>
              <span class="dx-surface-soon">coming soon</span></div>
            <p class="dx-surface-line">${esc(x.line)}</p>
            <p class="dx-surface-detail">${esc(x.detail)}</p>
            <p class="dx-surface-why">${esc(x.because)}</p>`;
          surfaces.appendChild(card);
        });
      };

      const btn = document.createElement("button");
      btn.className = "dx-pill dx-explore-cta";
      btn.textContent = it.explore.cta || "Explore something interesting for you →";
      s.appendChild(btn);
      s.appendChild(readOut);
      s.appendChild(surfaces);
      scene.appendChild(s);

      if (it.explore.read) readOut.textContent = it.explore.read;
      paintSurfaces(it.explore.surfaces);

      btn.addEventListener("click", () => {
        if (it.explore.next) openProbe(it.explore.next, readOut, paintSurfaces, btn);
        else { btn.classList.add("picked"); btn.textContent = "Answered"; }
      });
      if (!it.explore.next) { btn.textContent = "Answered"; btn.classList.add("picked"); }
    }

    /* PRODUCT ROUTES — also withheld here for the same reason */
    (it.showProductRoutes === false ? [] : (it.productRoutes || [])).forEach(r => {
      const s = document.createElement("section");
      s.className = "dx-mat-sec dx-close-sec dx-route";
      s.innerHTML = `
        <p class="dx-route-because">${esc(r.because)}</p>
        <p class="dx-route-gap">${esc(r.gap)}</p>
        <p class="dx-route-help">${esc(r.help)}</p>
        <p class="dx-route-optional">${esc(r.optional)}</p>`;
      const b = document.createElement("button");
      b.className = "dx-pill";
      b.textContent = "Show me how →";
      b.addEventListener("click", async () => {
        b.classList.add("picked");
        try { await api(`/sessions/${sessionId}/product-routes/${r.id}/accept`, {}); }
        catch (e) { /* best effort */ }
      });
      s.appendChild(b);
      scene.appendChild(s);
    });

    const cta = document.createElement("button");
    cta.className = "dx-commit ready dx-close-cta";
    cta.textContent = it.cta || "Enter your Discover space →";
    scene.appendChild(cta);

    const io = new IntersectionObserver(entries => {
      entries.forEach(e => { if (e.isIntersecting) e.target.classList.add("in"); });
    }, { threshold: 0.2 });
    scene.querySelectorAll(".dx-close-sec, .dx-life").forEach(el => io.observe(el));
    cta.addEventListener("click", async () => {
      const data = await commitAdvance(cta,
        () => api(`/sessions/${sessionId}/advance`, { to: it.next || "DISCOVER_WORKSPACE" }));
      if (!data) return;
      io.disconnect();
      stage.classList.remove("dx-scroll");
      handlePayload(data);
    });
  }

  function esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  window.UnbifyDiscover = { open, close };
  window.UnbifyBusy = { on: busyOn, off: busyOff, wrap: withBusy,
                        active: () => busyDepth > 0 };
})();
