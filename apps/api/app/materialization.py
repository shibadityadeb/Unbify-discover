"""MATERIALIZATION — the bridge from understanding to utility.

The four chapters produced MEANING. This produces VALUE: real objects the
user can save, test, compare and act on — professional position, capability
map, leverage map, gaps, directions and experiments. Every object carries the
evidence that produced it; nothing here is a personality label, and nothing
is invented by the LLM.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from . import experiments, knowledge, products, venture
from . import thresholds as th
from .dimensions import DIMENSIONS, dim_fragment, dim_phrase
from .models import (AmbiguityRecord, DiscoverSession, EvidenceItem, Hypothesis,
                     MaterialObject, MaterializationSnapshot, RecommendationItem,
                     WICapability)
from .signals import top_dims

MATERIALIZATION_VERSION = 1


# ---------------- object persistence ----------------

def _upsert(db: Session, session: DiscoverSession, kind: str, key: str, label: str,
            detail: dict, evidence_ids: list[str], strength: float) -> MaterialObject:
    row = (db.query(MaterialObject)
           .filter_by(session_id=session.id, kind=kind, key=key).first())
    if not row:
        row = MaterialObject(session_id=session.id, kind=kind, key=key)
        db.add(row)
    row.label = label[:200]
    row.detail = detail
    row.evidence_ids = evidence_ids[:8]
    row.strength = round(strength, 3)
    row.materialization_version = MATERIALIZATION_VERSION
    db.flush()
    return row


def _evidence_for_dims(db: Session, session: DiscoverSession, dims: list[str],
                       limit: int = 3) -> tuple[list[str], list[str]]:
    """→ (evidence ids, human-readable claims) for the given dimensions."""
    ids, claims = [], []
    rows = (db.query(EvidenceItem).filter_by(session_id=session.id)
            .order_by(EvidenceItem.created_at.desc()).all())
    for r in rows:
        if any(d.get("dim") in dims for d in (r.dims or [])):
            ids.append(r.id)
            claims.append(r.claim)
        if len(ids) >= limit:
            break
    return ids, claims


def _explicit_evidence(db: Session, session: DiscoverSession, limit: int = 6):
    return (db.query(EvidenceItem)
            .filter(EvidenceItem.session_id == session.id,
                    EvidenceItem.kind.in_(("explicit_fact", "professional_history")))
            .order_by(EvidenceItem.created_at.desc()).limit(limit).all())


# ---------------- WHERE YOU STAND ----------------

FACT_LABELS = {
    "current_status": "Current context", "current_occupation_title": "What you do",
    "works_with_software": "Works with software", "hands_on_technical": "Hands-on technical work",
    "builds_things": "Builds things", "commercial_evidence": "Has been paid for the work",
    "freelance_experience": "Independent work experience",
    "people_management_evidence": "Has led people", "coordinates_delivery": "Coordinates delivery",
    "technical_decision_authority": "Owns technical decisions",
    "years_mentioned": "Years of experience", "client_exposure": "Direct client exposure",
}


STATUS_LABELS = {
    "employed_good": "Employed — and it mostly works",
    "employed_stale": "Employed — but stalling",
    "founder": "Running your own business", "freelance": "Working independently",
    "student": "Studying", "between": "Between roles", "between_roles": "Between roles",
    "retired": "Retired",
}


def professional_position(db: Session, session: DiscoverSession) -> dict:
    pc = session.practical_context or {}
    facts = pc.get("_facts", {})
    context, evidence_rows = [], []
    for key, label in FACT_LABELS.items():
        if key not in pc:
            continue
        value = pc[key]
        if isinstance(value, bool):
            pretty = "yes" if value else "no"
        elif key == "current_status":
            pretty = STATUS_LABELS.get(str(value), str(value).replace("_", " "))
        else:
            pretty = str(value).replace("_", " ")
        row = {"label": label, "value": pretty,
               "source": (facts.get(key, {}) or {}).get("source", "derived_fact")}
        (context if key in ("current_status", "current_occupation_title") else evidence_rows).append(row)

    # what remains genuinely unclear — from open ambiguities + thin dimensions
    unclear = []
    for amb in db.query(AmbiguityRecord).filter_by(session_id=session.id, status="open").all():
        unclear.append(amb.description)
    dims = session.dimensions or {}
    for dim in ("sales_comfort", "revenue_ambition", "risk_tolerance", "time_availability",
                "leadership", "capital_availability"):
        state = dims.get(dim, {})
        if state.get("confidence", 0) < th.WEAK_INTERNAL:
            unclear.append(f"how you relate to {dim_phrase(dim, 1)}")
        if len(unclear) >= 4:
            break
    return {"heading": "Where you stand", "context": context,
            "evidence": evidence_rows, "unclear": unclear[:4]}


# ---------------- CAPABILITY MAP ----------------

def capability_map(db: Session, session: DiscoverSession) -> list[dict]:
    """Real capability clusters with what supports them — never personality labels."""
    from .world.ontology import user_capability_vector
    vec = user_capability_vector(db, session)
    if not vec:
        return []
    out = []
    for cap_id, weight in sorted(vec.items(), key=lambda kv: -kv[1])[:7]:
        cap = db.get(WICapability, cap_id)
        label = (cap.label if cap else cap_id.replace("_", " ")).capitalize()
        supported_by, ids = [], []
        pc = session.practical_context or {}
        for fact, flabel in FACT_LABELS.items():
            if pc.get(fact) and fact in ("builds_things", "hands_on_technical", "commercial_evidence",
                                         "people_management_evidence", "coordinates_delivery",
                                         "freelance_experience", "technical_decision_authority"):
                supported_by.append(flabel.lower())
        title = pc.get("current_occupation_title")
        if title:
            supported_by.insert(0, f"your work as {title}")
        # Every card used to print the same first fact, so four capabilities all
        # read "from has led people" — which looks like a rendering fault rather
        # than a reading. Each card now cites a different piece of support, and
        # where there is only one fact to cite it is stated once, on the card it
        # backs most strongly, instead of repeated underneath all of them.
        offset = len(out)
        if len(supported_by) > 1:
            supported_by = supported_by[offset % len(supported_by):] + \
                supported_by[:offset % len(supported_by)]
        elif offset:
            supported_by = []
        strength = ("strong" if weight >= 0.7 else "present" if weight >= 0.4 else "emerging")
        out.append({"key": cap_id, "label": label, "strength": strength,
                    "weight": round(weight, 2),
                    "supportedBy": supported_by[:3] if (supported_by or offset)
                    else ["your answers across the journey"],
                    "evidenceIds": ids})
    for c in out:
        _upsert(db, session, "capability", c["key"], c["label"],
                {"strength": c["strength"], "supportedBy": c["supportedBy"]},
                c["evidenceIds"], c["weight"])
    return out


# ---------------- LEVERAGE MAP ----------------

LEVERAGE_SOURCES = [
    ("domain_expertise", "Knowing your field", "years in one field add up whether you notice or not"),
    ("network", "People who'd take your call", "knowing people makes everything faster"),
    ("reputation", "A name people know", "trust you've already earned carries over"),
    ("audience", "People who already follow you", "you don't have to find an audience twice"),
    ("credentials", "Formal qualifications", "some doors are already open to you"),
    ("capital_availability", "Money you could put in", "money buys you time and shortcuts"),
    ("geographic_access", "Where you live", "being local is worth real money in some markets"),
]

PRACTICAL_LEVERAGE = {
    "commercial_evidence": ("Proof people pay you", "the hardest thing to fake, and you've already done it"),
    "freelance_experience": ("Experience working for yourself", "you've run work without a company around you"),
    "people_management_evidence": ("Experience leading people", "being responsible for others counts almost everywhere"),
    "builds_things": ("A record of finishing things", "finished work proves things nothing else can"),
    "years_mentioned": ("Years in the work", "there's no shortcut to time served"),
    "technical_decision_authority": ("You own the technical calls", "people already trust your judgement"),
}


def leverage_map(db: Session, session: DiscoverSession) -> list[dict]:
    """What is already compounding — so the user knows they aren't starting at zero."""
    out = []
    dims = session.dimensions or {}
    pc = session.practical_context or {}
    for key, (label, note) in PRACTICAL_LEVERAGE.items():
        if pc.get(key):
            ids, claims = _evidence_for_dims(db, session, [], 1)
            out.append({"key": key, "label": label, "note": note, "strength": 0.8,
                        "basis": "you told us this directly", "evidenceIds": ids})
    for dim, label, note in LEVERAGE_SOURCES:
        state = dims.get(dim, {})
        if state.get("estimate", 0) > 0.2 and state.get("confidence", 0) >= th.MAY_TEST:
            ids, claims = _evidence_for_dims(db, session, [dim], 2)
            out.append({"key": dim, "label": label, "note": note,
                        "strength": round(state["confidence"], 2),
                        "basis": f"supported across {state.get('evidence_count', 2)} answers",
                        "evidenceIds": ids})
    title = pc.get("current_occupation_title")
    if title and not any(l["key"] == "domain_expertise" for l in out):
        from .world.ontology import resolve_title
        res = resolve_title(db, str(title))
        if res["status"] == "resolved":
            years = pc.get("years_mentioned")
            out.append({"key": "occupation_domain", "strength": 0.75,
                        "label": f"Everything you know about {res['candidates'][0]['label'].lower()} work",
                        "note": "the slowest thing to build, and the easiest to undervalue in yourself",
                        "basis": (f"{years} years in the work" if years else "your stated occupation"),
                        "evidenceIds": []})
    out.sort(key=lambda x: -x["strength"])
    for l in out[:6]:
        _upsert(db, session, "leverage", l["key"], l["label"],
                {"note": l["note"], "basis": l["basis"]}, l["evidenceIds"], l["strength"])
    return out[:6]


