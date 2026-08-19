"""Server-authoritative journey state machine. Frontend URLs never decide state.
PART ONE (the four-chapter story) must finish before PART TWO (the persistent
Discover Workspace with Questions + Actions, where the Opportunity Map lives)."""

STATES = [
    "PROLOGUE",
    "SELF_DISCOVERY", "SELF_DISCOVERY_CLOSING",
    "REFLECTION", "REFLECTION_CLOSING",
    "ALIGNMENT", "ALIGNMENT_CLOSING",
    "TRANSFORMATION", "TRANSFORMATION_CLOSING",
    "STORY_COMPLETE",
    "MATERIALIZATION",
    "DISCOVER_WORKSPACE",
]

# Closing states are where the human reads at their own pace. The server enters
# a CLOSING state when the chapter objective is satisfied; ONLY an explicit user
# continue advances past it. There are no timers anywhere in this machine.
TRANSITIONS: dict[str, list[str]] = {
    "PROLOGUE": ["SELF_DISCOVERY"],
    "SELF_DISCOVERY": ["SELF_DISCOVERY_CLOSING"],
    "SELF_DISCOVERY_CLOSING": ["REFLECTION"],
    "REFLECTION": ["REFLECTION_CLOSING"],
    "REFLECTION_CLOSING": ["ALIGNMENT"],
    "ALIGNMENT": ["ALIGNMENT_CLOSING"],
    "ALIGNMENT_CLOSING": ["TRANSFORMATION"],
    "TRANSFORMATION": ["TRANSFORMATION_CLOSING"],
    "TRANSFORMATION_CLOSING": ["STORY_COMPLETE"],
    # the four-chapter STORY ends at STORY_COMPLETE. MATERIALIZATION is not a
    # fifth chapter — it is the bridge from understanding to utility, and only
    # an explicit user continue crosses it.
    "STORY_COMPLETE": ["MATERIALIZATION"],
    "MATERIALIZATION": ["DISCOVER_WORKSPACE"],
    "DISCOVER_WORKSPACE": [],
}

CLOSING_TO_NEXT = {
    "SELF_DISCOVERY_CLOSING": "REFLECTION",
    "REFLECTION_CLOSING": "ALIGNMENT",
    "ALIGNMENT_CLOSING": "TRANSFORMATION",
    "TRANSFORMATION_CLOSING": "STORY_COMPLETE",
}

CHAPTER_STATES = ["SELF_DISCOVERY", "REFLECTION", "ALIGNMENT", "TRANSFORMATION"]


class InvalidTransition(Exception):
    pass


def validate_transition(current: str, target: str) -> None:
    if target not in TRANSITIONS.get(current, []):
        raise InvalidTransition(f"{current} -> {target} is not permitted")


def advance(session, target: str) -> None:
    validate_transition(session.journey_status, target)
    session.journey_status = target


def is_chapter(state: str) -> bool:
    return state in CHAPTER_STATES
