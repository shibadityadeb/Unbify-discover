"""PARTs 73-75, 4, 16, 55/56, 59, 77/96 — the judgment-discipline tests:
facts never become inferences, ambiguity never becomes signal, one answer
never creates a role, corrections cascade, and abstention is a real outcome."""
import pytest


@pytest.fixture()
def db(client):
    from app.db import SessionLocal
    s = SessionLocal()
    yield s
    s.rollback()
    s.close()


def make_session(db, journey_status="ALIGNMENT"):
    from app.models import AnonymousIdentity, DiscoverSession
    anon = AnonymousIdentity()
    db.add(anon)
    db.flush()
    session = DiscoverSession(anon_id=anon.id, journey_status=journey_status,
                              dimensions={}, practical_context={}, counters={})
    db.add(session)
    db.flush()
    return session


# ---------------- PART 73: the student test ----------------

def test_student_manage_software_is_ambiguous_not_management(db):
    from app.interpretation import interpret_free_text
    from app.models import AmbiguityRecord
    session = make_session(db)
    interpret_free_text(db, session, "I am a student.")
    out = interpret_free_text(db, session, "I manage codes and softwares for college projects.")
    pc = session.practical_context
    assert pc.get("current_status") == "student"
    assert pc.get("works_with_software") is True
    # the forbidden leaps:
    assert "people_management_evidence" not in pc
    assert "management_exposure" not in pc
    # ambiguity recorded, not resolved
    amb = db.query(AmbiguityRecord).filter_by(session_id=session.id, key="manage_software_scope").first()
    assert amb is not None and amb.status == "open"
    assert "software development" in amb.possible_interpretations
    # facts carry provenance
    assert pc["_facts"]["current_status"]["source"] == "explicit_user_statement"
    assert pc["_facts"]["current_status"]["confidence"] == 1.0


def test_clarification_is_easy_and_offered_when_valuable(db):
    from app.interpretation import interpret_free_text, pending_clarification, apply_clarification
    session = make_session(db, journey_status="ALIGNMENT")
    interpret_free_text(db, session, "I manage code and software.")
    pending = pending_clarification(db, session)
    assert pending is not None, "high-value professional ambiguity deserves one easy question"
    options = pending["definition"]["content"]["options"]
    assert len(options) >= 5 and any(o["id"] == "other" for o in options)
    assert "which is closest" in pending["definition"]["content"]["headline"].lower()
    # answering resolves it and stores explicit facts — still no role
    changed = apply_clarification(db, session, "manage_software_scope", "build")
    assert "hands_on_technical" in changed
    from app.models import AmbiguityRecord
    amb = db.query(AmbiguityRecord).filter_by(session_id=session.id, key="manage_software_scope").first()
    assert amb.status == "clarified"


def test_clarification_not_asked_when_low_value(db):
    """Early chapters + already-confident related state = leave it unresolved."""
    from app.interpretation import interpret_free_text, pending_clarification
    session = make_session(db, journey_status="SELF_DISCOVERY")
    session.dimensions = {"implementation_affinity": {"estimate": 0.8, "confidence": 0.85,
                                                      "evidence_count": 5, "pos_w": 3.0, "neg_w": 0.0,
                                                      "variance": 0.0}}
    interpret_free_text(db, session, "I manage software.")
    assert pending_clarification(db, session) is None


# ---------------- PART 74: software professional test ----------------

def test_engineer_with_review_duties_is_not_a_manager(db):
    from app.interpretation import interpret_free_text
    session = make_session(db)
    interpret_free_text(db, session,
                        "I'm a software engineer. I write most of the code, "
                        "but I also review two other developers' work.")
    pc = session.practical_context
    assert pc.get("hands_on_technical") is True
    assert "people_management_evidence" not in pc, "code review is not management"


# ---------------- PART 75: founder test ----------------

def test_founder_status_recorded_without_preference_assumption(db):
    from app.interpretation import interpret_free_text
    session = make_session(db)
    interpret_free_text(db, session, "I run a small software company with 8 employees.")
    pc = session.practical_context
    assert pc.get("current_status") == "founder"
    # current responsibility != natural preference: no leadership hypothesis exists
    from app.models import Hypothesis
    assert db.query(Hypothesis).filter_by(session_id=session.id, construct="leadership").count() == 0


