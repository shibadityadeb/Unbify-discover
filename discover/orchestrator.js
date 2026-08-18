/* Experience Orchestrator.
   SESSION STATE -> what do we need next? -> safe primitive -> AI content
   -> validate -> render contract -> response -> signal engine -> state.
   The AI directs content and tone; this module owns pacing, safety,
   chapter objectives, evidence thresholds and repetition limits. */

import { randomUUID } from "node:crypto";
import { DIMENSIONS, CHAPTER_FOCUS } from "./dimensions.js";
import { applyEvidence, topDims, thinnestDims, totalEvidence } from "./signals.js";
import {
  FALLBACK_INTERACTIONS, composeReveal, composePossibleLives, composeFinal,
} from "./fallbacks.js";
import * as ai from "./ai.js";

const CHAPTERS = ["self_discovery", "reflection", "alignment", "transformation"];
const SIGNAL_TYPES = ["visual_choice", "binary_tension", "spectrum", "scenario_choice", "forced_rank", "object_sort"];
const HEAVY_TYPES = ["forced_rank", "object_sort", "micro_reflection"];

export function newState(sessionId) {
  return {
    sessionId: sessionId || randomUUID(),
    chapter: "self_discovery",
    chapterProgress: 0,
    interactionCount: 0,
    evidence: [],
    dimensions: {},
    contradictions: [],
    userCorrections: [],
    revealedInsights: [],
    recentInteractionTypes: [],
    practicalContext: {},
    possibleLives: null,
    engagementSignals: { startedAt: Date.now(), skippedCount: 0, responseTimes: [] },
    /* orchestration internals */
    sinceReveal: 0,
    revealsThisChapter: 0,
    reflectionsDone: 0,
    usedFallbacks: [],
    pending: null,
    finalPayload: null,
    finished: false,
  };
}

/* ---------------- next experience ---------------- */

export async function nextInteraction(state) {
  if (state.finished) return wrap(state, { type: "journey_complete" });

  const decision = decide(state);

  if (decision.kind === "chapter_transition") {
    state.chapter = decision.next;
    state.chapterProgress = 0;
    state.sinceReveal = 0;
    state.revealsThisChapter = 0;
    return wrap(state, { type: "chapter_transition", next: decision.next });
  }

  if (decision.kind === "reveal") {
    const reveal = await makeReveal(state, decision.revealKind);
    state.pending = { id: randomUUID(), type: "reveal", insight: reveal.insight };
    state.sinceReveal = 0;
    state.revealsThisChapter += 1;
    if (reveal.insight?.contradiction) {
      const c = state.contradictions.find(x => x.dim === reveal.insight.contradiction);
      if (c) c.explored = true;
    }
    return wrap(state, {
      id: state.pending.id, type: "reveal",
      lines: reveal.lines,
      calibration: decision.revealKind === "contradiction"
        ? [{ id: "first", label: "The first, mostly" }, { id: "second", label: "The second, mostly" }, { id: "depends", label: "Depends on the situation" }]
        : [{ id: "yes", label: "Feels like me" }, { id: "kind_of", label: "Kind of" }, { id: "no", label: "Not really" }],
    });
  }

  if (decision.kind === "possible_lives") {
    const lives = await makeLives(state);
    state.possibleLives = lives;
    state.pending = { id: randomUUID(), type: "possible_lives" };
    return wrap(state, {
      id: state.pending.id, type: "possible_lives",
      headline: "Three lives you could actually live.",
      supportingText: "Not predictions. Possibilities — read them slowly.",
      lives: lives.map(publicLife),
      ask: "Which one pulls at you?",
      options: [...lives.map(l => ({ id: l.key, label: l.name })), { id: "none", label: "None of them, fully" }],
    });
  }

  if (decision.kind === "final") {
    const finalPayload = state.finalPayload || await makeFinal(state);
    state.finalPayload = finalPayload;
    state.pending = { id: randomUUID(), type: "final" };
    return wrap(state, { id: state.pending.id, type: "final", ...finalPayload, map: (state.possibleLives || []).map(publicLife) });
  }

  /* signal-gathering interaction */
  const interaction = await makeSignalInteraction(state, decision);
  const id = randomUUID();
  state.pending = {
    id, type: interaction.type,
    optionSignals: Object.fromEntries((interaction.options || []).map(o => [o.id, o.signals || []])),
    poles: interaction.left ? { left: interaction.left, right: interaction.right } : null,
    practicalKey: interaction.practicalKey || null,
    prompt: interaction.headline,
    maxSelect: interaction.maxSelect || null,
  };
  return wrap(state, publicInteraction(id, interaction));
}