# ---------------- GAPS ----------------

def gaps(db: Session, session: DiscoverSession, directions: list[dict]) -> list[dict]:
    """What would change the picture — framed as missing information, never deficiency.
    These feed the Questions tab directly."""
    out, seen = [], set()
    pc = session.practical_context or {}
    for d in directions[:3]:
        for cap in (d.get("missing") or [])[:2]:
            key = cap if isinstance(cap, str) else str(cap)
            if key in seen:
                continue
            seen.add(key)
            cap_row = db.get(WICapability, key)
            label = (cap_row.label if cap_row else key.replace("_", " "))
            out.append({"key": key, "kind": "capability", "label": label,
                        "why": f"it's the main thing in the way of {d['label']}",
                        "preferBuy": key in ("customer_acquisition", "sales_selling",
                                             "business_administration"),
                        "blocks": d["label"]})
        lic = d.get("licensing") or {}
        if lic.get("required") and not lic.get("eligible") and "license" not in seen:
            seen.add("license")
            out.append({"key": "license", "kind": "regulatory", "label": lic.get("note", "a required licence"),
                        "why": f"{d['label']} is regulated — eligibility decides whether it's real at all",
                        "preferBuy": False, "blocks": d["label"]})
    # evidence gaps: things we'd need to ask about
    dims = session.dimensions or {}
    evidence_gaps = [
        ("sales_comfort", "evidence about how you feel selling",
         "anything you run yourself depends on it, and right now we're guessing"),
        ("time_availability", "a clearer view of the time you actually have",
         "it decides what's realistic this year rather than one day"),
        ("capital_availability", "what resources you could put behind this",
         "it separates what you could start now from what needs saving up for first"),
        ("risk_tolerance", "how much downside you'd genuinely accept",
         "it changes whether the safe version or the bold version suits you"),
    ]
    for dim, label, why in evidence_gaps:
        if dim in seen:
            continue
        state = dims.get(dim, {})
        if state.get("confidence", 0) < th.MAY_TEST:
            seen.add(dim)
            out.append({"key": dim, "kind": "evidence", "label": label,
                        "why": why, "preferBuy": False, "blocks": None})
    for amb in db.query(AmbiguityRecord).filter_by(session_id=session.id, status="open").all():
        if amb.key in seen:
            continue
        seen.add(amb.key)
        out.append({"key": amb.key, "kind": "ambiguity", "label": amb.description,
                    "why": "one quick answer would sharpen everything after it",
                    "preferBuy": False, "blocks": None})
    for g in out[:6]:
        _upsert(db, session, "gap", g["key"], g["label"],
                {"why": g["why"], "kind": g["kind"], "blocks": g.get("blocks")}, [], 0.5)
    return out[:6]


