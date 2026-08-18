"""Server-authoritative journey state machine. Frontend URLs never decide state.
PART ONE (the four-chapter story) must finish before PART TWO (the persistent
Discover Workspace with Questions + Actions, where the Opportunity Map lives)."""

STATES = [
    "PROLOGUE",
    "SELF_DISCOVERY",
    "REFLECTION",
    "ALIGNMENT",
    "TRANSFORMATION",
    "STORY_COMPLETE",
    "DISCOVER_WORKSPACE",
]

TRANSITIONS: dict[str, list[str]] = {
    "PROLOGUE": ["SELF_DISCOVERY"],
    "SELF_DISCOVERY": ["REFLECTION"],
    "REFLECTION": ["ALIGNMENT"],
    "ALIGNMENT": ["TRANSFORMATION"],
    "TRANSFORMATION": ["STORY_COMPLETE"],
    "STORY_COMPLETE": ["DISCOVER_WORKSPACE"],
    "DISCOVER_WORKSPACE": [],
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
