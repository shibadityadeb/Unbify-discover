"""The long list: ten directions, and what AI does to each of them.

"Explore my possibilities" returned three cards. The ask was for a proper
ranked list with an AI-era read per field, which the data supports — the
matching pipeline already computes capability fit, transferable capabilities,
missing ones, licensing, self-employment prevalence and per-occupation
automation/augmentation figures for every occupation we hold.

What it does NOT support is calling them "rising". Rising is a claim about
demand over time, and every demand signal we hold comes from a single seeded
source below the display threshold. So the list is ranked by what is actually
knowable — how well it fits this person, and how the work sits against AI —
and the demand column says plainly that it is missing rather than sorting by a
number that would be invented.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .models import DiscoverSession

TOP_N = 10

# a demand reading needs more than the seeded baseline before it is worth stating
MIN_DEMAND_SOURCES = 2
MIN_DEMAND_CONFIDENCE = 0.40


def ai_posture(ai: dict, label: str | None = None) -> dict:
    """Where a field sits against automation — the part of "in the age of AI"
    we can answer from data rather than atmosphere. With a label, the reading
    names the field and carries its own numbers, so ten rows never share one
    interchangeable sentence."""
    exposure = float(ai.get("automationExposure") or 0)
    augment = float(ai.get("augmentationPotential") or 0)
    edge = augment - exposure
    name = label or "this work"
    figures = f"automation exposure {exposure:.0%}, AI leverage {augment:.0%}"
    if exposure >= 0.6 and edge <= 0:
        posture = "exposed"
        line = (f"Machines are getting good at the core of {name} ({figures}). The durable "
                "income is in the parts that stay human, or in running the tools.")
    elif edge >= 0.2:
        posture = "amplified"
        line = (f"AI multiplies {name} rather than replacing it ({figures}) — "
                "same craft, more of it per week.")
    elif exposure <= 0.25:
        posture = "insulated"
        line = (f"Tools move {name} slowly ({figures}). Growth comes from being good "
                "and reaching more people, not from automating.")
    else:
        posture = "mixed"
        line = (f"Parts of {name} will be automated and parts will not ({figures}) — "
                "which half you sit in is a choice you still get to make.")
    return {"posture": posture, "reading": line,
            "automationExposure": round(exposure, 2),
            "augmentationPotential": round(augment, 2),
            "aiEdge": round(edge, 2)}


def _demand_state(market: dict) -> dict:
    demand, conf = market.get("demand"), float(market.get("confidence") or 0)
    if demand is None:
        return {"status": "unavailable", "label": "no demand data",
                "note": "We hold no demand observations for this field."}
    # a single seeded source is a baseline, not evidence of a trend
    if conf < MIN_DEMAND_CONFIDENCE:
        return {"status": "unavailable", "label": "not enough sources",
                "note": f"One seeded reading ({demand:.2f}) — below the bar to state as fact."}
    return {"status": "known", "value": round(float(demand), 2),
            "label": ("growing" if demand >= 0.65 else
                      "steady" if demand >= 0.45 else "softening"),
            "note": f"Refreshed {market.get('freshnessDays')}d ago."}


def _score(c: dict) -> float:
    """Ranked on what is knowable: fit first, then how the work sits against AI,
    then whether it is a documented step from where they already are — and,
    only where multiple named sources actually back it, where demand is going."""
    ai = ai_posture(c.get("ai") or {})
    score = c.get("capabilityFit", 0) * 2.0
    score += ai["aiEdge"] * 0.8
    score -= max(0.0, ai["automationExposure"] - 0.5) * 1.2
    market = c.get("market") or {}
    if (market.get("demand") is not None
            and float(market.get("confidence") or 0) >= MIN_DEMAND_CONFIDENCE):
        score += (float(market["demand"]) - 0.45) * 0.9
    if c.get("isCurrentField"):
        score += 0.35
    if c.get("isKnownTransition"):
        score += 0.30
    if not (c.get("licensing") or {}).get("eligible", True):
        score -= 0.9
    score -= 0.05 * len(c.get("missing") or [])
    return score


def possibilities(db: Session, session: DiscoverSession) -> dict:
    """Up to ten directions, each with its AI posture and an honest demand cell."""
    from .world.matching import generate_candidates

    # a wider net than ranking uses: this view exists to show adjacent ground,
    # and every row states its own fit so a weak match cannot masquerade
    gen = generate_candidates(db, session, min_fit=0.06)
    candidates = gen.get("candidates") if isinstance(gen, dict) else gen
    if not candidates:
        return {"status": "insufficient_evidence", "items": [],
                "note": "We can't yet see enough of what you can do to rank anything "
                        "against it responsibly."}

    ranked = sorted(candidates, key=_score, reverse=True)
    items, seen = [], set()
    for c in ranked:
        key = (c.get("occupationId"), c.get("pathway"))
        if key in seen or c.get("occupationId") in {i["occupationId"] for i in items}:
            continue                      # one row per occupation, best pathway wins
        seen.add(key)
        ai = ai_posture(c.get("ai") or {}, c.get("label"))
        demand = _demand_state(c.get("market") or {})
        if demand["status"] == "known" and c.get("occupationId"):
            from .world import signals as wsignals
            sig = wsignals.signal_for(db, c["occupationId"], "demand_direction")
            demand["evidence"] = wsignals.demand_evidence(db, sig)
        items.append({
            "occupationId": c.get("occupationId"),
            "label": c.get("label"),
            "pathway": c.get("pathwayLabel") or c.get("pathway"),
            "fit": round(float(c.get("capabilityFit") or 0), 2),
            "youAlreadyHave": [t.replace("_", " ") for t in (c.get("transfers") or [])][:3],
            "missing": [m.replace("_", " ") for m in (c.get("missing") or [])][:3],
            "ai": ai,
            "demand": demand,
            "selfEmployed": round(float(c.get("selfEmployment") or 0), 2),
            "licensed": bool((c.get("licensing") or {}).get("required")),
            "isStepFromHere": bool(c.get("isKnownTransition")) or bool(c.get("isCurrentField")),
            "fitLabel": ("strong overlap" if float(c.get("capabilityFit") or 0) >= 0.45
                         else "partial overlap" if float(c.get("capabilityFit") or 0) >= 0.2
                         else "thin overlap — exploratory"),
        })
        if len(items) >= TOP_N:
            break

    known_demand = sum(1 for i in items if i["demand"]["status"] == "known")
    return {
        "status": "ok",
        "items": items,
        "rankedBy": ("fit to what you can already do, how the work sits against AI, "
                     "and — where multiple named sources back it — where demand is heading"
                     if known_demand else
                     "how well it fits what you can already do, and how the work sits against AI"),
        "demandCoverage": {"known": known_demand, "total": len(items)},
        "honesty": (
            "Ranked on fit and AI posture — not on which fields are rising. "
            f"We hold usable demand data for {known_demand} of {len(items)}, so sorting "
            "by growth would be inventing the very thing you'd be relying on."
            if known_demand < len(items) else
            "Fit, AI posture and current demand all had data behind them."),
    }


# ---------------- testing one direction ----------------

def direction_test(db: Session, session: DiscoverSession, direction: dict) -> dict:
    """A week-sized experiment for one direction, detailed enough to act on.

    "Timebox it: two evenings" was not a plan — it said nothing about what the
    week would settle, what would kill the idea, or what tools change about
    doing it now. The deterministic version below is always available; the LLM
    only sharpens the specifics, and anything it returns that fails the content
    policy is discarded rather than shown.
    """
    from . import content_policy
    from .llm import gateway

    name = direction.get("name") or direction.get("label") or "this direction"
    first = (direction.get("firstExperiment")
             or (direction.get("experiment") or {}).get("action")
             or "Do the smallest real version of this work, once, for someone real.")
    missing = direction.get("skillGaps") or direction.get("missing") or []
    posture = direction.get("ai") or {}
    if not posture and direction.get("occupationId"):
        from .models import WIOccupation
        occ = db.get(WIOccupation, direction["occupationId"])
        if occ:
            posture = ai_posture({"automationExposure": occ.ai_automation_exposure,
                                  "augmentationPotential": occ.ai_augmentation_potential})

    fallback = {
        "direction": name,
        "whatYouDo": first,
        "proves": f"Whether the day-to-day of {name} is what you're picturing.",
        "rulesOut": ("Whether the appeal survives contact with the actual work — "
                     "if it doesn't, you've saved months."),
        "aiAngle": posture.get("reading") or
                   "Current tools change the admin around this work more than the work itself.",
        "successLooks": "One finished piece of real work, and one person's honest reaction to it.",
        "ifItWorks": "Do it twice more before changing anything structural.",
        "ifItDoesnt": "The direction was wrong, not you — and it cost a week, not a year.",
        "cost": "A week of evenings. No money committed, nothing announced, fully reversible.",
        "missing": [m.replace("_", " ") for m in missing][:3],
        "source": "built",
    }

    out = gateway.generate(db, "direction_test_v1", {
        "direction": name,
        "firstStep": first,
        "missingCapabilities": [m.replace("_", " ") for m in missing][:3],
        "aiPosture": {"posture": posture.get("posture"), "reading": posture.get("reading")},
    })
    if not out:
        return fallback
    required = ("whatYouDo", "proves", "rulesOut", "aiAngle",
                "successLooks", "ifItWorks", "ifItDoesnt")
    shaped = {k: str(out.get(k, "")).strip() for k in required}
    # a half-filled plan is worse than the written one: it looks bespoke and
    # then stops exactly where the person needs it most
    if not all(shaped.values()):
        return fallback
    if not all(content_policy.validate(v) for v in shaped.values()):
        return fallback
    return {**fallback, **shaped, "source": "generated"}
