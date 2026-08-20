"""The OPERATOR branch — for people who already run something.

Someone running their own business is not a job-seeker, and the four chapters
did not spend their time earning the right to give them career advice. What we
can honestly offer them is narrower and more useful:

    WHAT YOUR OWN EVIDENCE SHOWS YOU'RE STRONG AT
    WHAT IT SHOWS IS THIN
    WHAT THE MARKET DATA ACTUALLY SAYS ABOUT THAT SPACE  (or, loudly, that we
                                                          don't have it)
    A FEW QUESTIONS ABOUT HOW YOU RUN IT
    THE UNBIFY SURFACES THAT FIT WHAT YOU JUST DESCRIBED

Every claim here is either derived from the user's own answers or read off a
persisted market signal with its provenance attached. The market half abstains
by default: an unsupported claim about someone's own industry is the single
fastest way to lose a person who actually works in it.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from . import thresholds as th
from .dimensions import DIMENSIONS, dim_phrase
from .models import DiscoverSession, EvidenceItem, WICapability
from .signals import top_dims

# a market claim needs more than one source before it is worth a sentence
MIN_SOURCES_FOR_CLAIM = 2
MIN_CONFIDENCE_FOR_CLAIM = 0.40


def is_operator(session: DiscoverSession) -> bool:
    """Already running something, on their own say-so."""
    pc = session.practical_context or {}
    return (pc.get("current_status") in ("founder", "freelance")
            or bool(pc.get("freelance_experience"))
            or bool(pc.get("runs_business")))


# ---------------- what the evidence says they're strong at ----------------

def strengths(db: Session, session: DiscoverSession) -> list[dict]:
    """Capability clusters, each with the thing that actually supports it.

    Reuses the same capability vector the rest of materialization uses, so an
    operator and a job-seeker are read by identical machinery — only the
    framing downstream differs.
    """
    from .world.ontology import user_capability_vector
    vec = user_capability_vector(db, session)
    pc = session.practical_context or {}
    out = []
    for cap_id, weight in sorted(vec.items(), key=lambda kv: -kv[1])[:5]:
        if weight < 0.4:
            continue
        cap = db.get(WICapability, cap_id)
        label = (cap.label if cap else cap_id.replace("_", " ")).capitalize()
        out.append({
            "key": cap_id, "label": label, "weight": round(weight, 2),
            "strength": "strong" if weight >= 0.7 else "present",
        })
    backing = _backing_lines(pc)
    for i, card in enumerate(out):
        card["inYourBusiness"] = backing[i % len(backing)]
    return out


def _backing_lines(pc: dict) -> list[str]:
    """Every true statement we can make about where these capabilities come from.

    Returning the first match for all of them printed the same sentence under
    every card, which reads like a template rather than a reading of the person.
    """
    lines = []
    if pc.get("commercial_evidence"):
        lines.append("people have paid you for this, which beats any other kind of proof")
    if pc.get("builds_things") or pc.get("hands_on_technical"):
        lines.append("it shows in the work you do yourself, not the bits you hand off")
    if pc.get("coordinates_delivery"):
        lines.append("it shows in how you get work finished and out")
    if pc.get("people_management_evidence"):
        lines.append("you've done this with other people depending on you")
    if pc.get("freelance_experience"):
        lines.append("you've done this without a company around you to fall back on")
    if pc.get("years_mentioned"):
        lines.append(f"{pc['years_mentioned']} years of doing it is the evidence")
    lines.append("it came up again and again in your answers")
    return lines


def thin_spots(db: Session, session: DiscoverSession) -> list[dict]:
    """Where the business is exposed — stated as unknowns, never as failings.

    A weakness we have not evidenced is an insult, not an insight; each entry
    below names the specific thing we have not seen rather than diagnosing the
    person.
    """
    dims = session.dimensions or {}
    pc = session.practical_context or {}
    out = []
    watch = [
        ("sales_comfort", "Getting in front of new customers",
         "nothing you've told us shows how you feel about selling, and for an owner that "
         "sets the ceiling more than skill does"),
        ("capital_availability", "What you could afford to put in",
         "we don't know what money you could put in, so we can't tell a cheap test from "
         "an expensive one"),
        ("time_availability", "The hours the business actually leaves you",
         "we don't know what your week looks like, and that decides what's doable now "
         "rather than one day"),
        ("leadership", "Whether this can grow past you",
         "we haven't seen how you get things done through other people"),
        ("revenue_ambition", "How big you actually want this",
         "a business meant to stay small and one meant to grow need opposite decisions"),
    ]
    for dim, label, why in watch:
        state = dims.get(dim, {})
        if state.get("confidence", 0) >= th.MAY_TEST:
            continue                     # we know this one; it isn't a blind spot
        out.append({"key": dim, "label": label, "why": why})
    if pc.get("people_management_evidence"):
        out = [o for o in out if o["key"] != "leadership"]
    return out[:3]


# ---------------- what the market data actually says ----------------

def market_standing(db: Session, session: DiscoverSession) -> dict:
    """The honest state of our market evidence for this person's own field.

    This deliberately refuses to produce a headline unless real, multi-source
    evidence exists. The person reading it works in this industry every day —
    they will know instantly if we are bluffing, and everything else on the
    page loses its credibility with it.
    """
    from .world import signals as world_signals
    from .world.ontology import resolve_title
    from .models import WISource

    pc = session.practical_context or {}
    title = pc.get("current_occupation_title")
    occupation_id = occupation_label = None
    ambiguous: list[str] = []
    if title:
        res = resolve_title(db, str(title))
        cands = res.get("candidates") or []
        if res.get("status") == "resolved" and cands:
            occupation_id = cands[0].get("occupationId")
            occupation_label = cands[0].get("label")
        elif res.get("status") == "ambiguous":
            # picking the first of several would be a coin flip presented as a
            # fact — name the fork instead and let the user settle it
            ambiguous = [c.get("label") for c in cands if c.get("label")]

    if not occupation_id:
        return {"status": "ambiguous_occupation" if ambiguous else "no_occupation",
                "heading": "What the market says",
                "occupation": None,
                "ambiguousBetween": ambiguous,
                "note": (
                    "Your title could mean " + " or ".join(ambiguous[:3]) +
                    ", and those are different markets. Tell us which and we can "
                    "read the real numbers for it."
                    if ambiguous else
                    "We haven't pinned down which market you're actually in yet, "
                    "so there's nothing here we could say accurately."),
                "readings": []}

    readings = []
    for construct, label in (("demand_direction", "Demand"),
                             ("posting_volume", "Hiring activity"),
                             ("self_employment_prevalence", "How much of this field works for itself")):
        sig = world_signals.signal_for(db, occupation_id, construct)
        if not sig:
            continue
        src_types = set()
        for obs_id in (sig.evidence_refs or []):
            from .models import WISourceObservation
            obs = db.get(WISourceObservation, obs_id)
            if obs:
                src = db.get(WISource, obs.source_id)
                if src:
                    src_types.add(src.name)
        usable = (sig.source_count >= MIN_SOURCES_FOR_CLAIM
                  and sig.confidence >= MIN_CONFIDENCE_FOR_CLAIM)
        readings.append({
            "construct": construct, "label": label,
            "value": round(sig.value, 2), "confidence": round(sig.confidence, 2),
            "sourceCount": sig.source_count, "sourceDiversity": sig.source_diversity,
            "sources": sorted(src_types),
            "freshnessDays": world_signals.freshness_days(sig),
            "geography": sig.geography, "geographyLevel": sig.geography_level,
            "conflicts": sig.conflicts or [],
            # the reading is only allowed to become a sentence if it is earned
            "usable": usable,
            "reading": _reading_sentence(construct, sig.value) if usable else None,
        })

    usable = [r for r in readings if r["usable"]]
    if not usable:
        weak = len(readings)
        return {
            "status": "insufficient_market_evidence",
            "heading": "What the market says",
            "occupation": occupation_label,
            "note": (
                f"We hold {weak} baseline reading(s) for {occupation_label} and none of them "
                f"clear the bar to be stated as fact — they come from a single seeded source, "
                f"not from live market data. Rather than dress that up: we don't yet know how "
                f"much room this space has."
                if weak else
                f"We have no market observations for {occupation_label} yet. "
                "Saying anything about its size or direction would be invention."),
            "readings": readings,
        }
    return {"status": "ok", "heading": "What the market says",
            "occupation": occupation_label, "note": None, "readings": readings}


def _reading_sentence(construct: str, value: float) -> str:
    """Plain language for an earned reading — bounded, never inflated."""
    if construct == "demand_direction":
        return ("demand is growing" if value >= 0.65 else
                "demand is holding steady" if value >= 0.45 else "demand is softening")
    if construct == "posting_volume":
        return ("hiring activity is high" if value >= 0.65 else
                "hiring activity is moderate" if value >= 0.4 else "hiring activity is low")
    if construct == "self_employment_prevalence":
        return (f"about {int(round(value * 100))}% of this field works independently"
                if value > 0 else "independent work is uncommon here")
    return "reading available"


# ---------------- the follow-up probe ----------------
#
# Short, adaptive, and only asked once the person opts in by clicking through.
# Each answer must change something downstream — a question whose answer we
# would ignore is a question we have no business asking.

PROBE_STEPS: list[dict] = [
    {"id": "shape", "question": "How are you running it right now?",
     "options": [{"id": "solo", "label": "Just me"},
                 {"id": "team", "label": "Me and a team"},
                 {"id": "partners", "label": "Me and co-founders"}]},
    {"id": "team_size", "question": "Roughly how many people?",
     "dependsOn": {"shape": ["team", "partners"]},
     "options": [{"id": "2_5", "label": "2–5"}, {"id": "6_20", "label": "6–20"},
                 {"id": "20_plus", "label": "More than 20"}]},
    {"id": "solo_load", "question": "What eats most of your week?",
     "dependsOn": {"shape": ["solo"]},
     "options": [{"id": "delivery", "label": "Doing the actual work"},
                 {"id": "finding", "label": "Finding the next customer"},
                 {"id": "admin", "label": "Admin and coordination"}]},
    {"id": "funding", "question": "Anyone else's money in it?",
     "options": [{"id": "bootstrapped", "label": "No — it's mine"},
                 {"id": "investors", "label": "Yes, investors"},
                 {"id": "raising", "label": "Not yet, but raising"}]},
    {"id": "friction", "question": "What's the thing that keeps not getting done?",
     "options": [{"id": "knowledge", "label": "Everything lives in my head"},
                 {"id": "capacity", "label": "Not enough hands"},
                 {"id": "demand", "label": "Not enough demand"},
                 {"id": "focus", "label": "Too many directions at once"}]},
]


def next_probe_step(answers: dict) -> dict | None:
    """The next question worth asking, given what's been answered. Returns None
    when the probe is complete — the flow never pads itself to a fixed length."""
    for step in PROBE_STEPS:
        if step["id"] in answers:
            continue
        dep = step.get("dependsOn")
        if dep:
            if not all(answers.get(k) in v for k, v in dep.items()):
                continue
        return {"id": step["id"], "question": step["question"],
                "options": step["options"],
                "stepIndex": len([s for s in PROBE_STEPS if s["id"] in answers]) + 1}
    return None


def save_probe(db: Session, session: DiscoverSession, step_id: str, option_id: str) -> dict:
    """Persist one probe answer as an explicit fact — the user stated it, so it
    carries explicit-fact reliability, not inference."""
    valid = next((s for s in PROBE_STEPS if s["id"] == step_id), None)
    if not valid or option_id not in {o["id"] for o in valid["options"]}:
        return {"ok": False, "error": "unknown step or option"}
    pc = dict(session.practical_context or {})
    probe = dict(pc.get("_venture_probe") or {})
    probe[step_id] = option_id
    pc["_venture_probe"] = probe
    session.practical_context = pc
    label = next(o["label"] for o in valid["options"] if o["id"] == option_id)
    db.add(EvidenceItem(session_id=session.id, kind="explicit_fact",
                        claim=f"{valid['question']} {label}", dims=[],
                        strength=0.7, reliability=0.9))
    db.flush()
    return {"ok": True, "answers": probe, "next": next_probe_step(probe)}


def probe_answers(session: DiscoverSession) -> dict:
    return dict((session.practical_context or {}).get("_venture_probe") or {})


def probe_read(answers: dict) -> str | None:
    """One honest sentence back, so the questions visibly did something."""
    if not answers:
        return None
    shape, friction = answers.get("shape"), answers.get("friction")
    bits = []
    if shape == "solo":
        bits.append("You're carrying the whole thing yourself")
        if answers.get("solo_load") == "delivery":
            bits.append("and the delivery work is eating the week that would grow it")
        elif answers.get("solo_load") == "finding":
            bits.append("and the search for the next customer never really stops")
        elif answers.get("solo_load") == "admin":
            bits.append("and coordination is taking the hours the actual work should get")
    elif shape in ("team", "partners"):
        size = {"2_5": "a small team", "6_20": "a real team",
                "20_plus": "an organisation"}.get(answers.get("team_size"), "a team")
        bits.append(f"You're running this through {size}")
        if answers.get("team_size") == "20_plus":
            bits.append("which means your leverage is now other people's clarity, not your own output")
    if friction == "knowledge":
        bits.append("and everything the others need to know is still in your head")
    elif friction == "capacity":
        bits.append("and the constraint is hands, not ideas")
    elif friction == "demand":
        bits.append("and the constraint is demand, which no amount of internal tidying fixes")
    elif friction == "focus":
        bits.append("and there are more live directions than one person can hold")
    if answers.get("funding") == "investors":
        bits.append("with other people's money and the reporting that comes with it")
    elif answers.get("funding") == "raising":
        bits.append("while trying to raise")
    if not bits:
        return None
    return (bits[0] + (" " + ", ".join(bits[1:]) if len(bits) > 1 else "")).strip() + "."


# ---------------- UNBIFY surfaces ----------------
#
# All five are pre-launch. They are presented as coming soon with no link,
# because claiming availability we don't have would undo the one thing this
# whole product is built on. `url` stays None until real destinations exist.

SURFACES: dict[str, dict] = {
    "brain": {
        "name": "Unbify Brain",
        "line": "Everything your company knows, in one place.",
        "detail": "Notes, meetings, boards and tools in one place. A bot sits in your "
                  "meetings and writes down what was decided, a board tracks it, "
                  "your other tools plug in, and slide decks come out of what's "
                  "already there. It does things, not just stores them.",
        "url": None, "status": "coming_soon",
    },
    "suite": {
        "name": "Unbify Suite",
        "line": "Post the problem you actually have.",
        "detail": "Where owners go to find a fix for the thing that's blocking them, "
                  "or post the problem and let people come to them.",
        "url": None, "status": "coming_soon",
    },
    "marketplace": {
        "name": "Unbify Marketplace",
        "line": "People who can take the work off your plate.",
        "detail": "Developers and builders pick up jobs people have posted, or get hired "
                  "directly. The part you'd rather pay for than learn.",
        "url": None, "status": "coming_soon",
    },
    "gtr": {
        "name": "Go To Retreats",
        "line": "Somewhere to actually stop.",
        "detail": "Retreats, for when the honest answer is that you haven't properly "
                  "stopped in a long time.",
        "url": None, "status": "coming_soon",
    },
    "affiliate": {
        "name": "Unbify Affiliate Marketplace",
        "line": "If your following is the asset.",
        "detail": "For people with a following who want it to earn without turning into "
                  "a full-time shop.",
        "url": None, "status": "coming_soon",
    },
}


def surfaces_for(db: Session, session: DiscoverSession, answers: dict,
                 strength_keys: list[str] | None = None) -> list[dict]:
    """Route to surfaces from what the operator actually told us.

    A surface appears only with a stated reason tied to a specific answer. No
    reason, no card — the same rule the rest of product routing already obeys.
    """
    pc = session.practical_context or {}
    dims = session.dimensions or {}
    picked: list[tuple[str, str, float]] = []      # (key, because, weight)

    friction, shape = answers.get("friction"), answers.get("shape")
    size, funding = answers.get("team_size"), answers.get("funding")

    if friction == "knowledge":
        picked.append(("brain", "you said everything is still in your head", 0.95))
    elif shape in ("team", "partners") or size:
        picked.append(("brain", "once more than one person is involved, everyone needs the "
                                "same information in the same place", 0.7))
    if funding == "investors":
        picked.append(("brain", "investors mean reporting, and reporting means someone has to be able "
                                "to find things", 0.75))

    if friction == "capacity":
        picked.append(("marketplace", "you said the constraint is hands, not ideas", 0.9))
    elif answers.get("solo_load") == "delivery":
        picked.append(("marketplace", "doing the work yourself is eating the week you'd "
                                      "otherwise spend growing it", 0.8))

    if friction == "demand" or answers.get("solo_load") == "finding":
        picked.append(("suite", "the thing holding you back is demand, and that's worth "
                                "putting in front of people who fix it", 0.85))
    elif friction == "focus":
        picked.append(("suite", "with several things on the go at once, the cheapest move is to "
                                "describe the problem and see what comes back", 0.7))

    # GTR is only honest when something in the evidence points at load, never
    # as a lifestyle upsell bolted onto every result
    stretched = (shape == "solo" and friction in ("capacity", "knowledge")) or size == "20_plus"
    peace = dims.get("stability", {}).get("estimate", 0) > 0.2 or \
        dims.get("autonomy", {}).get("estimate", 0) > 0.4
    if stretched and peace:
        picked.append(("gtr", "you're carrying a lot of this yourself, and your answers lean "
                              "toward wanting less on your plate, not more", 0.6))

    if (strength_keys and any("content" in k or "audience" in k or "market" in k
                              for k in strength_keys)) or \
            dims.get("audience", {}).get("estimate", 0) > 0.3 or pc.get("audience_evidence"):
        picked.append(("affiliate", "you already have people following you, which most owners "
                                    "have to build from nothing", 0.65))

    best: dict[str, tuple[str, float]] = {}
    for key, because, weight in picked:
        if key not in best or weight > best[key][1]:
            best[key] = (because, weight)
    out = []
    for key, (because, weight) in sorted(best.items(), key=lambda kv: -kv[1][1])[:3]:
        s = SURFACES[key]
        out.append({"key": key, "name": s["name"], "line": s["line"],
                    "detail": s["detail"], "status": s["status"], "url": s["url"],
                    "because": because.capitalize() + ".",
                    "relevance": round(weight, 2)})
    return out
