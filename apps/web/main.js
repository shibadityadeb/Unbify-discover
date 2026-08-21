/* UNBIFY Discover — orbital life, parallax, transition */
(function () {
  "use strict";

  /* ---------- destinations ----------
     Set a URL to make a hotspot navigate there; leave null for the
     built-in behavior (placeholder scene / gentle response). */
  const LINKS = {
    menu: null,     // e.g. "menu.html"  — hamburger hotspot on the chapter art
    map: null,      // e.g. "journey-map.html" — dark map-icon hotspot
    scene01: null,  // e.g. "self-discovery.html" — Self Discovery title + cue + scroll
    reflection01: null, // e.g. "reflection.html" — Chapter II title + cue + scroll
    alignment01: null,  // e.g. "alignment.html" — Chapter III title + cue + scroll
    transformation01: null, // e.g. "transformation.html" — Chapter IV title + cue + scroll
  };

  /* ---------- particles along orbital paths ---------- */
  const particleHost = document.querySelector(".particles");
  const PARTICLES = [
    { a0: 30,  rf: .958, dur: 84,  rev: false, s: 3,   c: "#e0954f", tw: 4.2, twd: 0 },
    { a0: 140, rf: .958, dur: 84,  rev: false, s: 2.4, c: "#d8b978", tw: 5.4, twd: 1.2 },
    { a0: 250, rf: .905, dur: 70,  rev: true,  s: 2.6, c: "#e2a35e", tw: 3.4, twd: .6 },
    { a0: 75,  rf: .843, dur: 64,  rev: true,  s: 3,   c: "#d9b070", tw: 6,   twd: 2 },
    { a0: 195, rf: .843, dur: 64,  rev: true,  s: 2.2, c: "#e0954f", tw: 4.8, twd: 3.1 },
    { a0: 320, rf: .78,  dur: 55,  rev: false, s: 2.6, c: "#dcae66", tw: 3.8, twd: 1.7 },
    { a0: 10,  rf: .707, dur: 46,  rev: false, s: 2.2, c: "#e2a35e", tw: 5.2, twd: .3 },
    { a0: 160, rf: .653, dur: 46,  rev: false, s: 2.4, c: "#d8b978", tw: 4.4, twd: 2.6 },
    { a0: 285, rf: .582, dur: 120, rev: true,  s: 2,   c: "#dcae66", tw: 5.8, twd: 1 },
  ];
  PARTICLES.forEach(p => {
    const carrier = document.createElement("div");
    carrier.className = "p-carrier";
    carrier.style.setProperty("--a0", p.a0 + "deg");
    const spin = document.createElement("div");
    spin.className = "p-spin" + (p.rev ? " rev" : "");
    spin.style.setProperty("--dur", p.dur + "s");
    const dot = document.createElement("span");
    dot.className = "p-dot";
    dot.style.setProperty("--rf", p.rf);
    dot.style.setProperty("--s", p.s + "px");
    dot.style.setProperty("--c", p.c);
    dot.style.setProperty("--tw", p.tw + "s");
    dot.style.setProperty("--twd", p.twd + "s");
    spin.appendChild(dot);
    carrier.appendChild(spin);
    particleHost.appendChild(carrier);
  });

  /* ---------- connector: active chapter -> orange node ---------- */
  const connector = document.querySelector(".connector");
  const activeLi = document.querySelector(".chapters li.active");
  const activeNode = document.getElementById("activeNode");
  function layoutConnector() {
    if (!connector || !activeLi || !activeNode) return;
    if (getComputedStyle(connector).display === "none") return;
    const a = activeLi.getBoundingClientRect();
    const n = activeNode.getBoundingClientRect();
    const x1 = a.right + 18;
    const y1 = a.top + a.height * 0.42;
    const x2 = n.left + n.width / 2 - 10;
    const y2 = n.top + n.height / 2;
    const dx = x2 - x1, dy = y2 - y1;
    connector.style.left = x1 + "px";
    connector.style.top = y1 + "px";
    connector.style.width = Math.hypot(dx, dy) + "px";
    connector.style.transform = "rotate(" + Math.atan2(dy, dx) + "rad)";
    connector.style.transformOrigin = "0 50%";
  }
  layoutConnector();
  window.addEventListener("resize", layoutConnector);
  setTimeout(layoutConnector, 600);

  /* ---------- parallax ---------- */
  /* intro layers */
  const introPlx = [
    { el: document.querySelector(".landscape"), f: 3.5 },
    { el: document.querySelector(".orbit-anchor"), f: -4 },
    { el: document.querySelector(".hero"), f: -1.5 },
    { el: document.querySelector(".haze-a"), f: 1.5 },
    { el: document.querySelector(".haze-b"), f: 1 },
    { el: document.querySelector(".chapters"), f: 1.2 },
    { el: document.querySelector(".quote"), f: 1.2 },
  ].filter(x => x.el);
  /* chapter layers — portrait almost still, inner landscape deeper, bg opposite */
  const innerLand = document.querySelector(".innerLand");
  const chPlx = [
    { el: document.getElementById("chPortrait"), f: 1.4 },
    { el: document.querySelector(".ch-bg-right"), f: -2 },
    { el: document.querySelector(".ch-bg-left"), f: -2 },
    { el: document.querySelector(".ch-birds"), f: 2.4 },
  ].filter(x => x.el);

  let tx = 0, ty = 0, cx = 0, cy = 0;
  let departed = false;
  let transitioning = false;
  window.addEventListener("pointermove", e => {
    tx = (e.clientX / window.innerWidth - 0.5) * 2;
    ty = (e.clientY / window.innerHeight - 0.5) * 2;
  });
  (function raf() {
    cx += (tx - cx) * 0.045;
    cy += (ty - cy) * 0.045;
    if (!departed) {
      introPlx.forEach(({ el, f }) => {
        el.style.translate = (cx * f) + "px " + (cy * f) + "px";
      });
    } else {
      chPlx.forEach(({ el, f }) => {
        el.style.translate = (cx * f) + "px " + (cy * f) + "px";
      });
      /* inner landscape drifts a little deeper than the portrait shell */
      if (innerLand) {
        /* CSS animation owns transform; use translate property offset via parent only */
      }
    }
    requestAnimationFrame(raf);
  })();

  /* ---------- CTA hover: nearby system quickens ---------- */
  const cta = document.getElementById("ctaBtn");
  cta.addEventListener("pointerenter", () => document.body.classList.add("cta-hover"));
  cta.addEventListener("pointerleave", () => document.body.classList.remove("cta-hover"));

  /* ---------- cinematic departure ---------- */
  let cueTimer = null;
  cta.addEventListener("click", () => {
    if (departed || transitioning) return;
    departed = true;
    transitioning = true;
    window.scrollTo(0, 0);
    introPlx.forEach(({ el }) => { el.style.translate = "0px 0px"; });
    /* step 1: the system recognizes the decision */
    document.body.classList.add("pre-depart");
    setTimeout(() => {
      document.body.classList.remove("pre-depart");
      document.body.classList.add("depart");
    }, 480);
    /* step 3-5: light takes over, the circle becomes the person */
    setTimeout(() => {
      document.body.classList.add("arrived");
      cueTimer = setTimeout(() => document.body.classList.add("cue"), 2800);
    }, 1700);
    setTimeout(() => { transitioning = false; }, 3200);
  });


  /* ---------- pre-decode all chapter artwork (prevents first-reveal stall) ---------- */
  ["chArtImg", "ch2Img", "ch3Img", "ch4Img"].forEach(id => {
    const im = document.getElementById(id);
    if (!im) return;
    im.decoding = "async";
    const warm = () => { if (im.decode) im.decode().catch(() => {}); };
    if (im.complete) warm(); else im.addEventListener("load", warm);
  });

  /* ---------- exact-artwork mode ---------- */
  const artImg = document.getElementById("chArtImg");
  const artFrame = document.getElementById("artFrame");
  function sizeArtFrame() {
    if (!document.body.classList.contains("art-mode")) return;
    const W = artImg.naturalWidth, H = artImg.naturalHeight;
    if (!W || !H) return;
    const vw = window.innerWidth, vh = window.innerHeight;
    const s = Math.max(vw / W, vh / H);
    const dw = W * s, dh = H * s;
    artFrame.style.width = dw + "px";
    artFrame.style.height = dh + "px";
    artFrame.style.left = (vw - dw) / 2 + "px";
    artFrame.style.top = (vh - dh) / 2 + "px";
  }
  if (artImg) {
    const enableArt = () => {
      document.body.classList.add("art-mode");
      sizeArtFrame();
    };
    if (artImg.complete && artImg.naturalWidth > 0) enableArt();
    else {
      artImg.addEventListener("load", enableArt);
      artImg.addEventListener("error", () => {
        /* no exact artwork on disk yet -> coded recreation stays active */
        console.info("UNBIFY: assets/chapter-self-discovery.png not found; using coded recreation.");
      });
    }
    window.addEventListener("resize", sizeArtFrame);
  }

  /* Chapter entry runs an animation and then a network call. The unlock used to
     be a fixed timer, so on a slow link it released while the request was still
     in flight, and on a fast one it held the page long after the content had
     arrived. Either way a scroll in that window did nothing and looked broken.
     openChapter ties the lock to the work and shows the blocking wait. */
  function openChapter(name, onUnavailable, release) {
    const busy = window.UnbifyBusy;
    if (busy) busy.on("Opening the next chapter…");
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      if (busy) busy.off();
      release();
    };
    try {
      const p = window.UnbifyDiscover.open(name, onUnavailable);
      if (p && typeof p.then === "function") p.then(finish, finish);
      else finish();
    } catch (e) {
      finish();
    }
    /* a hung request must never strand the page in a locked state */
    setTimeout(finish, 20000);
  }

  /* enter Self Discovery — zoom, focus the walking figure, wash to Scene 01 */
  let entering = false;
  function enterScene() {
    if (entering || transitioning) return;
    entering = true; transitioning = true;
    /* quiet the scene, then follow the inner path */
    document.body.classList.add("enter-scene");
    if (LINKS.scene01) {
      setTimeout(() => { window.location.href = LINKS.scene01; }, 1400);
      return;
    }
    /* the artwork becomes the doorway — the Discover experience opens inside the light */
    setTimeout(() => {
      openChapter("self_discovery", () => {
        document.body.classList.add("ch2");
        clearTimeout(cue2Timer);
        cue2Timer = setTimeout(() => document.body.classList.add("cue2"), 3400);
      }, () => {
        document.body.classList.remove("enter-scene");
        entering = false; transitioning = false;
      });
    }, 1050);
  }
  const hsTitle = document.getElementById("hsTitle");
  if (hsTitle) hsTitle.addEventListener("click", enterScene);
  document.querySelectorAll(".hs-menu, .hs-map").forEach(hs => {
    hs.addEventListener("click", () => {
      const url = hs.classList.contains("hs-menu") ? LINKS.menu : LINKS.map;
      if (url) window.location.href = url;
    });
  });
  /* ---------- overlays: menu & journey map ---------- */
  const ovMenu = document.getElementById("ovMenu");
  const ovMap = document.getElementById("ovMap");
  function openOverlay(ov) { if (ov === ovMenu && typeof syncMenuState === "function") syncMenuState(); ov.classList.add("open"); ov.setAttribute("aria-hidden", "false"); }
  function closeOverlays() {
    [ovMenu, ovMap].forEach(ov => { ov.classList.remove("open"); ov.setAttribute("aria-hidden", "true"); });
  }
  function overlayOpen() { return ovMenu.classList.contains("open") || ovMap.classList.contains("open"); }

  document.querySelectorAll(".ch-nav-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const isMenu = btn.classList.contains("light");
      const url = isMenu ? LINKS.menu : LINKS.map;
      if (url) { window.location.href = url; return; }
      openOverlay(isMenu ? ovMenu : ovMap);
    });
  });
  /* intro round menu button opens the same menu */
  const introMenuBtn = document.querySelector(".menu-btn");
  if (introMenuBtn) introMenuBtn.addEventListener("click", () => {
    if (LINKS.menu) { window.location.href = LINKS.menu; return; }
    openOverlay(ovMenu);
  });

  document.querySelectorAll("[data-close]").forEach(b => b.addEventListener("click", closeOverlays));
  window.addEventListener("keydown", e => { if (e.key === "Escape") closeOverlays(); });
  [ovMenu, ovMap].forEach(ov => ov.addEventListener("click", e => { if (e.target === ov) closeOverlays(); }));

  document.querySelectorAll("[data-go]").forEach(b => {
    b.addEventListener("click", () => {
      const dest = b.getAttribute("data-go");
      closeOverlays();
      if (dest === "chapter") {
        leaveCh4(); leaveCh3(); leaveCh2();
        document.body.classList.remove("scene-open", "enter-scene");
        if (!document.body.classList.contains("arrived") && !departed) setTimeout(() => cta.click(), 350);
      } else if (dest === "chapter2") {
        leaveCh4(); leaveCh3();
        setTimeout(gotoCh2, 300);
      } else if (dest === "chapter3") {
        leaveCh4();
        setTimeout(gotoCh3, 300);
      } else if (dest === "chapter4") {
        setTimeout(gotoCh4, 300);
      } else if (dest === "intro") {
        leaveCh4(); leaveCh3(); leaveCh2();
        if (document.body.classList.contains("arrived")) setTimeout(() => document.getElementById("chBack").click(), 350);
      }
    });
  });
  /* menu highlights the chapter you are on */
  const menuItems = document.querySelectorAll(".ov-item[data-chapter]");
  function syncMenuState() {
    const b = document.body.classList;
    const current = b.contains("ch4") ? "4" : b.contains("ch3") ? "3" : b.contains("ch2") ? "2" : "1";
    menuItems.forEach(it => {
      it.classList.toggle("active", it.getAttribute("data-chapter") === current);
    });
  }
  const chCopy = document.querySelector(".ch-copy");
  if (chCopy) chCopy.addEventListener("click", e => {
    if (e.target.closest(".ch-title, .ch-marker, .ch-support, .ch-underline")) enterScene();
  });
  const s1Back = document.getElementById("s1Back");
  if (s1Back) s1Back.addEventListener("click", () => {
    document.body.classList.remove("scene-open");
  });

  /* ---------- continuation cue ---------- */
  document.getElementById("chCue").addEventListener("click", enterScene);

  /* ---------- Chapter II — Reflection ---------- */
  let cue2Timer = null;
  let enteringCh2 = false;
  function gotoCh2() {
    closeOverlays();
    document.body.classList.remove("scene-open", "enter-scene");
    document.body.classList.add("ch2");
    clearTimeout(cue2Timer);
    cue2Timer = setTimeout(() => document.body.classList.add("cue2"), 2800);
  }
  function leaveCh2() {
    clearTimeout(cue2Timer);
    document.body.classList.remove("ch2", "cue2", "enter-ch2", "scene2-open");
  }
  /* forward declaration used before definition below */
  function enterReflection() {
    if (enteringCh2 || transitioning) return;
    enteringCh2 = true; transitioning = true;
    if (LINKS.reflection01) {
      document.body.classList.add("enter-ch2");
      setTimeout(() => { window.location.href = LINKS.reflection01; }, 1400);
      return;
    }
    /* the hold: stillness earns its weight before moving */
    setTimeout(() => document.body.classList.add("enter-ch2"), 500);
    /* the Roman path becomes the doorway into Reflection */
    setTimeout(() => {
      openChapter("reflection", () => {
        document.body.classList.add("ch3");
        clearTimeout(cue3Timer);
        cue3Timer = setTimeout(() => document.body.classList.add("cue3"), 3400);
      }, () => {
        document.body.classList.remove("enter-ch2");
        enteringCh2 = false; transitioning = false;
      });
    }, 1600);
  }
  /* size halo + focus wash to the displayed (cover, right-anchored) image rect */
  const ch2Img = document.getElementById("ch2Img");
  function sizeCh2Rect() {
    if (!ch2Img) return;
    const W = 1672, Hn = 941;
    const vw = window.innerWidth, vh = window.innerHeight;
    const s = Math.max(vw / W, vh / Hn);
    const dw = W * s, dh = Hn * s;
    const left = vw - dw, top = (vh - dh) / 2;
    [document.querySelector(".fig-halo"), document.querySelector(".ch2-focus-wash")].forEach(el => {
      if (!el) return;
      el.style.left = left + "px"; el.style.top = top + "px";
      el.style.width = dw + "px"; el.style.height = dh + "px";
    });
  }
  sizeCh2Rect();
  window.addEventListener("resize", sizeCh2Rect);

  document.getElementById("ch2Cue").addEventListener("click", enterReflection);
  const ch2Copy = document.querySelector(".ch2-copy");
  if (ch2Copy) ch2Copy.addEventListener("click", e => {
    if (e.target.closest(".ch-title, .ch-marker, .ch-support, .ch-underline")) enterReflection();
  });
  document.getElementById("ch2Back").addEventListener("click", () => {
    leaveCh2();
    if (!document.body.classList.contains("arrived") && !departed) setTimeout(() => cta.click(), 300);
  });

  /* ---------- Chapter III — Alignment ---------- */
  let cue3Timer = null;
  let enteringCh3 = false;
  function gotoCh3() {
    closeOverlays();
    document.body.classList.remove("scene2-open", "enter-ch2");
    document.body.classList.add("ch2", "ch3");
    clearTimeout(cue3Timer);
    cue3Timer = setTimeout(() => document.body.classList.add("cue3"), 2800);
  }
  function leaveCh3() {
    clearTimeout(cue3Timer);
    document.body.classList.remove("ch3", "cue3", "enter-ch3", "scene3-open");
  }
  function enterAlignment() {
    if (enteringCh3 || transitioning) return;
    enteringCh3 = true; transitioning = true;
    /* the lines converge; light forms where they meet */
    document.body.classList.add("enter-ch3");
    if (LINKS.alignment01) {
      setTimeout(() => { window.location.href = LINKS.alignment01; }, 1400);
      return;
    }
    /* the river becomes the doorway into Alignment */
    setTimeout(() => {
      openChapter("alignment", () => {
        document.body.classList.add("ch4");
        clearTimeout(cue4Timer);
        cue4Timer = setTimeout(() => document.body.classList.add("cue4"), 3600);
      }, () => {
        document.body.classList.remove("enter-ch3");
        enteringCh3 = false; transitioning = false;
      });
    }, 1150);
  }
  const ch3Img = document.getElementById("ch3Img");
  function sizeCh3Rect() {
    if (!ch3Img) return;
    const W = 1672, Hn = 941;
    const vw = window.innerWidth, vh = window.innerHeight;
    const s = Math.max(vw / W, vh / Hn);
    const dw = W * s, dh = Hn * s;
    const left = vw - dw, top = (vh - dh) / 2;
    [document.querySelector(".ch3-glow"), document.querySelector(".ch3-focus-wash")].forEach(el => {
      if (!el) return;
      el.style.left = left + "px"; el.style.top = top + "px";
      el.style.width = dw + "px"; el.style.height = dh + "px";
    });
  }
  sizeCh3Rect();
  window.addEventListener("resize", sizeCh3Rect);
  document.getElementById("ch3Cue").addEventListener("click", enterAlignment);
  const ch3Copy = document.querySelector(".ch3-copy");
  if (ch3Copy) ch3Copy.addEventListener("click", e => {
    if (e.target.closest(".ch-title, .ch-marker, .ch-support, .ch-underline")) enterAlignment();
  });
  document.getElementById("ch3Back").addEventListener("click", () => {
    leaveCh3();
    gotoCh2();
  });

  /* ---------- Chapter IV — Transformation ---------- */
  let cue4Timer = null;
  let enteringCh4 = false;
  function gotoCh4() {
    closeOverlays();
    document.body.classList.remove("scene3-open", "enter-ch3");
    document.body.classList.add("ch2", "ch3", "ch4");
    clearTimeout(cue4Timer);
    cue4Timer = setTimeout(() => document.body.classList.add("cue4"), 3000);
  }
  function leaveCh4() {
    clearTimeout(cue4Timer);
    document.body.classList.remove("ch4", "cue4", "enter-ch4", "scene4-open");
  }
  function enterTransformation() {
    if (enteringCh4 || transitioning) return;
    enteringCh4 = true; transitioning = true;
    document.body.classList.add("enter-ch4");
    setTimeout(() => {
      if (LINKS.transformation01) { window.location.href = LINKS.transformation01; return; }
      openChapter("transformation", () => {
        document.body.classList.add("scene4-open");
      }, () => {
        document.body.classList.remove("enter-ch4");
        enteringCh4 = false; transitioning = false;
      });
    }, 2000);
  }
  const ch4Img = document.getElementById("ch4Img");
  function sizeCh4Rect() {
    if (!ch4Img) return;
    const W = 1672, Hn = 941;
    const vw = window.innerWidth, vh = window.innerHeight;
    const s = Math.max(vw / W, vh / Hn);
    const dw = W * s, dh = Hn * s;
    /* left-anchored cover: image pinned to the left edge */
    const top = (vh - dh) / 2;
    [document.getElementById("ch4Rect"), document.querySelector(".ch4-focus-wash")].forEach(el => {
      if (!el) return;
      el.style.left = "0px"; el.style.top = top + "px";
      el.style.width = dw + "px"; el.style.height = dh + "px";
    });
  }
  sizeCh4Rect();
  window.addEventListener("resize", sizeCh4Rect);
  document.getElementById("ch4Cue").addEventListener("click", enterTransformation);
  const ch4Copy = document.querySelector(".ch4-copy");
  if (ch4Copy) ch4Copy.addEventListener("click", e => {
    if (e.target.closest(".ch-title, .ch-marker, .ch-support, .ch-underline")) enterTransformation();
  });
  document.getElementById("ch4Back").addEventListener("click", () => {
    leaveCh4();
    gotoCh3();
  });
  document.getElementById("s4Back").addEventListener("click", () => {
    document.body.classList.remove("scene4-open", "enter-ch4");
  });

  /* ---------- Discover experience handoffs ---------- */
  window.addEventListener("discover:chapter", e => {
    const next = e.detail.next;
    if (next === "reflection") {
      document.body.classList.add("ch2");
      clearTimeout(cue2Timer);
      cue2Timer = setTimeout(() => document.body.classList.add("cue2"), 3400);
    } else if (next === "alignment") {
      document.body.classList.add("ch2", "ch3");
      clearTimeout(cue3Timer);
      cue3Timer = setTimeout(() => document.body.classList.add("cue3"), 3400);
    } else if (next === "transformation") {
      document.body.classList.add("ch2", "ch3", "ch4");
      clearTimeout(cue4Timer);
      cue4Timer = setTimeout(() => document.body.classList.add("cue4"), 3600);
    }
  });
  window.addEventListener("discover:complete", () => {
    document.body.classList.add("scene4-open");
  });

  /* ---------- scroll continues the journey ---------- */
  /* On phones the intro is a scrolling page (hero -> chapters -> what-this-is),
     so scroll gestures there must scroll, not advance. Once a chapter overlay
     is open the page is frozen again and the gesture resumes its meaning. */
  const stackedFlow = window.matchMedia("(max-width: 760px), (max-height: 480px)");
  let lastAdvance = 0;
  function advance() {
    const now = Date.now();
    if (now - lastAdvance < 1800) return;
    const b = document.body.classList;
    if (stackedFlow.matches && !departed) return;
    if (b.contains("scene4-open") || b.contains("dx-open") || transitioning || overlayOpen()) return;
    if (window.UnbifyBusy && window.UnbifyBusy.active()) return;   // a wait is already exclusive
    lastAdvance = now;
    if (b.contains("ch4")) {
      enterTransformation();
    } else if (b.contains("ch3")) {
      enterAlignment();
    } else if (b.contains("ch2")) {
      enterReflection();
    } else if (b.contains("arrived")) {
      enterScene();
    } else if (!departed) {
      cta.click();
    }
  }
  window.addEventListener("wheel", e => { if (e.deltaY > 24) advance(); }, { passive: true });
  let touchY = null;
  window.addEventListener("touchstart", e => { touchY = e.touches[0].clientY; }, { passive: true });
  window.addEventListener("touchend", e => {
    if (touchY !== null && touchY - e.changedTouches[0].clientY > 46) advance();
    touchY = null;
  }, { passive: true });
  window.addEventListener("keydown", e => {
    if (e.key === "ArrowDown" || e.key === "PageDown" || e.key === " ") advance();
  });
  const scrollHint = document.querySelector(".scroll-hint");
  if (scrollHint) scrollHint.addEventListener("click", advance);

  /* ---------- return ---------- */
  document.getElementById("chBack").addEventListener("click", () => {
    clearTimeout(cueTimer);
    document.body.classList.remove("arrived", "cue", "enter-scene", "scene-open");
    chPlx.forEach(({ el }) => { el.style.translate = "0px 0px"; });
    setTimeout(() => {
      document.body.classList.remove("depart");
      departed = false;
      layoutConnector();
    }, 900);
  });
})();
