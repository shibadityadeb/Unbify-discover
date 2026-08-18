import pytest
from app import statemachine as sm


def test_forward_transitions_valid():
    sm.validate_transition("PROLOGUE", "SELF_DISCOVERY")
    sm.validate_transition("TRANSFORMATION", "STORY_COMPLETE")
    sm.validate_transition("STORY_COMPLETE", "OPPORTUNITY_MAP")


def test_no_early_opportunity_map():
    for state in ["PROLOGUE", "SELF_DISCOVERY", "REFLECTION", "ALIGNMENT", "TRANSFORMATION"]:
        with pytest.raises(sm.InvalidTransition):
            sm.validate_transition(state, "OPPORTUNITY_MAP")


def test_no_skipping_chapters():
    with pytest.raises(sm.InvalidTransition):
        sm.validate_transition("SELF_DISCOVERY", "ALIGNMENT")
    with pytest.raises(sm.InvalidTransition):
        sm.validate_transition("SELF_DISCOVERY", "TRANSFORMATION")


def test_no_backwards():
    with pytest.raises(sm.InvalidTransition):
        sm.validate_transition("REFLECTION", "SELF_DISCOVERY")
