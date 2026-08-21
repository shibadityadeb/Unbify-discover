"""The follow-up the model decides, not a decision tree we wrote.

Chapter IV opens, and a few seconds later one short question appears. Which
question depends entirely on who is reading: someone already running a company
gets asked how many people are in it; someone employed gets asked whether they
want out or want to be paid more where they are; someone between roles gets
asked what they can actually commit.

That branching was never going to survive as hardcoded rules — the situations
are too varied and the interesting ones are the combinations. So the model is
given the assessed situation and picks the question. What it is NOT given is
freedom to invent facts: it receives only what we already hold, it must return
a closed question with concrete options, and anything malformed or prescriptive
falls back to a written question chosen from the same situation. The fallback
is a floor, not the design.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .models import DiscoverSession

MAX_OPTIONS = 4
# Two or three is a follow-up; more is an interview, and the audit is already
# on screen behind it.
MAX_QUESTIONS = 3


def assess(db: Session, session: DiscoverSession) -> dict:
    """Everything we already know, in the shape the model is allowed to see.

    Deliberately no free text: the person's own sentences stay out of the
    prompt, so a question can never quote something back at them.
    """
    pc = session.practical_context or {}
    dims = session.dimensions or {}

    def known(dim: str) -> str | None:
        state = dims.get(dim, {})
        if state.get("confidence", 0) < 0.5:
            return None
        return "high" if state.get("estimate", 0) > 0.2 else (
            "low" if state.get("estimate", 0) < -0.2 else "middling")

    from .insights import resolve_field
    occ = resolve_field(db, session)
    answered = dict((pc.get("_situation") or {}))
    asked_text = list(pc.get("_situation_asked") or [])

    return {
        "status": pc.get("current_status"),
        "runsSomething": bool(pc.get("current_status") in ("founder", "freelance")
                              or pc.get("freelance_experience")),
        "hasLedPeople": bool(pc.get("people_management_evidence")),
        "hasBeenPaidForOwnWork": bool(pc.get("commercial_evidence")),
        "worksWithSoftware": bool(pc.get("works_with_software")),
        "buildsThings": bool(pc.get("builds_things")),
        "field": occ.preferred_label if occ else None,
        "fieldSelfEmploymentRate": (round(occ.self_employment_prevalence, 2) if occ else None),
        "timeAvailable": known("time_availability"),
        "moneyPressure": known("income_urgency"),
        "riskAppetite": known("risk_tolerance"),
        "alreadyAnswered": answered,
        "alreadyAskedText": asked_text,
    }


# The floor, never the intent: one written question per situation, used only
# when the model is unavailable or returns something unusable.
def _fallback(a: dict) -> dict | None:
    answered = a.get("alreadyAnswered") or {}

    if a["runsSomething"] and "team_size" not in answered:
        return {"key": "team_size",
                "question": "How many people does it run through right now?",
                "why": "It decides whether the constraint is your hours or other people's clarity.",
                "options": [{"id": "just_me", "label": "Just me"},
                            {"id": "2_5", "label": "2 to 5"},
                            {"id": "6_20", "label": "6 to 20"},
                            {"id": "20_plus", "label": "More than 20"}]}

    if a["status"] in ("employed", "employed_stuck") and "ambition" not in answered:
        return {"key": "ambition",
                "question": "Where would you rather the next two years go?",
                "why": "Earning more where you are and leaving to build need opposite moves.",
                "options": [{"id": "earn_more_employed", "label": "Paid a lot more, still employed"},
                            {"id": "become_founder", "label": "Running my own thing"},
                            {"id": "not_sure", "label": "Genuinely not sure"}]}

    if a["status"] in ("between", "between_roles", "studying") and "commitment" not in answered:
        return {"key": "commitment",
                "question": "What could you actually commit right now?",
                "why": "It separates what's realistic this month from what needs a runway.",
                "options": [{"id": "full_time", "label": "Full time, starting now"},
                            {"id": "part_time", "label": "Part of each week"},
                            {"id": "evenings", "label": "Evenings only"},
                            {"id": "nothing_yet", "label": "Nothing until money is sorted"}]}

    if "focus" not in answered:
        return {"key": "focus",
                "question": "What would make the biggest difference in the next month?",
                "why": "It decides which of these findings is worth acting on first.",
                "options": [{"id": "more_income", "label": "More income"},
                            {"id": "more_control", "label": "More control over my work"},
                            {"id": "more_certainty", "label": "Knowing which direction is right"},
                            {"id": "more_time", "label": "Getting my time back"}]}
    return None


def _valid(q: dict, answered: dict) -> bool:
    """A question is usable only if it is closed, short, and new."""
    from . import content_policy
    if not isinstance(q, dict):
        return False
    key, text = str(q.get("key", "")).strip(), str(q.get("question", "")).strip()
    opts = q.get("options")
    if not key or not text or key in answered:
        return False
    if len(text.split()) > 22 or not isinstance(opts, list):
        return False
    if not (2 <= len(opts) <= MAX_OPTIONS):
        return False
    seen = set()
    for o in opts:
        if not isinstance(o, dict):
            return False
        oid, label = str(o.get("id", "")).strip(), str(o.get("label", "")).strip()
        if not oid or not label or oid in seen or len(label.split()) > 8:
            return False
        seen.add(oid)
    return all(content_policy.validate(t) for t in
               [text, str(q.get("why", "")), *(str(o.get("label")) for o in opts)])


# Words that carry the actual decision. Two questions that both turn on
# leaving-versus-staying are the same question however they are worded, and
# lexical overlap alone does not notice: "do you want out of your job, or to
# earn more where you are" and "would you rather leave software work or earn
# much more" share only "earn".
DECISION_MARKERS = {
    "leave": "exit", "out": "exit", "quit": "exit", "stay": "exit", "leaving": "exit",
    "earn": "money", "pay": "money", "paid": "money", "money": "money", "income": "money",
    "people": "size", "team": "size", "staff": "size", "employees": "size", "many": "size",
    "time": "commitment", "hours": "commitment", "commit": "commitment", "week": "commitment",
    "customers": "demand", "clients": "demand", "demand": "demand", "sell": "demand",
}
REPEAT_OVERLAP = 0.5


def _topics(text: str) -> set[str]:
    return {DECISION_MARKERS[w] for w in
            (t.strip(".,?!").lower() for t in text.split()) if w in DECISION_MARKERS}


def _repeats(question: str, asked: list[str]) -> bool:
    """A backstop, not the primary guard.

    The model is given the questions already asked and told not to repeat them;
    this catches the case where it complies with the letter by inventing a new
    key for the same ask. Two questions count as the same when they turn on the
    same decision, or when their wording overlaps heavily.
    """
    stop = {"you", "your", "do", "to", "or", "the", "a", "of", "in", "and", "want",
            "much", "more", "where", "are", "is", "would", "rather", "right", "now",
            "what", "how", "could", "actually", "does", "it"}
    def words(t):
        return {w.strip(".,?!").lower() for w in t.split()} - stop
    new_w, new_t = words(question), _topics(question)
    if not new_w:
        return True
    for prev in asked:
        if new_t and new_t == _topics(prev):
            return True                      # same decision, different sentence
        old_w = words(prev)
        if old_w and len(new_w & old_w) / max(1, min(len(new_w), len(old_w))) >= REPEAT_OVERLAP:
            return True
    return False


def next_question(db: Session, session: DiscoverSession) -> dict | None:
    """One question, chosen by the model from the assessed situation."""
    from .llm import gateway

    a = assess(db, session)
    answered = a.get("alreadyAnswered") or {}
    if len(answered) >= MAX_QUESTIONS:
        return None
    asked_text = a.get("alreadyAskedText") or []
    out = gateway.generate(db, "situation_probe_v1", {
        "situation": {k: v for k, v in a.items()
                      if k not in ("alreadyAnswered", "alreadyAskedText")},
        "alreadyAsked": sorted(answered.keys()),
        # the wording too, not just the keys: the model happily picked a new key
        # for the same question and asked it twice in a row
        "alreadyAskedQuestions": asked_text,
    })
    if out and _valid(out, answered) and not _repeats(out.get("question", ""), asked_text):
        return {"key": str(out["key"]).strip(),
                "question": str(out["question"]).strip(),
                "why": str(out.get("why", "")).strip(),
                "options": [{"id": str(o["id"]).strip(), "label": str(o["label"]).strip()}
                            for o in out["options"]],
                "source": "generated"}
    written = _fallback(a)
    return {**written, "source": "built"} if written else None


def save_answer(db: Session, session: DiscoverSession, key: str, option_id: str,
                label: str | None = None, question: str | None = None) -> dict:
    """Store it as an explicit fact — they stated it, so it is not inference."""
    from .models import EvidenceItem
    key, option_id = str(key)[:40], str(option_id)[:40]
    if not key or not option_id:
        return {"ok": False}
    pc = dict(session.practical_context or {})
    answered = dict(pc.get("_situation") or {})
    answered[key] = option_id
    pc["_situation"] = answered
    if question:
        pc["_situation_asked"] = (list(pc.get("_situation_asked") or []) + [question])[-6:]
    pc.pop("_materialization", None)          # the page reads from this
    session.practical_context = pc
    db.add(EvidenceItem(session_id=session.id, kind="explicit_fact",
                        claim=f"{key}: {label or option_id}", dims=[],
                        strength=0.7, reliability=0.9))
    db.flush()
    return {"ok": True, "answers": answered}