# ---------------- DIRECTIONS ----------------

def directions(db: Session, session: DiscoverSession, rec_set_id: str | None = None) -> list[dict]:
    """Material directions from the world engine — with why, transfers, missing,
    realism, risk, market evidence and the cheapest way to test each."""
    from .world.matching import recommend
    from .config import settings
    rec_set = None
    if settings.world_intelligence_enabled:
        rec_set = recommend(db, session)
    if rec_set is None:
        return []
    items = (db.query(RecommendationItem).filter_by(set_id=rec_set.id)
             .order_by(RecommendationItem.rank).all())
    from .models import Opportunity
    from .models import WIOpportunitySnapshot
    snap = (db.query(WIOpportunitySnapshot)
            .filter_by(recommendation_set_id=rec_set.id).first())
    cand_by_key = {}
    for c in (snap.candidates if snap else []):
        cand_by_key[f"world_{c.get('occupationId')}_{c.get('pathway')}"[:60]] = c

    out = []
    for item in items:
        opp = db.get(Opportunity, item.opportunity_id)
        if not opp:
            continue
        n = item.narrative or {}
        cand = cand_by_key.get(item.opportunity_id, {})
        existing = (db.query(MaterialObject)
                    .filter_by(session_id=session.id, kind="direction", key=opp.id).first())
        d = {
            "key": opp.id, "label": opp.title, "pathway": opp.pathway_type,
            "whyThisAppeared": n.get("whyYou") or opp.value_proposition,
            "whatYouHave": [t.replace("_", " ") for t in (cand.get("transfers") or [])][:3] or
                           [t.strip() for t in
                            (n.get("whyYou", "").replace("your evidence shows", "").split(","))
                            if t.strip()][:3],
            "missing": opp.skill_gaps or [],
            "whatMakesItRealistic": (f"it builds on work you already do" if opp.time_to_first_value == "weeks"
                                     else "it uses capabilities you already have, with real steps in between"),
            "whatMakesItRisky": n.get("friction") or "unknown until tested",
            "marketEvidence": n.get("whyNow") or "No strong timing signal yet.",
            "evidenceFreshness": n.get("freshnessDays"),
            "confidenceLabel": n.get("confidenceLabel", "uncertain"),
            "rankingFactors": item.factor_contributions,
            "licensing": {"required": bool(cand.get("licensing", {}).get("required")),
                          "eligible": bool(cand.get("licensing", {}).get("eligible", True)),
                          "note": (cand.get("licensing") or {}).get("note")},
            "status": existing.status if existing else "new",
            "saved": bool(existing.saved) if existing else False,
        }
        d["experiment"] = experiments.generate(session, d)
        out.append(d)
        obj = _upsert(db, session, "direction", d["key"], d["label"],
                      {k: v for k, v in d.items() if k not in ("status", "saved")},
                      [], max(0.1, min(1.0, item.score)))
        _upsert(db, session, "experiment", f"exp_{d['key']}", d["experiment"]["action"],
                {"teaches": d["experiment"]["teaches"], "effort": d["experiment"]["effort"],
                 "direction": d["key"]}, [], 0.5)
    return out