# ---------------- PART 16: one answer cannot create a role ----------------

def test_single_answer_cannot_unlock_role_analysis(db):
    from app.knowledge import role_analysis_allowed
    session = make_session(db)
    from app.interpretation import interpret_free_text
    interpret_free_text(db, session, "I manage code and software.")
    allowed, reason = role_analysis_allowed(session)
    assert not allowed
    assert "coverage too low" in reason or "confidence too low" in reason


def test_role_analysis_gate_opens_with_real_evidence(db):
    from app.knowledge import role_analysis_allowed
    session = make_session(db)
    session.practical_context = {"current_status": "student", "builds_things": True,
                                 "commercial_evidence": True, "works_with_software": True,
                                 "hands_on_technical": True}
    session.dimensions = {
        "implementation_affinity": {"estimate": 0.8, "confidence": 0.7, "evidence_count": 4,
                                    "pos_w": 2.5, "neg_w": 0, "variance": 0},
        "experimentation": {"estimate": 0.7, "confidence": 0.65, "evidence_count": 3,
                            "pos_w": 2.0, "neg_w": 0, "variance": 0},
    }
    allowed, _ = role_analysis_allowed(session)
    assert allowed


# ---------------- PART 4: abstention ----------------

def test_inference_decision_abstains_without_evidence(db):
    from app.knowledge import inference_decision
    session = make_session(db)
    assert inference_decision(db, session, "autonomy")["status"] == "insufficient_evidence"


def test_inference_decision_flags_clarification(db):
    from app.interpretation import interpret_free_text
    from app.knowledge import inference_decision
    session = make_session(db, journey_status="ALIGNMENT")
    interpret_free_text(db, session, "I manage software systems.")
    decision = inference_decision(db, session, "manage_software_scope")
    assert decision["status"] == "needs_clarification"


# ---------------- evidence ledger + hypothesis versioning ----------------

def test_hypotheses_carry_evidence_ids_and_versions(db):
    from app.signals import apply_evidence
    from app.knowledge import sync_hypotheses
    from app.models import EvidenceItem, Hypothesis, HypothesisVersion
    session = make_session(db, journey_status="SELF_DISCOVERY")
    for _ in range(3):
        apply_evidence(db, session, [{"dim": "autonomy", "delta": 0.6, "weight": 0.6}],
                       "visual_choice", None, None)
        sync_hypotheses(db, session, trigger="test")
    hyp = db.query(Hypothesis).filter_by(session_id=session.id, construct="autonomy").first()
    assert hyp is not None
    assert len(hyp.supporting_evidence_ids) >= 3
    for eid in hyp.supporting_evidence_ids:
        assert db.get(EvidenceItem, eid) is not None, "hypothesis points at missing evidence"
    versions = db.query(HypothesisVersion).filter_by(session_id=session.id).all()
    assert len(versions) >= 2, "confidence growth must be versioned, not overwritten"


def test_one_evidence_item_is_never_supported(db):
    from app.signals import apply_evidence
    from app.knowledge import sync_hypotheses
    from app.models import Hypothesis
    session = make_session(db, journey_status="SELF_DISCOVERY")
    apply_evidence(db, session, [{"dim": "leadership", "delta": 0.9, "weight": 1.5}],
                   "visual_choice", None, None)
    sync_hypotheses(db, session, trigger="test")
    hyp = db.query(Hypothesis).filter_by(session_id=session.id, construct="leadership").first()
    assert hyp.status == "emerging", "one answer must never make a hypothesis 'supported'"


# ---------------- PART 55/56: corrections cascade ----------------

def test_correction_records_feedback_and_invalidates_downstream(db):
    from app.knowledge import record_correction
    from app.models import InferenceFeedback, NarrativeEvent
    session = make_session(db)
    pc = dict(session.practical_context)
    pc["_lives"] = [{"key": "x"}]
    session.practical_context = pc
    session.counters = {"lives_generated": True}
    record_correction(db, session, "leadership", "not_really", {"insight": "leads the room"})
    assert db.query(InferenceFeedback).filter_by(session_id=session.id).count() == 1
    assert "_lives" not in session.practical_context, "stale recommendations must not survive a correction"
    assert session.counters.get("lives_generated") is False
    events = [e.type for e in db.query(NarrativeEvent).filter_by(session_id=session.id)]
    assert "USER_CORRECTED_SYSTEM" in events