function decide(state) {
  const ch = state.chapter;
  const evid = totalEvidence(state);

  if (ch === "self_discovery") {
    if (state.revealsThisChapter >= 1 && evid >= 8 && state.sinceReveal >= 2) {
      return { kind: "chapter_transition", next: "reflection" };
    }
    if (state.sinceReveal >= 3 && evid >= 5 && state.revealsThisChapter < 1) {
      return { kind: "reveal", revealKind: "early" };
    }
    if (state.sinceReveal >= 4 && state.revealsThisChapter >= 1) {
      return { kind: "reveal", revealKind: "pattern" };
    }
    return { kind: "signal" };
  }

  if (ch === "reflection") {
    const unexplored = state.contradictions.find(c => !c.explored);
    if (state.revealsThisChapter >= 2 && state.reflectionsDone >= 1 && state.sinceReveal >= 1) {
      return { kind: "chapter_transition", next: "alignment" };
    }
    if (unexplored && state.sinceReveal >= 1) {
      return { kind: "reveal", revealKind: "contradiction" };
    }
    if (state.sinceReveal >= 2 && state.revealsThisChapter < 2) {
      return { kind: "reveal", revealKind: "pattern" };
    }
    if (state.reflectionsDone < 2 && !HEAVY_TYPES.includes(lastType(state)) && state.interactionCount % 2 === 1) {
      return { kind: "signal", forceType: "micro_reflection" };
    }
    return { kind: "signal" };
  }

  if (ch === "alignment") {
    const practicalKeys = Object.keys(state.practicalContext).filter(k => k !== "notes" && k !== "resonantLife");
    if (state.possibleLives && state.practicalContext.resonantLife !== undefined) {
      return { kind: "chapter_transition", next: "transformation" };
    }
    if (practicalKeys.length >= 5 && !state.possibleLives) {
      return { kind: "possible_lives" };
    }
    return { kind: "signal", practical: true };
  }

  /* transformation */
  return { kind: "final" };
}

/* ---------------- content creation (AI first, fallback always) ---------------- */

async function makeSignalInteraction(state, decision) {
  const focus = CHAPTER_FOCUS[state.chapter];
  const targetDims = thinnestDims(state, focus, 4);
  const recent = state.recentInteractionTypes.slice(-3);
  let allowed = decision.forceType ? [decision.forceType]
    : SIGNAL_TYPES.filter(t => !(recent[recent.length - 1] === t && recent[recent.length - 2] === t));
  /* cognitive-load guard: after heavy moments, go instinctive */
  if (!decision.forceType && HEAVY_TYPES.includes(lastType(state))) {
    allowed = allowed.filter(t => !HEAVY_TYPES.includes(t));
  }
  if (ai.aiAvailable()) {
    try {
      const it = await ai.generateInteraction(state, {
        allowedTypes: allowed,
        targetDims,
        validDims: Object.keys(DIMENSIONS),
        avoid: state.revealedInsights.slice(-3).map(i => i.summary),
        note: decision.practical
          ? "Alignment chapter: also gently gather real-world context (work, time, money pressure, risk, assets, geography) — conversational, never form-like."
          : undefined,
      });
      /* practical tagging for alignment */
      if (decision.practical) it.practicalKey = it.practicalKey || `ctx_${state.interactionCount}`;
      return it;
    } catch { /* fall through */ }
  }
  return pickFallback(state, decision, allowed);
}