# ---------------- assembly ----------------

def build(db: Session, session: DiscoverSession) -> dict:
    """Full materialization payload. Evidence determines what exists —
    sections with nothing behind them simply don't appear."""
    position = professional_position(db, session)
    caps = capability_map(db, session)
    lev = leverage_map(db, session)
    dirs = directions(db, session)
    gp = gaps(db, session, dirs)

    material = {"directions": dirs, "gaps": gp, "leverage": lev,
                "openQuestionCount": len([g for g in gp if g["kind"] in ("evidence", "ambiguity")])}
    routes = products.route(db, session, material)

    intro = ["Four chapters to work out how you decide things.",
             "Here's what that's actually worth."]
    payload = {
        "type": "materialization",
        "intro": intro,
        "position": position,
        "capabilities": caps,
        "leverage": lev,
        "gaps": gp,
        # Chapter IV is the audit, not the shop. Role recommendations and product
        # routes belonged to a page that was trying to conclude; what follows the
        # audit is one question, not a list of suggestions. They are still
        # computed and persisted as material objects — the workspace's Explore
        # action is where someone asks for them — but the page does not show them.
        "directions": dirs,
        "productRoutes": routes,
        "showDirections": False,
        "showProductRoutes": False,
        "cta": "Enter your Discover space →",
        "next": "DISCOVER_WORKSPACE",
    }

    # OPERATOR BRANCH: someone already running a business is not choosing a job.
    # Offering them "Facilities Maintenance Technician — employed role" ignores
    # the most important thing they told us. They get a read on what they run
    # instead, and role directions are withheld entirely.
    if venture.is_operator(session):
        payload["audience"] = "operator"
        payload["directions"] = []
        payload["venture"] = {
            "heading": "What you're actually strong at",
            "supportingText": "Taken from your own answers — not a job title we picked for you.",
            "strengths": venture.strengths(db, session),
            "thinSpots": venture.thin_spots(db, session),
            "market": venture.market_standing(db, session),
        }
        answers = venture.probe_answers(session)
        payload["explore"] = {
            "cta": "Explore something interesting for you →",
            "note": "A few quick questions about how you run it.",
            "answers": answers,
            "next": venture.next_probe_step(answers),
            "read": venture.probe_read(answers),
            "surfaces": venture.surfaces_for(db, session, answers,
                                             [c["key"] for c in caps]) if answers else [],
        }
    else:
        payload["audience"] = "explorer"
    # the field-level read: real numbers where we hold them, named gaps where we
    # do not, ordered by the job-or-build branch if the person has picked one
    from . import insights as _insights
    payload["insights"] = _insights.top_insights(db, session, _insights.current_intent(session))
    # the follow-up is chosen by the model from the assessed situation and shown
    # a few seconds after the page settles — never a branch we wrote by hand
    from . import situation as _situation
    payload["situationProbe"] = _situation.next_question(db, session)
    payload["probeDelayMs"] = 3000

    snapshot = MaterializationSnapshot(session_id=session.id, version=MATERIALIZATION_VERSION,
                                       payload=payload)
    db.add(snapshot)
    db.flush()
    return payload


# ---------------- object lifecycle ----------------

VALID_STATUSES = ("new", "exploring", "saved", "testing", "active", "dismissed", "completed")


def set_status(db: Session, session: DiscoverSession, kind: str, key: str, status: str,
               reason: str | None = None) -> MaterialObject | None:
    if status not in VALID_STATUSES:
        return None
    row = (db.query(MaterialObject)
           .filter_by(session_id=session.id, kind=kind, key=key).first())
    if not row:
        return None
    row.status = status
    row.saved = status in ("saved", "testing", "active")
    if status == "dismissed" and reason:
        row.dismissal_reason = reason[:200]
    if status == "dismissed":
        # strong ranking feedback — the user disagreeing is data, not error
        knowledge.emit_event(db, session, "USER_CORRECTED_SYSTEM",
                             {"dismissed": key, "reason": reason}, importance=0.6)
    db.flush()
    return row


def saved_objects(db: Session, session: DiscoverSession) -> list[dict]:
    rows = (db.query(MaterialObject)
            .filter(MaterialObject.session_id == session.id,
                    MaterialObject.saved.is_(True)).all())
    return [{"kind": r.kind, "key": r.key, "label": r.label, "status": r.status,
             "detail": r.detail} for r in rows]
