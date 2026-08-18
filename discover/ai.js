/* AI Experience Director — server-side only. Talks to the OpenAI-compatible
   LiteLLM endpoint; the key never reaches the browser. Every output is
   validated against the interaction contract; any failure falls back to the
   curated library. */

import { isDim } from "./dimensions.js";
import { MOTIFS } from "./fallbacks.js";

const BASE_URL = "https://litellm.gtor.app/v1";
const MODEL = "gpt-5.6-luna";

let KEY = process.env.LITELLM_KEY || null;

/* tiny .env loader (no dependencies) */
import { readFileSync } from "node:fs";
try {
  if (!KEY) {
    const env = readFileSync(new URL("../.env", import.meta.url), "utf8");
    for (const line of env.split("\n")) {
      const m = line.match(/^LITELLM_KEY=(.+)$/);
      if (m) KEY = m[1].trim();
    }
  }
} catch { /* no .env — fallback mode */ }

/* circuit breaker: after consecutive upstream failures, rest before retrying
   so a broken model deployment never slows the experience down. */
let failStreak = 0;
let restUntil = 0;

export function aiAvailable() {
  return Boolean(KEY) && Date.now() >= restUntil;
}

function noteSuccess() { failStreak = 0; }
function noteFailure() {
  failStreak += 1;
  if (failStreak >= 2) {
    restUntil = Date.now() + 4 * 60 * 1000;
    console.warn("AI director resting for 4 min after repeated upstream failures — fallback library active.");
  }
}

async function chat(messages, { maxTokens = 700, effort = null, timeoutMs = 7000 } = {}) {
  if (!KEY) throw new Error("no key");
  const body = {
    model: MODEL,
    messages,
    response_format: { type: "json_object" },
    max_tokens: maxTokens,
  };
  if (effort) body.reasoning_effort = effort;
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    let res = await fetch(`${BASE_URL}/chat/completions`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${KEY}` },
      body: JSON.stringify(body),
      signal: ctrl.signal,
    });
    if (res.status === 400 && effort) {
      delete body.reasoning_effort;
      res = await fetch(`${BASE_URL}/chat/completions`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${KEY}` },
        body: JSON.stringify(body),
        signal: ctrl.signal,
      });
    }
    if (!res.ok) { noteFailure(); throw new Error(`llm ${res.status}`); }
    const data = await res.json();
    const text = data.choices?.[0]?.message?.content;
    if (!text) { noteFailure(); throw new Error("empty completion"); }
    noteSuccess();
    return JSON.parse(text);
  } catch (e) {
    if (e.name === "AbortError") noteFailure();
    throw e;
  } finally {
    clearTimeout(t);
  }
}

const DIRECTOR_IDENTITY = `You are the invisible experience intelligence behind UNBIFY Discover.
You are not chatting with the user. You are directing a self-discovery experience.
Your job is to choose the most useful, effortless and emotionally interesting next moment.
You never diagnose. You never assign destiny. You never flatter generically.
You never ask something merely because assessments usually ask it.
You infer cautiously. You seek patterns across evidence. You look for contradictions.
You give value back frequently. You keep interactions lightweight. You vary interaction styles.
You make the experience feel beautifully human rather than AI-generated.
UI copy is 2-12 words wherever possible. Options must feel equally respectable — never one obviously "better" answer.
Never use horoscope language. Never mention scores, dimensions, or that you are an AI.`;

/* compact state for the model — never the raw conversation */
export function compactState(state) {
  const dims = {};
  for (const [k, v] of Object.entries(state.dimensions)) {
    if (v.evidenceCount > 0) dims[k] = { s: Number(v.score.toFixed(2)), c: Number(v.confidence.toFixed(2)), n: v.evidenceCount };
  }
  return {
    chapter: state.chapter,
    interactions: state.interactionCount,
    dims,
    contradictions: state.contradictions.map(c => ({ dim: c.dim, explored: c.explored })),
    corrections: state.userCorrections.slice(-4),
    revealed: state.revealedInsights.slice(-4).map(i => i.summary),
    recentTypes: state.recentInteractionTypes.slice(-5),
    practical: state.practicalContext,
    reflectionsUsed: state.reflectionsDone || 0,
  };
}

