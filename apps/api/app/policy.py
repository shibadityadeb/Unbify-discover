"""Adaptive Experience Policy.

Policy V0 is deterministic and information-gain driven. Every decision logs
context, eligible actions, the chosen action, its propensity and the policy
version — the substrate for offline evaluation and the contextual bandit
(implemented in ml/policies/linucb.py, inactive until real data exists)."""
from __future__ import annotations

from abc import ABC, abstractmethod

from sqlalchemy.orm import Session

from .models import DiscoverSession, PolicyDecision
from .signals import information_gain_estimate, thinnest_dims, total_evidence
from .dimensions import CHAPTER_FOCUS

POLICY_VERSION = "rule_v0"

# safe approved action catalog — the policy can never invent actions
ACTION_CATALOG = [
    "show_visual_choice",
    "show_binary_tension",
    "show_spectrum",
    "show_scenario",
    "show_rank",
    "show_object_sort",
    "request_micro_reflection",
    "show_reveal",
    "explore_contradiction",
    "generate_possible_lives",
    "transition_chapter",
    "close_story",
]

ACTION_TO_TYPE = {
    "show_visual_choice": "visual_choice",
    "show_binary_tension": "binary_tension",
    "show_spectrum": "spectrum",
    "show_scenario": "scenario_choice",
    "show_rank": "forced_rank",
    "show_object_sort": "object_sort",
    "request_micro_reflection": "micro_reflection",
}

HEAVY_ACTIONS = {"show_rank", "show_object_sort", "request_micro_reflection"}
COGNITIVE_COST = {
    "show_visual_choice": 0.15, "show_binary_tension": 0.2, "show_spectrum": 0.2,
    "show_scenario": 0.3, "show_rank": 0.5, "show_object_sort": 0.5,
    "request_micro_reflection": 0.7, "show_reveal": 0.1, "explore_contradiction": 0.2,
}

# bounded journeys: never trap a user because confidence is low
CHAPTER_MAX_INTERACTIONS = {"SELF_DISCOVERY": 9, "REFLECTION": 9, "ALIGNMENT": 10, "TRANSFORMATION": 3}
CHAPTER_MIN_EVIDENCE = {"SELF_DISCOVERY": 8, "REFLECTION": 5, "ALIGNMENT": 0, "TRANSFORMATION": 0}


class ExperiencePolicy(ABC):
    version: str

    @abstractmethod
    def choose_action(self, context: dict, eligible_actions: list[str]) -> tuple[str, float, dict]:
        """returns (action, propensity, action_values)"""


class RuleBasedExperiencePolicy(ExperiencePolicy):
    version = POLICY_VERSION

    def choose_action(self, context: dict, eligible_actions: list[str]) -> tuple[str, float, dict]:
        values: dict[str, float] = {}
        for action in eligible_actions:
            values[action] = self._candidate_value(action, context)
        chosen = max(values, key=values.get)
        # deterministic policy: chosen with certainty (propensity 1.0)
        return chosen, 1.0, values

    def _candidate_value(self, action: str, ctx: dict) -> float:
        info_gain = ctx.get("info_gain", {}).get(action, 0.3)
        novelty = 0.0 if action in ctx.get("recent_actions", [])[-2:] else 0.25
        repetition_penalty = 0.5 if ctx.get("recent_actions", [])[-1:] == [action] else 0.0
        cognitive = COGNITIVE_COST.get(action, 0.3)
        load_penalty = cognitive * 0.8 if ctx.get("recent_heavy") else 0.0
        if ctx.get("fatigued"):
            load_penalty += cognitive * 1.2  # quietly become easier — never announce it
        chapter_relevance = ctx.get("chapter_relevance", {}).get(action, 0.5)
        reveal_bonus = 0.0
        if action == "show_reveal":
            reveal_bonus = 0.9 if ctx.get("reveal_due") else -1.5
        if action == "explore_contradiction":
            reveal_bonus = 1.1 if ctx.get("contradiction_ready") else -2.0
        if action == "transition_chapter":
            reveal_bonus = 2.0 if ctx.get("chapter_done") else -3.0
        if action == "generate_possible_lives":
            reveal_bonus = 1.6 if ctx.get("lives_ready") else -3.0
        if action == "close_story":
            reveal_bonus = 2.5 if ctx.get("story_ready") else -4.0
        return (info_gain * 1.2 + chapter_relevance * 0.6 + novelty + reveal_bonus
                - cognitive * 0.4 - repetition_penalty - load_penalty)


