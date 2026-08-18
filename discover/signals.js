/* Signal engine: evidence accumulation, dimension math, contradictions.
   Rules: one interaction only ever contributes weak evidence; corrections
   outweigh inference; conclusions need multiple supporting signals. */

import { DIMENSIONS, isDim } from "./dimensions.js";

export function ensureDim(state, dim) {
  if (!state.dimensions[dim]) {
    state.dimensions[dim] = { score: 0, confidence: 0, evidenceCount: 0, posW: 0, negW: 0 };
  }
  return state.dimensions[dim];
}

/* evidence: [{ dim, delta (-1..1), weight (0..1.5) }], source: string */
export function applyEvidence(state, evidence, source) {
  const applied = [];
  for (const ev of evidence || []) {
    if (!isDim(ev.dim)) continue;
    const delta = clamp(Number(ev.delta) || 0, -1, 1);
    const weight = clamp(Number(ev.weight) || 0.4, 0.05, 1.6);
    if (delta === 0) continue;
    const d = ensureDim(state, ev.dim);
    if (delta > 0) d.posW += weight * delta; else d.negW += weight * -delta;
    d.evidenceCount += 1;
    const total = d.posW + d.negW;
    d.score = total > 0 ? (d.posW - d.negW) / total : 0;
    d.confidence = Math.min(0.92, total / 3.2);
    applied.push({ dim: ev.dim, delta, weight, source, at: Date.now() });
  }
  state.evidence.push(...applied);
  if (state.evidence.length > 400) state.evidence = state.evidence.slice(-400);
  detectContradictions(state);
  return applied;
}

export function detectContradictions(state) {
  for (const [dim, d] of Object.entries(state.dimensions)) {
    if (d.posW >= 1.1 && d.negW >= 1.1) {
      if (!state.contradictions.find(c => c.dim === dim)) {
        state.contradictions.push({ dim, explored: false, at: Date.now() });
      }
    }
  }
}

export function topDims(state, n = 3, { minConfidence = 0.25, families = null } = {}) {
  return Object.entries(state.dimensions)
    .filter(([id, d]) => d.confidence >= minConfidence && (!families || families.includes(DIMENSIONS[id].family)))
    .sort((a, b) => Math.abs(b[1].score) * b[1].confidence - Math.abs(a[1].score) * a[1].confidence)
    .slice(0, n)
    .map(([id, d]) => ({ dim: id, ...d }));
}

/* dimensions in the chapter's focus families with the least evidence */
export function thinnestDims(state, families, n = 4) {
  const pool = Object.entries(DIMENSIONS)
    .filter(([, meta]) => families.includes(meta.family))
    .map(([id]) => ({ dim: id, count: state.dimensions[id]?.evidenceCount || 0 }))
    .sort((a, b) => a.count - b.count);
  return pool.slice(0, n).map(p => p.dim);
}

export function totalEvidence(state) {
  return state.evidence.length;
}

export function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

/* human phrase for a dimension in its current direction */
export function dimPhrase(dim, score) {
  const meta = DIMENSIONS[dim];
  if (!meta) return dim;
  return score >= 0 ? meta.pos : meta.neg;
}