export async function generateInteraction(state, need) {
  const sys = `${DIRECTOR_IDENTITY}

Return ONLY JSON matching:
{
  "interaction": {
    "type": one of ${JSON.stringify(need.allowedTypes)},
    "headline": string (<= 90 chars),
    "supportingText": string|null (<= 110 chars),
    // for visual_choice: "options": [3-5 of {id, label(<=42), motif(one of ${JSON.stringify(MOTIFS)}), signals:[{dim,delta,weight}]}]
    // for scenario_choice: "options": [3-5 of {id, label(<=60), signals:[...]}]
    // for binary_tension|spectrum: "left":{label(<=28),dim}, "right":{label(<=28),dim}
    // for forced_rank|object_sort: "maxSelect": 3-4, "options": [6-10 of {id,label(<=26),signals:[...]}]
    // for micro_reflection: "placeholder": string(<=40)
  },
  "intent": { "primaryDimensions": [dims], "reason": string }
}
signals: dim must be one of the profile dimensions provided; delta in [-1,1]; weight in [0.1,0.8].
One answer may carry several WEAK signals. Options must cover DIFFERENT dimensions, not restate one.
Never number questions. Never reference previous answers explicitly.`;
  const user = JSON.stringify({
    state: compactState(state),
    need: {
      allowedTypes: need.allowedTypes,
      targetDimensions: need.targetDims,
      avoidRepeating: need.avoid || [],
      note: need.note || "Reduce useful uncertainty about this person. Keep it effortless.",
    },
    validDimensions: need.validDims,
  });
  const out = await chat([{ role: "system", content: sys }, { role: "user", content: user }], { maxTokens: 800 });
  return validateInteraction(out.interaction, need.allowedTypes);
}

export function validateInteraction(it, allowedTypes) {
  if (!it || typeof it !== "object") throw new Error("no interaction");
  if (!allowedTypes.includes(it.type)) throw new Error("type not allowed");
  const clean = { type: it.type, headline: str(it.headline, 90), supportingText: it.supportingText ? str(it.supportingText, 120) : null };
  const cleanSignals = (arr) => (Array.isArray(arr) ? arr : [])
    .filter(s => isDim(s.dim))
    .slice(0, 4)
    .map(s => ({ dim: s.dim, delta: clampN(s.delta, -1, 1), weight: clampN(s.weight, 0.1, 0.8) }));
  if (["visual_choice", "scenario_choice", "forced_rank", "object_sort"].includes(it.type)) {
    if (!Array.isArray(it.options) || it.options.length < 3) throw new Error("options missing");
    const seen = new Set();
    clean.options = it.options.slice(0, 10).map((o, i) => {
      const id = String(o.id || `o${i}`).slice(0, 24);
      if (seen.has(id)) throw new Error("dup option id");
      seen.add(id);
      const opt = { id, label: str(o.label, 60), signals: cleanSignals(o.signals) };
      if (it.type === "visual_choice") opt.motif = MOTIFS.includes(o.motif) ? o.motif : MOTIFS[i % MOTIFS.length];
      return opt;
    });
    if (it.type === "visual_choice" && clean.options.length > 5) clean.options = clean.options.slice(0, 5);
    if (["forced_rank", "object_sort"].includes(it.type)) {
      clean.maxSelect = Math.max(2, Math.min(4, Number(it.maxSelect) || 3));
      if (clean.options.length < 6) throw new Error("rank needs 6+ options");
    }
  } else if (["binary_tension", "spectrum"].includes(it.type)) {
    if (!it.left?.label || !it.right?.label) throw new Error("poles missing");
    clean.left = { label: str(it.left.label, 30), dim: isDim(it.left.dim) ? it.left.dim : null };
    clean.right = { label: str(it.right.label, 30), dim: isDim(it.right.dim) ? it.right.dim : null };
    if (!clean.left.dim || !clean.right.dim) throw new Error("pole dims invalid");
  } else if (it.type === "micro_reflection") {
    clean.placeholder = str(it.placeholder || "One honest line…", 44);
  } else {
    throw new Error("unhandled type");
  }
  return clean;
}

export async function generateReveal(state, kind) {
  const sys = `${DIRECTOR_IDENTITY}

Compose a short reveal — an observation given back to the user. Return ONLY JSON:
{ "lines": [2-4 short strings, each its own beat, total <= 60 words],
  "insight": { "summary": string(<=80, internal), "dims": [{"dim": string, "dir": 1|-1}] } }
Quality bar — specific, evidence-based, slightly surprising, humble, correctable.
GOOD: "You keep choosing room to experiment — but not novelty for its own sake."
BAD: "You are a visionary who values freedom and creativity."
Reference actual patterns in the evidence. If exploring a contradiction, honor both sides as real.`;
  const user = JSON.stringify({ state: compactState(state), revealKind: kind });
  const out = await chat([{ role: "system", content: sys }, { role: "user", content: user }], { maxTokens: 500, effort: "high", timeoutMs: 20000 });
  if (!Array.isArray(out.lines) || out.lines.length < 2) throw new Error("bad reveal");
  return {
    lines: out.lines.slice(0, 4).map(l => str(l, 140)),
    insight: {
      summary: str(out.insight?.summary || out.lines[0], 90),
      dims: (out.insight?.dims || []).filter(d => isDim(d.dim)).slice(0, 3).map(d => ({ dim: d.dim, dir: d.dir === -1 ? -1 : 1 })),
    },
  };
}