function pickFallback(state, decision, allowed) {
  const pool = FALLBACK_INTERACTIONS.filter(f =>
    f.chapters.includes(state.chapter) &&
    !state.usedFallbacks.includes(f.id) &&
    (decision.practical ? f.practicalKey : !f.practicalKey || state.chapter !== "alignment") &&
    (decision.forceType ? f.type === decision.forceType : allowed.includes(f.type))
  );
  let pick = pool[0];
  if (!pick) {
    /* relax: any unused for chapter, then any at all */
    pick = FALLBACK_INTERACTIONS.find(f => f.chapters.includes(state.chapter) && !state.usedFallbacks.includes(f.id))
      || FALLBACK_INTERACTIONS.find(f => f.chapters.includes(state.chapter));
  }
  state.usedFallbacks.push(pick.id);
  return { ...pick };
}

async function makeReveal(state, kind) {
  if (ai.aiAvailable()) {
    try { return await ai.generateReveal(state, kind); } catch { /* fall through */ }
  }
  return composeReveal(state, kind);
}

async function makeLives(state) {
  if (ai.aiAvailable()) {
    try { return await ai.generatePossibleLives(state); } catch { /* fall through */ }
  }
  return composePossibleLives(state);
}

async function makeFinal(state) {
  if (ai.aiAvailable()) {
    try { return await ai.generateFinal(state); } catch { /* fall through */ }
  }
  return composeFinal(state);
}

/* ---------------- responses ---------------- */

export async function applyResponse(state, interactionId, response, elapsedMs) {
  const p = state.pending;
  if (!p || p.id !== interactionId) return { ok: false, error: "stale interaction" };
  state.pending = null;
  state.interactionCount += 1;
  state.recentInteractionTypes.push(p.type);
  if (state.recentInteractionTypes.length > 10) state.recentInteractionTypes.shift();
  if (elapsedMs) {
    state.engagementSignals.responseTimes.push(Math.min(60000, elapsedMs));
    if (state.engagementSignals.responseTimes.length > 30) state.engagementSignals.responseTimes.shift();
  }
  if (response?.skipped) {
    state.engagementSignals.skippedCount += 1;
    state.sinceReveal += 1;
    return { ok: true };
  }

  switch (p.type) {
    case "visual_choice":
    case "scenario_choice": {
      const sig = p.optionSignals[response.optionId];
      if (sig) applyEvidence(state, sig, p.type);
      if (p.practicalKey) state.practicalContext[p.practicalKey] = response.optionId;
      state.sinceReveal += 1;
      break;
    }
    case "binary_tension":
    case "spectrum": {
      const v = Math.max(-1, Math.min(1, Number(response.value) || 0));
      if (p.poles) {
        const ev = [];
        const ldir = p.poles.left.dir ?? 1, rdir = p.poles.right.dir ?? 1;
        if (p.poles.left.dim) ev.push({ dim: p.poles.left.dim, delta: -v * ldir, weight: 0.55 * Math.abs(v) + 0.1 });
        if (p.poles.right.dim && p.poles.right.dim !== p.poles.left.dim) {
          ev.push({ dim: p.poles.right.dim, delta: v * rdir, weight: 0.55 * Math.abs(v) + 0.1 });
        }
        applyEvidence(state, ev, p.type);
      }
      if (p.practicalKey) state.practicalContext[p.practicalKey] = Number(Number(response.value).toFixed(2));
      state.sinceReveal += 1;
      break;
    }
    case "forced_rank":
    case "object_sort": {
      const chosen = Array.isArray(response.optionIds) ? response.optionIds.slice(0, p.maxSelect || 4) : [];
      for (const id of chosen) {
        const sig = p.optionSignals[id];
        if (sig) applyEvidence(state, sig, p.type);
      }
      /* releasing an item is mild counter-evidence */
      for (const [id, sig] of Object.entries(p.optionSignals)) {
        if (!chosen.includes(id)) {
          applyEvidence(state, sig.map(s => ({ ...s, delta: -s.delta * 0.35, weight: Math.min(0.25, s.weight * 0.5) })), `${p.type}_released`);
        }
      }
      if (p.practicalKey) state.practicalContext[p.practicalKey] = chosen;
      state.sinceReveal += 1;
      break;
    }
    case "micro_reflection": {
      const text = String(response.text || "").slice(0, 300);
      state.reflectionsDone += 1;
      if (text.trim()) {
        state.practicalContext.notes = [...(state.practicalContext.notes || []), { prompt: p.prompt, text }].slice(-6);
        if (ai.aiAvailable()) {
          try {
            const ex = await ai.extractReflectionSignals(state, p.prompt, text);
            if (ex.signals.length) applyEvidence(state, ex.signals, "micro_reflection");
          } catch { /* keep the note; skip signals */ }
        }
      }
      state.sinceReveal += 1;
      break;
    }
    case "reveal": {
      const insight = p.insight || { dims: [] };
      const answer = response.optionId;
      state.revealedInsights.push({ summary: insight.summary, answer, at: Date.now() });
      const dims = insight.dims || [];
      if (answer === "yes" || answer === "first") {
        applyEvidence(state, dims.map(d => ({ dim: d.dim, delta: 0.5 * d.dir, weight: 1.0 })), "calibration_agree");
      } else if (answer === "kind_of" || answer === "depends") {
        applyEvidence(state, dims.map(d => ({ dim: d.dim, delta: 0.2 * d.dir, weight: 0.35 })), "calibration_partial");
      } else if (answer === "no" || answer === "second") {
        state.userCorrections.push({ insight: insight.summary, at: Date.now() });
        applyEvidence(state, dims.map(d => ({ dim: d.dim, delta: -0.6 * d.dir, weight: 1.4 })), "calibration_correction");
      }
      break;
    }
    case "possible_lives": {
      state.practicalContext.resonantLife = response.optionId === "none" ? null : response.optionId;
      if (response.optionId && response.optionId !== "none") {
        applyEvidence(state, [{ dim: "initiative", delta: 0.2, weight: 0.2 }], "life_resonance");
      }
      break;
    }
    case "final": {
      state.finished = true;
      break;
    }
  }
  state.chapterProgress = chapterProgress(state);
  return { ok: true };
}

