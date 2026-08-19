"""Versioned confidence thresholds — the system's judgment discipline in one
place. These are configuration, not constants scattered through call sites;
bump THRESHOLDS_VERSION when tuning so decisions stay auditable."""

THRESHOLDS_VERSION = "thresh_v1"

# knowledge-level bands (PART 5)
DO_NOT_SURFACE = 0.30          # below: internal only, never shown
WEAK_INTERNAL = 0.50           # 0.30–0.50: weak hypothesis, internal only
MAY_TEST = 0.70                # 0.50–0.70: may be tested via another interaction
MAY_OBSERVE = 0.85             # 0.70–0.85: may surface carefully as observation
                               # 0.85+:     may influence stronger synthesis

# professional / career claims carry higher stakes (PART 6)
PROFESSIONAL_SURFACE = 0.60          # min confidence to mention a professional pattern
ROLE_ANALYSIS_MIN_FACTS = 4          # explicit professional facts before role-level analysis
ROLE_ANALYSIS_MIN_FEATURES = 2       # supported features above PROFESSIONAL_SURFACE

# clarification economics (PART 10)
CLARIFICATION_VALUE_MIN = 0.35       # below: leave the ambiguity unresolved
MAX_CLARIFICATIONS_PER_CHAPTER = 1   # never interrogate

# hypothesis mechanics
HYPOTHESIS_MIN_EVIDENCE = 2          # one answer can never make a hypothesis "supported"
VERSION_DELTA = 0.05                 # confidence change that warrants a new version
FALSIFICATION_BAND = (0.50, 0.78)    # moderately strong: seek disconfirming tests

# overinterpretation (PART 15): claim_strength - evidence_confidence
OVERINTERPRETATION_MAX = 0.25


def band(confidence: float) -> str:
    if confidence < DO_NOT_SURFACE:
        return "do_not_surface"
    if confidence < WEAK_INTERNAL:
        return "weak_internal"
    if confidence < MAY_TEST:
        return "may_test"
    if confidence < MAY_OBSERVE:
        return "may_observe"
    return "synthesis"


def user_facing_strength(confidence: float) -> str:
    """PART 89: no false precision toward the user."""
    if confidence >= MAY_OBSERVE:
        return "strong evidence"
    if confidence >= MAY_TEST:
        return "emerging"
    return "still unclear"
