"""Repetition protection for the Narrative Director.

Detects exact duplicates, normalized duplicates, semantic near-duplicates,
repeated sentence openings, repeated sentence shapes, repeated metaphors and
verbal tics across the WHOLE session — the rolling narrative memory lives in
NarrativeState.recent_copy / sentence_openings_used / metaphors_used.
"""
from __future__ import annotations

import re

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "for", "is",
    "are", "was", "were", "be", "been", "it", "its", "this", "that", "those",
    "these", "you", "your", "we", "our", "i", "so", "at", "as", "by", "with",
    "not", "no", "yet", "still", "just", "one", "what", "than", "then",
}

# openings that become verbal tics when they dominate the narration
TIC_OPENINGS = [
    "interesting", "something", "it seems", "you keep", "there's", "there is",
    "let's", "lets", "now", "okay", "so", "here's", "here is", "that",
]

# metaphor families the narration leans on; each may carry the story once
METAPHOR_MARKERS = {
    "map": ["map", "chart", "compass", "terrain"],
    "thread": ["thread", "weave", "unravel", "strand"],
    "mirror": ["mirror", "reflection", "reflect"],
    "echo": ["echo", "resonance", "resonate"],
    "constellation": ["constellation", "stars", "orbit"],
    "picture": ["picture", "portrait", "frame"],
    "puzzle": ["puzzle", "pieces", "fit together"],
    "shape": ["shape", "outline", "contour"],
    "story": ["story", "chapter", "page"],
    "light": ["light", "shadow", "glow", "spark"],
    "gravity": ["gravity", "pull", "orbit", "drawn toward"],
    "current": ["current", "tide", "drift", "flow"],
    "seed": ["seed", "root", "grow", "bloom"],
    "door": ["door", "threshold", "key", "unlock"],
}


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())).strip()


def content_tokens(text: str) -> set[str]:
    return {w for w in normalize(text).split() if len(w) > 2 and w not in _STOPWORDS}


def similarity(a: str, b: str) -> float:
    """Token-Jaccard over content words — cheap semantic-repetition proxy.
    'There's one thing I don't want to guess' vs 'One part is still something
    we shouldn't guess' land well above the rejection threshold."""
    ta, tb = content_tokens(a), content_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def opening_of(text: str) -> str:
    words = normalize(text).split()
    return " ".join(words[:2]) if words else ""


def shape_of(text: str) -> str:
    """Coarse structural fingerprint: opening word class + clause count +
    terminal punctuation. Catches the 'same two-line rhythm' failure mode."""
    t = (text or "").strip()
    words = normalize(t).split()
    first = words[0] if words else ""
    clauses = 1 + t.count(",") + t.count("—") + t.count(";")
    terminal = "?" if t.endswith("?") else ("…" if t.endswith("…") else ".")
    return f"{first}|{min(clauses, 4)}|{terminal}|{min(len(words) // 6, 4)}"


def metaphors_in(text: str) -> list[str]:
    t = normalize(text)
    found = []
    for family, markers in METAPHOR_MARKERS.items():
        if any(m in t for m in markers):
            found.append(family)
    return found


def tic_opening(text: str) -> str | None:
    t = normalize(text)
    for tic in TIC_OPENINGS:
        if t.startswith(tic + " ") or t == tic:
            return tic
    return None


class RepetitionVerdict:
    def __init__(self, ok: bool, reasons: list[str]):
        self.ok = ok
        self.reasons = reasons

    def __bool__(self) -> bool:
        return self.ok


def check(candidate: str, memory: dict, *, semantic_threshold: float = 0.5) -> RepetitionVerdict:
    """memory: {recent_copy: [str], openings: {opening: count}, shapes: {shape: count},
               metaphors: [family], tics: {tic: count}}"""
    reasons: list[str] = []
    cand_norm = normalize(candidate)
    if not cand_norm:
        return RepetitionVerdict(False, ["empty"])
    for prior in memory.get("recent_copy", []):
        if normalize(prior) == cand_norm:
            reasons.append("normalized_duplicate")
            break
    for prior in memory.get("recent_copy", [])[-40:]:
        if similarity(candidate, prior) >= semantic_threshold:
            reasons.append(f"semantic_repeat:{prior[:40]}")
            break
    opening = opening_of(candidate)
    if opening and memory.get("openings", {}).get(opening, 0) >= 2:
        reasons.append(f"opening_overused:{opening}")
    tic = tic_opening(candidate)
    if tic and memory.get("tics", {}).get(tic, 0) >= 2:
        reasons.append(f"tic:{tic}")
    shape = shape_of(candidate)
    if memory.get("shapes", {}).get(shape, 0) >= 3:
        reasons.append(f"shape_overused:{shape}")
    for family in metaphors_in(candidate):
        if family in memory.get("metaphors", []):
            reasons.append(f"metaphor_reused:{family}")
            break
    return RepetitionVerdict(not reasons, reasons)


def commit(candidate: str, memory: dict) -> dict:
    """Record accepted copy into the rolling memory (mutates a copy, returns it)."""
    mem = {
        "recent_copy": list(memory.get("recent_copy", [])),
        "openings": dict(memory.get("openings", {})),
        "shapes": dict(memory.get("shapes", {})),
        "metaphors": list(memory.get("metaphors", [])),
        "tics": dict(memory.get("tics", {})),
    }
    mem["recent_copy"] = (mem["recent_copy"] + [candidate])[-80:]
    op = opening_of(candidate)
    if op:
        mem["openings"][op] = mem["openings"].get(op, 0) + 1
    sh = shape_of(candidate)
    mem["shapes"][sh] = mem["shapes"].get(sh, 0) + 1
    tic = tic_opening(candidate)
    if tic:
        mem["tics"][tic] = mem["tics"].get(tic, 0) + 1
    for family in metaphors_in(candidate):
        if family not in mem["metaphors"]:
            mem["metaphors"].append(family)
    mem["metaphors"] = mem["metaphors"][-10:]
    return mem