export async function generatePossibleLives(state) {
  const sys = `${DIRECTOR_IDENTITY}

Generate exactly 3 Possible Lives — distinct, credible future directions grounded in THIS person's evidence and practical reality. Not job titles; forms of opportunity. Names should fit the person (archetypes like "The Builder" are allowed but personalize when evidence supports it). Avoid three near-identical directions. Return ONLY JSON:
{ "lives": [3 of {
  "key": short_id, "name": string(<=26), "essence": string(<=60),
  "whyYou": string(<=140), "whyNow": string(<=120), "uses": string(<=110),
  "requires": string(<=120), "friction": string(<=110),
  "risk": "low"|"medium"|"medium-high"|"high", "timeToValue": string(<=40),
  "firstExperiment": string(<=140), "confidence": 35-85 } ] }`;
  const user = JSON.stringify({ state: compactState(state) });
  const out = await chat([{ role: "system", content: sys }, { role: "user", content: user }], { maxTokens: 1400, effort: "high", timeoutMs: 25000 });
  if (!Array.isArray(out.lives) || out.lives.length !== 3) throw new Error("bad lives");
  return out.lives.map((l, i) => ({
    key: String(l.key || `life${i}`).slice(0, 20),
    name: str(l.name, 28), essence: str(l.essence, 64),
    whyYou: str(l.whyYou, 150), whyNow: str(l.whyNow, 130), uses: str(l.uses, 120),
    requires: str(l.requires, 130), friction: str(l.friction, 120),
    risk: ["low", "medium", "medium-high", "high"].includes(l.risk) ? l.risk : "medium",
    timeToValue: str(l.timeToValue, 44), firstExperiment: str(l.firstExperiment, 150),
    confidence: Math.max(35, Math.min(85, Number(l.confidence) || 55)),
  }));
}

export async function generateFinal(state) {
  const sys = `${DIRECTOR_IDENTITY}

Compose the final Transformation synthesis. Warm human language, no clinical terms, no scores. Connect earlier moments (including any contradiction) into one coherent picture. Return ONLY JSON:
{ "opening": [3-4 short lines connecting the journey],
  "mirror": [5-7 of {"label": one of ["Your natural energy","How you create value","What you protect","Your unusual edge","Your current reality","What may be holding you back","Where your leverage may be"], "text": string(<=170)}],
  "nextAction": {"headline": string(<=40), "text": string(<=150), "note": string(<=70)} }
The nextAction must be genuinely small and doable this week.`;
  const user = JSON.stringify({ state: compactState(state), possibleLives: state.possibleLives, resonantLife: state.practicalContext?.resonantLife || null });
  const out = await chat([{ role: "system", content: sys }, { role: "user", content: user }], { maxTokens: 1200, effort: "high", timeoutMs: 25000 });
  if (!Array.isArray(out.mirror) || out.mirror.length < 4) throw new Error("bad final");
  return {
    opening: (out.opening || []).slice(0, 4).map(l => str(l, 110)),
    mirror: out.mirror.slice(0, 7).map(m => ({ label: str(m.label, 44), text: str(m.text, 180) })),
    nextAction: {
      headline: str(out.nextAction?.headline || "One small next step", 44),
      text: str(out.nextAction?.text || "", 160),
      note: str(out.nextAction?.note || "Not a life plan. Just the next honest experiment.", 80),
    },
  };
}

export async function extractReflectionSignals(state, prompt, text) {
  const sys = `${DIRECTOR_IDENTITY}

The user typed one honest line. Extract at most 3 weak signals and a short internal note. Return ONLY JSON:
{ "signals": [{"dim": string, "delta": -1..1, "weight": 0.1-0.7}], "note": string(<=90) }
Only use dims clearly supported by the text. If nothing is clear, return empty signals.`;
  const user = JSON.stringify({ prompt, text: String(text).slice(0, 300), validDimensions: Object.keys(state.dimensions).length ? undefined : undefined, state: compactState(state) });
  const out = await chat([{ role: "system", content: sys }, { role: "user", content: user }], { maxTokens: 300, timeoutMs: 8000 });
  return {
    signals: (out.signals || []).filter(s => isDim(s.dim)).slice(0, 3)
      .map(s => ({ dim: s.dim, delta: clampN(s.delta, -1, 1), weight: clampN(s.weight, 0.1, 0.7) })),
    note: str(out.note || "", 100),
  };
}

function str(v, max) { return String(v ?? "").replace(/\s+/g, " ").trim().slice(0, max); }
function clampN(v, lo, hi) { const n = Number(v); return Number.isFinite(n) ? Math.max(lo, Math.min(hi, n)) : lo; }
