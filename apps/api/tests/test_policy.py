from app.models import DiscoverSession
from app.policy import (ACTION_CATALOG, RuleBasedExperiencePolicy, build_context,
                        eligible_actions)


def make_session(state="SELF_DISCOVERY", **kw):
    return DiscoverSession(id="t1", anon_id="a1", journey_status=state,
                           dimensions=kw.get("dimensions", {}), contradictions=kw.get("contradictions", []),
                           practical_context=kw.get("practical_context", {}),
                           recent_interaction_types=kw.get("recent", []),
                           counters=kw.get("counters", {"since_reveal": 0, "reveals_this_chapter": 0, "chapter_interactions": 0}),
                           engagement={"skipped": 0}, used_definitions=[])


def test_policy_is_deterministic():
    s = make_session()
    ctx = build_context(s)
    elig = eligible_actions(s, ctx)
    p = RuleBasedExperiencePolicy()
    a1, prop1, _ = p.choose_action(ctx, elig)
    a2, _, _ = p.choose_action(ctx, elig)
    assert a1 == a2
    assert prop1 == 1.0


def test_policy_only_selects_eligible():
    s = make_session()
    ctx = build_context(s)
    elig = eligible_actions(s, ctx)
    action, _, _ = RuleBasedExperiencePolicy().choose_action(ctx, elig)
    assert action in elig
    assert action in ACTION_CATALOG


def test_no_immediate_repetition():
    s = make_session(recent=["scenario_choice"])
    ctx = build_context(s)
    elig = eligible_actions(s, ctx)
    assert "show_scenario" not in elig


def test_heavy_load_guard():
    s = make_session(recent=["forced_rank"])
    ctx = build_context(s)
    assert ctx["recent_heavy"] is True
    p = RuleBasedExperiencePolicy()
    action, _, values = p.choose_action(ctx, eligible_actions(s, ctx))
    assert action not in ("show_rank", "show_object_sort", "request_micro_reflection")


def test_no_transition_before_evidence():
    s = make_session()
    ctx = build_context(s)
    assert ctx["chapter_done"] is False
    assert "transition_chapter" not in eligible_actions(s, ctx)


def test_bounded_journey_forces_transition():
    s = make_session(counters={"since_reveal": 1, "reveals_this_chapter": 0, "chapter_interactions": 9})
    ctx = build_context(s)
    assert ctx["chapter_done"] is True
    assert eligible_actions(s, ctx) == ["transition_chapter"]


def test_fatigue_reduces_load():
    s = make_session()
    s.engagement = {"skipped": 1, "help_count": 1, "recent_latency": [20000, 25000]}
    ctx = build_context(s)
    assert ctx["fatigued"] is True
    elig = eligible_actions(s, ctx)
    assert "show_rank" not in elig and "show_object_sort" not in elig