def build_context(session: DiscoverSession) -> dict:
    counters = session.counters or {}
    chapter = session.journey_status
    focus = CHAPTER_FOCUS.get(chapter, [])
    recent = session.recent_interaction_types or []
    type_to_action = {v: k for k, v in ACTION_TO_TYPE.items()}
    recent_actions = [type_to_action.get(t, f"show_{t}") for t in recent[-4:]]
    thin = thinnest_dims(session, focus, 4) if focus else []
    evid = total_evidence(session)
    since_reveal = counters.get("since_reveal", 0)
    reveals = counters.get("reveals_this_chapter", 0)
    chapter_count = counters.get("chapter_interactions", 0)
    max_len = CHAPTER_MAX_INTERACTIONS.get(chapter, 9)
    min_evid = CHAPTER_MIN_EVIDENCE.get(chapter, 6)
    unexplored_contradiction = any(not c.get("explored") for c in (session.contradictions or []))
    practical_keys = [k for k in (session.practical_context or {}) if k not in ("notes", "resonant_life", "professional", "_lives")]
    # fatigue is a UX signal, never psychology: long latencies + skips + help requests
    engagement = session.engagement or {}
    recent_lat = (engagement.get("recent_latency") or [])[-3:]
    fatigued = (
        engagement.get("help_count", 0) + engagement.get("skipped", 0) >= 2
        or (len(recent_lat) >= 2 and sum(recent_lat) / len(recent_lat) > 18000)
    )

    chapter_done = False
    lives_ready = False
    story_ready = False
    if chapter == "SELF_DISCOVERY":
        chapter_done = (reveals >= 1 and evid >= min_evid and since_reveal >= 2) or chapter_count >= max_len
    elif chapter == "REFLECTION":
        chapter_done = (reveals >= 2 and counters.get("reflections", 0) >= 1 and since_reveal >= 1) or chapter_count >= max_len
    elif chapter == "ALIGNMENT":
        lives_ready = len(practical_keys) >= 5 and not counters.get("lives_generated")
        chapter_done = bool(counters.get("life_resonance_recorded")) or chapter_count >= max_len
    elif chapter == "TRANSFORMATION":
        # one connecting reveal, then the story closes — never an endless mirror
        story_ready = reveals >= 1

    reveal_due = (
        (chapter == "SELF_DISCOVERY" and since_reveal >= 3 and evid >= 5) or
        (chapter == "REFLECTION" and since_reveal >= 2 and reveals < 2)
    )

    info_gain = {}
    for action, itype in ACTION_TO_TYPE.items():
        info_gain[action] = information_gain_estimate(session, thin)
    return {
        "chapter": chapter,
        "evidence": evid,
        "since_reveal": since_reveal,
        "reveals": reveals,
        "chapter_interactions": chapter_count,
        "target_dims": thin,
        "recent_actions": recent_actions,
        "recent_heavy": bool(recent_actions and recent_actions[-1] in HEAVY_ACTIONS),
        "fatigued": fatigued,
        "help_count": engagement.get("help_count", 0),
        "skip_count": engagement.get("skipped", 0),
        "reveal_due": reveal_due,
        "contradiction_ready": chapter == "REFLECTION" and unexplored_contradiction and since_reveal >= 1,
        "chapter_done": chapter_done,
        "lives_ready": lives_ready,
        "story_ready": story_ready,
        "practical_keys": practical_keys,
        "info_gain": info_gain,
        "chapter_relevance": {a: 0.6 for a in ACTION_TO_TYPE},
        "skips": (session.engagement or {}).get("skipped", 0),
    }


def eligible_actions(session: DiscoverSession, context: dict) -> list[str]:
    chapter = session.journey_status
    out: list[str] = []
    if chapter == "TRANSFORMATION":
        return ["close_story"] if context["story_ready"] else ["show_reveal"]
    if context["chapter_done"]:
        return ["transition_chapter"]
    if context.get("lives_ready"):
        return ["generate_possible_lives"]
    for action, itype in ACTION_TO_TYPE.items():
        if itype == "micro_reflection":
            if (chapter in ("REFLECTION", "ALIGNMENT")
                    and (session.counters or {}).get("reflections", 0) < 3
                    and not context["recent_heavy"] and not context.get("fatigued")):
                out.append(action)
            continue
        if context.get("fatigued") and action in HEAVY_ACTIONS:
            continue
        out.append(action)
    if context["reveal_due"]:
        out.append("show_reveal")
    if context["contradiction_ready"]:
        out.append("explore_contradiction")
    # never immediately repeat the same interaction action twice
    last = context["recent_actions"][-1:] or [None]
    out = [a for a in out if a != last[0] or a in ("show_reveal", "explore_contradiction")]
    return out


def decide(db: Session, session: DiscoverSession, policy: ExperiencePolicy) -> PolicyDecision:
    context = build_context(session)
    eligible = eligible_actions(session, context)
    action, propensity, values = policy.choose_action(context, eligible)
    decision = PolicyDecision(
        session_id=session.id, policy_version=policy.version,
        context={k: v for k, v in context.items() if k != "info_gain"} | {"info_gain": context["info_gain"]},
        eligible_actions=eligible, chosen_action=action,
        propensity=propensity, action_values=values,
    )
    db.add(decision)
    db.flush()
    return decision