# ---------------- PART 59: ranker abstention ----------------

def test_possible_lives_abstains_to_broad_directions(db):
    from app.orchestrator import _make_possible_lives
    session = make_session(db, journey_status="ALIGNMENT")
    session.dimensions = {"autonomy": {"estimate": 0.6, "confidence": 0.4, "evidence_count": 2,
                                       "pos_w": 1.0, "neg_w": 0, "variance": 0}}
    out = _make_possible_lives(db, session)
    assert out["server"].get("abstained"), "weak evidence must yield abstention, not roles"
    assert "don't yet have enough evidence" in out["public"]["supportingText"]
    for life in out["public"]["lives"]:
        assert "recommendation" not in life["essence"] or "not a recommendation" in life["essence"]


def test_abstention_screen_reads_back_the_users_own_evidence(db):
    """Abstaining is not a licence to show a blank form.

    The pre-threshold Alignment screen used to render the full card scaffolding
    filled with constants — identical for every user, with "n/a" under two
    headings. It was honest and unreadable: nothing in it came from the person,
    so there was nothing to recognise. Every field must now be derived.
    """
    from app.orchestrator import _make_possible_lives
    session = make_session(db, journey_status="ALIGNMENT")
    session.dimensions = {
        "autonomy": {"estimate": 0.62, "confidence": 0.5, "evidence_count": 4,
                     "pos_w": 1.0, "neg_w": 0, "variance": 0},
        "originality": {"estimate": 0.51, "confidence": 0.42, "evidence_count": 3,
                        "pos_w": 1.0, "neg_w": 0, "variance": 0},
    }
    out = _make_possible_lives(db, session)
    assert out["server"].get("abstained")
    public = out["public"]
    lives = public["lives"]
    assert lives

    for life in lives:
        blob = " ".join(str(v) for v in life.values()).lower()
        assert "n/a" not in blob, "a placeholder under a heading reads as a broken form"
        assert "risk" not in life and "timeToValue" not in life, \
            "omit a field we cannot fill; never render it empty"
        assert content_policy_ok(life)

    # the user's own strongest signal has to appear in words they can recognise
    lead = next(l for l in lives if l["key"] == "energy")
    assert "setting your own hours and rules" in lead["whyYou"]
    assert "4 answers" in lead["whyYou"], "cite the evidence count, not 'your strongest evidence'"

    # and the abstention itself must name what is missing, not just that something is
    assert "don't yet have enough evidence" in public["supportingText"]
    assert "real-world context" in public["supportingText"]


def content_policy_ok(life: dict) -> bool:
    from app.content_policy import validate
    return all(validate(str(v)) for v in life.values())


def test_absence_closing_leads_with_what_is_present(db):
    """PART 36: an absence only means something next to a presence.

    The earlier composer opened on the system's expectation and closed by
    retracting itself. It must now open on what IS driving the choices.
    """
    from app.closing_planner import _detect_absence
    from app.closings import _unexpected_absence
    session = make_session(db, journey_status="REFLECTION")
    session.practical_context = {"works_with_software": True}
    session.dimensions = {
        "mastery": {"estimate": 0.1, "confidence": 0.3, "evidence_count": 2,
                    "pos_w": 1.0, "neg_w": 0, "variance": 0},
        "analytical": {"estimate": 0.05, "confidence": 0.32, "evidence_count": 2,
                       "pos_w": 1.0, "neg_w": 0, "variance": 0},
        "autonomy": {"estimate": 0.66, "confidence": 0.55, "evidence_count": 5,
                     "pos_w": 1.0, "neg_w": 0, "variance": 0},
    }
    payload = _detect_absence(db, session)
    assert payload, "software experience with no firm technical signal is an absence"
    beats = _unexpected_absence(db, session, None, {"drivingEvent": {"payload": payload}})

    assert "setting your own hours and rules" in beats[0]["text"], \
        "the first beat must be the pattern the reader can recognise"
    assert "hasn't been steering" in beats[1]["text"]
    assert "too early to interpret" not in beats[-1]["text"].lower(), \
        "the closing beat must carry the thread forward, not cancel the page"


# ---------------- PART 77/96: content policy ----------------

