import pytest
from app import statemachine as sm


def test_forward_transitions_valid():
    sm.validate_transition("PROLOGUE", "SELF_DISCOVERY")
    sm.validate_transition("SELF_DISCOVERY", "SELF_DISCOVERY_CLOSING")
    sm.validate_transition("SELF_DISCOVERY_CLOSING", "REFLECTION")
    sm.validate_transition("TRANSFORMATION", "TRANSFORMATION_CLOSING")
    sm.validate_transition("TRANSFORMATION_CLOSING", "STORY_COMPLETE")
    # the story ends at STORY_COMPLETE; MATERIALIZATION bridges into the product
    sm.validate_transition("STORY_COMPLETE", "MATERIALIZATION")
    sm.validate_transition("MATERIALIZATION", "DISCOVER_WORKSPACE")


def test_no_early_workspace():
    for state in ["PROLOGUE", "SELF_DISCOVERY", "REFLECTION", "ALIGNMENT", "TRANSFORMATION"]:
        with pytest.raises(sm.InvalidTransition):
            sm.validate_transition(state, "DISCOVER_WORKSPACE")


def test_no_skipping_chapters():
    with pytest.raises(sm.InvalidTransition):
        sm.validate_transition("SELF_DISCOVERY", "ALIGNMENT")
    with pytest.raises(sm.InvalidTransition):
        sm.validate_transition("SELF_DISCOVERY", "TRANSFORMATION")
    with pytest.raises(sm.InvalidTransition):
        sm.validate_transition("SELF_DISCOVERY", "REFLECTION")  # must pass through closing
    with pytest.raises(sm.InvalidTransition):
        sm.validate_transition("TRANSFORMATION", "STORY_COMPLETE")


def test_no_backwards():
    with pytest.raises(sm.InvalidTransition):
        sm.validate_transition("REFLECTION", "SELF_DISCOVERY")