/* ---------------- helpers ---------------- */

function lastType(state) { return state.recentInteractionTypes[state.recentInteractionTypes.length - 1]; }

function chapterProgress(state) {
  const i = CHAPTERS.indexOf(state.chapter);
  const inChapter = state.chapter === "alignment"
    ? Math.min(1, Object.keys(state.practicalContext).length / 6)
    : Math.min(1, (state.revealsThisChapter * 2 + state.sinceReveal) / 6);
  return Math.min(0.98, (i + inChapter) / CHAPTERS.length);
}

function publicLife(l) {
  return {
    key: l.key, name: l.name, essence: l.essence,
    whyYou: l.whyYou, whyNow: l.whyNow, uses: l.uses,
    requires: l.requires, friction: l.friction,
    risk: l.risk, timeToValue: l.timeToValue,
    firstExperiment: l.firstExperiment, confidence: l.confidence,
  };
}

/* strip hidden signals before sending to the browser */
function publicInteraction(id, it) {
  const pub = { id, type: it.type, headline: it.headline, supportingText: it.supportingText ?? null };
  if (it.options) pub.options = it.options.map(o => ({ id: o.id, label: o.label, motif: o.motif }));
  if (it.left) { pub.left = { label: it.left.label }; pub.right = { label: it.right.label }; }
  if (it.maxSelect) pub.maxSelect = it.maxSelect;
  if (it.minSelect) pub.minSelect = it.minSelect;
  if (it.placeholder) pub.placeholder = it.placeholder;
  return pub;
}

function wrap(state, interaction) {
  return { interaction, chapter: state.chapter, estimatedProgress: chapterProgress(state) };
}