def test_content_policy_blocks_prescriptions_and_horoscopes():
    from app.content_policy import validate, violations
    bad = [
        "You should become an Operations Lead.",
        "Your ideal career is Product Manager.",
        "You are a visionary builder who thrives on innovation.",
        "You possess a rare combination of skills.",
        "You're destined to lead.",
        "An 87% match with successful entrepreneurs.",
    ]
    for text in bad:
        assert not validate(text), f"should have been rejected: {text}"
    good = [
        "You keep choosing to build before positioning — that pattern has repeated.",
        "Too early to say what this means. We're keeping it open.",
        "You told us you are an operations lead, so we'll read earlier answers in that light.",
    ]
    for text in good:
        assert validate(text), f"wrongly rejected: {violations(text)}"


# ---------------- ambiguity is never psychological signal (PART 62) ----------------

def test_ambiguity_creates_no_dimension_signal(db):
    from app.interpretation import interpret_free_text
    session = make_session(db)
    interpret_free_text(db, session, "I manage codes and softwares.")
    assert not session.dimensions, "ambiguous wording must never move psychological state"

def test_cached_payloads_rebuild_when_the_build_changes(db):
    """A payload cached by older composition code must not be served forever.

    The materialization and closing caches were keyed only on journey state, so
    a session that reached the page once kept the old payload across every
    later code change. Refreshing could not fix it — the cache was the thing
    being refreshed.
    """
    from app import content_build
    from app.models import AnonymousIdentity, DiscoverSession
    from app.orchestrator import next_step

    anon = AnonymousIdentity()
    db.add(anon)
    db.flush()
    stale = {"type": "materialization", "intro": ["composed by code that no longer exists"],
             "directions": [{"key": "old", "label": "Some employed role"}]}
    session = DiscoverSession(
        anon_id=anon.id, journey_status="MATERIALIZATION", dimensions={}, counters={},
        practical_context={"current_status": "founder", "_materialization": stale})
    db.add(session)
    db.flush()

    out = next_step(db, session)["interaction"]
    assert out["intro"] != stale["intro"], "an unstamped cache must be treated as stale"
    assert session.practical_context["_materialization"]["build"] == content_build.CONTENT_BUILD

    # a cache from THIS build is still reused — versioning must not defeat caching
    marker = {"type": "materialization", "intro": ["current build"], "directions": []}
    pc = dict(session.practical_context)
    pc["_materialization"] = content_build.stamped(marker)
    session.practical_context = pc
    assert next_step(db, session)["interaction"]["intro"] == ["current build"]


# ---------------- plain-language guard ----------------

BANNED_REGISTER = [
    "unfold", "tapestry", "essence of", "resonate", "embrace", "lean into",
    "hold space", "authentic self", "your journey", "deeper truth", "horizon",
    "the shape of you", "whisper", "compounding", "precedes you",
]


def test_user_facing_copy_stays_in_plain_language():
    """The register is a product decision, not a matter of taste.

    This is sold to people mid-workday who want to know what their experience is
    worth. Copy that reads like a poem costs comprehension, and comprehension is
    the whole mechanism — a person who doesn't understand a claim can't tell us
    it's wrong.
    """
    from app.dimensions import DIMENSIONS, FRAGMENTS

    for dim, meta in DIMENSIONS.items():
        for pole in ("pos", "neg"):
            phrase = meta[pole].lower()
            for banned in BANNED_REGISTER:
                assert banned not in phrase, f"{dim}.{pole} slipped back into {banned!r}"
            # these get slotted into "you chose X" — keep them short enough to read
            assert len(meta[pole].split()) <= 9, f"{dim}.{pole} is too long to read inline"
    for dim, pair in FRAGMENTS.items():
        for frag in pair:
            assert len(frag.split()) <= 5, f"{dim} fragment {frag!r} is too long to float on screen"


def test_every_dimension_phrase_reads_in_the_sentences_that_use_it():
    """Phrases are composed into fixed sentence frames; each must survive them."""
    from app.dimensions import DIMENSIONS, dim_phrase

    for dim in DIMENSIONS:
        for score in (1, -1):
            phrase = dim_phrase(dim, score)
            assert phrase and phrase[0].islower(), \
                f"{dim} phrase must start lowercase to sit mid-sentence: {phrase!r}"
            assert not phrase.endswith("."), f"{dim} phrase must not carry its own full stop"
