"""Quote discipline: verified-only display, real provenance, evidence-pulled
(never decorative), no repetition, and no influence on profile scores."""
import pytest


@pytest.fixture()
def db(client):
    from app.db import SessionLocal
    s = SessionLocal()
    yield s
    s.rollback()
    s.close()


def make_session(db, dims=None, practical=None):
    from app.models import AnonymousIdentity, DiscoverSession
    anon = AnonymousIdentity()
    db.add(anon)
    db.flush()
    s = DiscoverSession(anon_id=anon.id, journey_status="REFLECTION",
                        dimensions=dims or {}, practical_context=practical or {}, counters={})
    db.add(s)
    db.flush()
    return s


def strong(estimate=0.8, confidence=0.8, count=5):
    return {"estimate": estimate, "confidence": confidence, "variance": 0.0,
            "evidence_count": count, "pos_w": 3.0, "neg_w": 0.0}


DEEP = {"mastery": strong(), "domain_expertise": strong(), "persistence": strong()}


def verify_all(db):
    from app.models import QuoteRecord
    for q in db.query(QuoteRecord).all():
        q.verification_status = "verified"
    db.flush()


# ---------------- verification gate ----------------

def test_quotes_seed_unverified_and_stay_invisible(db):
    """Nothing reaches a user until a human checks it against the source."""
    from app.models import QuoteRecord
    from app.quotes import select_quote
    rows = db.query(QuoteRecord).all()
    assert rows, "seed corpus missing"
    assert all(q.verification_status == "review_needed" for q in rows), \
        "seeded quotes must not be self-certified as verified"
    session = make_session(db, DEEP)
    assert select_quote(db, session, "REFLECTION_CLOSING") is None, \
        "unverified quotes must never be shown"


def test_rejected_quotes_are_never_shown(db):
    from app.models import QuoteRecord
    from app.quotes import select_quote
    verify_all(db)
    for q in db.query(QuoteRecord).all():
        q.verification_status = "rejected"
    db.flush()
    session = make_session(db, DEEP)
    assert select_quote(db, session, "REFLECTION_CLOSING") is None


# ---------------- provenance + retrieval ----------------

def test_every_quote_has_a_real_source_and_person(db):
    from app.models import QuotePerson, QuoteRecord, QuoteSource
    for q in db.query(QuoteRecord).all():
        assert db.get(QuotePerson, q.person_id) is not None
        source = db.get(QuoteSource, q.source_id)
        assert source is not None and source.title, f"{q.id} has no source"
        assert q.themes and q.professional_patterns, f"{q.id} is unroutable"


def test_quote_is_pulled_by_supported_evidence(db):
    from app.quotes import select_quote
    verify_all(db)
    strong_session = make_session(db, DEEP)
    bundle = select_quote(db, strong_session, "REFLECTION_CLOSING")
    assert bundle, "a strongly supported pattern should find a principle"
    assert bundle["yourEvidence"], "a quote must be tied to the user's own evidence"
    assert bundle["source"]["title"]
    # no supported pattern -> no quote, rather than a decorative one
    empty = make_session(db, {"autonomy": strong(0.4, 0.2, 1)})
    assert select_quote(db, empty, "REFLECTION_CLOSING") is None


def test_success_is_not_only_tech_founders(db):
    """§23 — the library must not equate accomplishment with tech wealth."""
    from app.models import QuotePerson
    fields = {p.field for p in db.query(QuotePerson).all()}
    assert {"trades", "science", "craft", "sport", "manufacturing"} <= fields, \
        f"library too narrow: {fields}"
    assert len(fields) >= 6


def test_same_principle_uses_two_different_worlds(db):
    from app.quotes import same_principle_different_world
    verify_all(db)
    session = make_session(db, DEEP)
    out = same_principle_different_world(db, session, "REFLECTION_CLOSING")
    if out is None:
        pytest.skip("no two-field pair for this evidence")
    assert len(out["people"]) == 2
    assert out["people"][0]["person"]["field"] != out["people"][1]["person"]["field"]
    assert "one principle" in out["honesty"].lower() or "overlap" in out["honesty"].lower()
    assert "identical" not in out["honesty"].lower()


# ---------------- repetition + non-contamination ----------------

def test_a_person_is_never_shown_twice(db):
    from app.quotes import record_impression, select_quote
    verify_all(db)
    session = make_session(db, DEEP)
    seen = []
    for chapter in ("SELF_DISCOVERY_CLOSING", "REFLECTION_CLOSING",
                    "ALIGNMENT_CLOSING", "TRANSFORMATION_CLOSING"):
        bundle = select_quote(db, session, chapter)
        if not bundle:
            continue
        seen.append(bundle["person"]["name"])
        record_impression(db, session, bundle, "quote", chapter)
    assert len(seen) == len(set(seen)), f"same voice repeated: {seen}"


def test_quotes_do_not_change_profile_state(db):
    """§52 — a quote is narrative context; it must not feed inference."""
    from app.quotes import record_impression, select_quote
    verify_all(db)
    session = make_session(db, DEEP)
    dims_before = {k: dict(v) for k, v in (session.dimensions or {}).items()}
    pc_before = dict(session.practical_context or {})
    bundle = select_quote(db, session, "REFLECTION_CLOSING")
    if bundle:
        record_impression(db, session, bundle, "quote", "REFLECTION_CLOSING")
    assert {k: dict(v) for k, v in (session.dimensions or {}).items()} == dims_before
    assert dict(session.practical_context or {}) == pc_before


# ---------------- pattern -> value ----------------

def test_pattern_value_explains_economic_mechanism(db):
    from app.quotes import value_of_pattern
    session = make_session(db, DEEP, {"current_occupation_title": "electrician"})
    value = value_of_pattern(db, session, "domain_depth")
    assert value and value["mechanisms"], "a pattern must map to a value mechanism"
    assert len(value["explanation"].split()) > 8
    for word in ("soul", "destiny", "universe", "manifest"):
        assert word not in value["explanation"].lower()


def test_material_language_in_pattern_values(db):
    from app.models import PatternValueRelationship
    rows = db.query(PatternValueRelationship).all()
    assert len(rows) >= 6
    material = ("leverage", "value", "pay", "market", "business", "income", "demand",
                "premium", "own", "client", "customer", "compound", "expertise",
                "money", "ceiling", "rare", "price", "hours", "sell", "reach")
    for r in rows:
        blob = (r.explanation + " " + " ".join(r.value_mechanisms)).lower()
        assert any(m in blob for m in material), f"{r.id} is not materially framed"
