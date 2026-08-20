"""Workspace actions that answer with this person's evidence, not with advice.

Several capsules were returning lines that would be equally true for anybody:
"pick the most repetitive hour of your week", "build the smallest version of
one idea in 14 days". They read as a newsletter rather than a reading, and the
person has just spent four chapters giving us the material to do better.

Each function here is built from something specific — the occupation's own
automation and augmentation figures, its self-employment prevalence, the
capabilities the ranker found transferable, the dimensions we are still short
of evidence on — and says which of those it used. Where a fact is missing it
names the gap instead of filling it with a maxim.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .dimensions import DIMENSIONS, dim_phrase
from .models import DiscoverSession


# describe the situation someone is in, not the work they prefer
CIRCUMSTANCE_DIMS = {"time_availability", "capital_availability", "income_urgency",
                     "geographic_access", "credentials", "automation_exposure"}

# the experiment generator falls back to this shape when it has nothing specific
GENERIC_STEP = "two honest hours this week"


def _short_title(name: str, limit: int = 52) -> str:
    """Opportunity names can be a whole problem statement. A title has to be a
    name — the rest belongs in the body."""
    name = (name or "").split(" — ")[0].strip()
    if len(name) <= limit:
        return name
    cut = name[:limit].rsplit(" ", 1)[0]
    return cut + "…"


def _concrete_step(db: Session, session: DiscoverSession, direction: dict) -> str:
    """A real action.

    The generic template ("give X two honest hours this week: sketch the first
    concrete step") told nobody what to actually do. Asking direction_test is
    not enough on its own — with the model unavailable its offline plan echoes
    the very same template back, so the placeholder has to be caught on the way
    out too and replaced with something specific to the direction.
    """
    step = direction.get("firstExperiment") or ""
    if step and GENERIC_STEP not in step:
        return step
    from .explore import direction_test
    step = direction_test(db, session, direction).get("whatYouDo") or ""
    if step and GENERIC_STEP not in step:
        return step
    return _written_step(direction)


def _written_step(direction: dict) -> str:
    """The always-available concrete action, built from the direction itself."""
    name = _short_title(direction.get("name") or direction.get("label") or "this work", 40)
    pathway = (direction.get("pathway") or "").lower()
    if pathway in ("business_ownership", "problem_business", "entrepreneurship", "builder"):
        return (f"Find two people who already pay for {name} work and ask what they paid, "
                "what annoyed them, and who else they considered.")
    if pathway in ("consulting", "contracting", "freelancing"):
        return (f"Quote one real {name} job end to end at the price you'd actually want — "
                "send it, even if you don't win it.")
    if pathway in ("training", "advisory"):
        return f"Teach one session of {name} to one real learner and ask for blunt feedback."
    return (f"Spend one evening on the smallest real piece of {name} work, for one actual "
            "person, and notice what it cost you.")


def _occupation(db: Session, session: DiscoverSession):
    from .insights import resolve_field
    return resolve_field(db, session)


def _posture(db: Session, session: DiscoverSession) -> dict | None:
    from .explore import ai_posture
    occ = _occupation(db, session)
    if not occ:
        return None
    out = ai_posture({"automationExposure": occ.ai_automation_exposure,
                      "augmentationPotential": occ.ai_augmentation_potential})
    out["label"] = occ.preferred_label
    out["selfEmployed"] = occ.self_employment_prevalence
    return out


# ---------------- what am I missing ----------------

def gaps(db: Session, session: DiscoverSession, primary: dict | None, dims: dict) -> dict:
    """Each gap says what it blocks. The old version printed the identical
    sentence — "we still know little about X, a few Questions would sharpen
    this" — once per dimension, which told the reader nothing about why any of
    them mattered or which to answer first."""
    items = []
    if primary and primary.get("skillGaps"):
        have = ", ".join(g.replace("_", " ") for g in primary["skillGaps"][:3])
        items.append(f"For {primary['name']}, the missing pieces are {have}. "
                     "Those are learnable — they're the price of entry, not a verdict.")

    # what each unknown dimension actually decides, so the reader can pick
    BLOCKS = {
        "sales_comfort": "whether anything you run yourself can find customers",
        "risk_tolerance": "whether the bold or the safe version of a direction suits you",
        "time_availability": "what is realistic this quarter rather than one day",
        "capital_availability": "which directions you could start now and which need saving for",
        "revenue_ambition": "whether to build something small and steady or something that scales",
        "leadership": "whether a direction that needs other people is open to you",
        "network": "how long finding the first customer would take",
        "domain_expertise": "how much of your advantage transfers to a new field",
    }
    thin = sorted(((d, v.get("confidence", 0)) for d, v in dims.items()
                   if v.get("confidence", 0) < 0.3 and d in BLOCKS),
                  key=lambda x: x[1])
    for dim, _ in thin[:3]:
        items.append(f"We don't know where you land on {dim_phrase(dim, 1)}, and that "
                     f"decides {BLOCKS[dim]}.")
    if not thin:
        # everything we track is evidenced; the honest gap is elsewhere
        items.append("Nothing in your own answers is thin enough to be holding you back. "
                     "What's missing now is outside evidence, not more questions.")

    occ = _occupation(db, session)
    if not occ:
        items.append("We haven't matched your work to a field we hold data for, so none of "
                     "the market numbers apply to you yet — that's the biggest single gap.")
    return {"kind": "list", "headline": "What am I missing?", "items": items,
            "note": "Each one names what it decides, so you can answer the one that matters."}


# ---------------- my best next move ----------------

def next_move(db: Session, session: DiscoverSession, primary: dict) -> dict:
    """One step, sized to the time they actually said they have."""
    dims = session.dimensions or {}
    time_state = dims.get("time_availability", {})
    scarce = time_state.get("confidence", 0) >= 0.5 and time_state.get("estimate", 0) < 0
    step = _concrete_step(db, session, primary)
    posture = _posture(db, session)

    window = ("You told us your time comes in scraps, so this is sized to fit one evening."
              if scarce else "You have real hours, so give this one proper sitting rather than five interrupted ones.")
    lines = [step, window]
    if posture:
        lines.append(f"Doing it now: {posture['reading']}")
    if primary.get("skillGaps"):
        lines.append(f"You'll hit {primary['skillGaps'][0].replace('_', ' ')} while doing it. "
                     "That's the point — it turns a guess into a known cost.")
    return {"kind": "list", "headline": "My best next move",
            "title": _short_title(primary.get("name", "")) or "Your strongest direction",
            "items": lines,
            "note": "One step, chosen from your top-ranked direction and sized to your week."}


# ---------------- turning expertise into income ----------------

def expertise_income(db: Session, session: DiscoverSession, lives: list) -> dict:
    """Grounded in how much of THIS field actually works for itself."""
    pc = session.practical_context or {}
    posture = _posture(db, session)
    consult = next((l for l in lives if l.get("pathway") == "consulting"), None)
    items = []

    if posture:
        pct = int(round((posture.get("selfEmployed") or 0) * 100))
        items.append(f"About {pct}% of {posture['label']} work already happens independently — "
                     + ("so there is a well-worn route here, not an experiment."
                        if pct >= 40 else
                        "so this is proven but uncommon; expect to explain yourself more."))
    if pc.get("commercial_evidence"):
        items.append("People have already paid you. The question isn't whether you can charge, "
                     "it's whether you can charge repeatably — which is a different problem.")
    else:
        items.append("Nobody has paid you for this yet, so the first job isn't scale — it's one "
                     "person paying once, which tells you more than any amount of planning.")
    if posture and posture["posture"] == "amplified":
        items.append("Tools cover the admin around this work, which is what usually stops people "
                     "going independent — not the craft, the invoicing and scheduling.")
    if consult:
        items.append(f"The shape the ranker found for you: {consult['name']}. {consult.get('whyYou', '')}")
    items.append("First revenue is evidence, not commitment. One paid job proves the market "
                 "exists; it doesn't oblige you to leave anything.")
    return {"kind": "list", "headline": "Turn my expertise into income",
            "title": _short_title(consult["name"]) if consult else "The first paid version",
            "items": items, "note": "Built from your field's own independence rate."}


# ---------------- build something ----------------

def build_something(db: Session, session: DiscoverSession, lives: list) -> dict:
    """Says what to build, from their evidence — not "build the smallest thing"."""
    builder = next((l for l in lives if l.get("pathway") in
                    ("builder", "entrepreneurship", "business_ownership", "problem_business")), None)
    posture = _posture(db, session)
    dims = session.dimensions or {}
    items = []

    if builder:
        why = (builder.get("whyYou") or "").strip()
        why = (why[0].upper() + why[1:]) if why else ""
        items.append(f"The build the evidence points at: {_short_title(builder['name'], 90)}."
                     + (f" {why}" if why else ""))
        items.append(f"First version: {_concrete_step(db, session, builder)}")
    elif posture:
        items.append(f"Nothing in your answers points at a specific product yet, but "
                     f"{posture['label']} work has a natural first build: the thing you "
                     "currently do by hand for every customer.")
    else:
        items.append("We can't yet see which build fits you rather than anybody — the "
                     "questions about time, money and risk are the ones that decide it.")

    capital = dims.get("capital_availability", {})
    if capital.get("confidence", 0) >= 0.5:
        items.append("You have resources to put in — which buys speed, not certainty. "
                     "Spend them on finding out you're wrong faster."
                     if capital.get("estimate", 0) > 0 else
                     "You're starting lean, so the build has to pay for itself early. "
                     "That rules out anything needing an audience before it earns.")
    if posture and posture["posture"] == "exposed":
        items.append("Be careful what you build here: the part that is easiest to build is "
                     "also the part machines are getting good at.")
    return {"kind": "list", "headline": "Build something",
            "title": _short_title(builder["name"]) if builder else "What to build first",
            "items": items, "note": "Ship rough. Learn real."}


# ---------------- AI leverage ----------------

def ai_leverage(db: Session, session: DiscoverSession, dims: dict) -> dict:
    """The real exposure and augmentation numbers for their field, not maxims."""
    posture = _posture(db, session)
    comfort = dims.get("ai_leverage", {})
    items = []

    if not posture:
        items.append("We haven't matched your work to a field we hold AI figures for, so "
                     "anything here would be the same advice everyone gets. Tell us what "
                     "you do and this becomes specific.")
        return {"kind": "list", "headline": "AI leverage", "items": items,
                "note": "Deliberately blank rather than generic."}

    items.append(f"{posture['label']}: automation exposure {posture['automationExposure']}, "
                 f"augmentation potential {posture['augmentationPotential']}. {posture['reading']}")
    if posture["posture"] == "amplified":
        items.append("Concretely: the tools should be taking the quoting, scheduling, notes and "
                     "follow-ups — not the judgement calls people are actually paying for.")
    elif posture["posture"] == "exposed":
        items.append("Concretely: the safest move is owning the customer relationship and the "
                     "decision, and letting the tools do the produced work underneath.")
    else:
        items.append("Concretely: tools won't change what you sell here. They change how many "
                     "people you can reach with it.")
    if comfort.get("confidence", 0) >= 0.5:
        items.append("You're already comfortable with these tools, so the gap isn't skill — "
                     "it's picking one workflow and finishing it."
                     if comfort.get("estimate", 0) > 0.2 else
                     "You lean toward work that stays human. That's a position, not a "
                     "weakness — but pick one repetitive hour and let a tool have it.")
    return {"kind": "list", "headline": "AI leverage", "items": items,
            "note": f"From {posture['label']}'s own exposure and augmentation figures."}
