"""Experiment generator.

OPPORTUNITY + USER CONSTRAINTS + CURRENT ASSETS + MISSING EVIDENCE
        ↓
"What is the cheapest, safest action that would teach us whether this
 opportunity deserves more attention?"

Experiments are specific to the direction and to what we don't yet know.
Generic "spend two hours exploring it" is only ever used when two hours is
genuinely the honest answer — and never as a filler.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .models import DiscoverSession

# what a missing capability is cheapest to test WITH — keyed by capability id
CAPABILITY_TESTS = {
    "customer_acquisition": ("Ask three people who match your likely customer what they "
                             "currently pay someone else to do", "whether demand exists before you build anything"),
    "sales_selling": ("Quote one real job end to end — even if you don't win it",
                      "how you actually feel about asking for money"),
    "estimating_pricing": ("Price one job the way you would if it were yours",
                           "whether pricing is a skill gap or just unfamiliar"),
    "people_leadership": ("Take responsibility for one other person's output for two weeks",
                          "whether managing people energizes or drains you"),
    "crew_supervision": ("Run one job with a second pair of hands you direct",
                         "whether you want a crew or prefer working alone"),
    "teaching_instruction": ("Teach one session to one real learner and ask for blunt feedback",
                             "whether teaching is something you'd want repeatedly"),
    "training_delivery": ("Run a single practical training session for one person",
                          "whether the training path is worth pursuing"),
    "business_administration": ("Do one month of your own books by hand",
                                "whether the admin side is tolerable at scale"),
    "software_construction": ("Ship the smallest version of one idea to one real user",
                              "whether you finish things once they stop being fun"),
    "project_management": ("Own the plan for one small piece of work end to end",
                           "whether coordinating is a fit or a chore"),
    "clinical_assessment": ("Shadow a colleague in the specialization for one session",
                            "what the daily reality of that specialization is"),
    "legal_analysis": ("Take one matter in the adjacent practice area under supervision",
                       "whether the subject matter holds your interest"),
    "financial_analysis": ("Analyze one real set of numbers you don't already know",
                           "whether the analytical depth suits you"),
    "installation_work": ("Do one supervised install in the new specialization",
                          "whether the hands-on work transfers as cleanly as it looks"),
    "systems_troubleshooting": ("Diagnose one unfamiliar system without help",
                                "how far your troubleshooting transfers"),
}

# per-pathway experiment shapes, most specific first
PATHWAY_TESTS = {
    "business_ownership": ("Talk to three people who already run this kind of business "
                           "and ask what they'd do differently", "the real economics before you commit capital"),
    "practice_ownership": ("Sit down with one person who runs their own practice and ask "
                           "about the first two years", "the operating reality behind the independence"),
    "contracting": ("Take one contract job on your own terms — one client, one scope, one price",
                    "whether independent work suits you before you leave anything behind"),
    "freelancing": ("Land one paid freelance engagement, however small",
                    "whether clients come to you, and how that feels"),
    "consulting": ("Offer one free diagnostic conversation to a business in your field",
                   "whether people value your judgment enough to pay for it later"),
    "specialization": ("Spend one job or one week doing only the specialized work",
                       "whether the narrower focus energizes or bores you"),
    "employment": ("Talk to two people currently doing this role about what their week "
                   "actually looks like", "whether the day-to-day matches what you're imagining"),
    "training": ("Run one session teaching what you already know",
                 "whether teaching is a direction or a distraction"),
    "advisory": ("Offer one advisory conversation and notice what you're asked for",
                 "where your experience is actually valued from outside"),
    "part_time": ("Arrange one week at the intensity you think you want",
                  "whether the reduced load is what you actually want"),
    "problem_business": ("Find three people with this problem and ask what it currently costs them",
                         "whether the problem is painful enough to pay for"),
    "independent_tutoring": ("Take one paying student for a month", "whether teaching one-to-one holds up"),
    "inspection": ("Spend a day with someone doing inspection work", "whether the work suits you"),
    "product_building": ("Put the smallest working version in front of five real users",
                         "whether anyone wants it before you invest months"),
}

REGULATED_TEST = ("Contact the licensing body and confirm exactly what your existing "
                  "qualifications count toward", "whether this is even open to you, before anything else")


def _constraints(session: DiscoverSession) -> dict:
    pc = session.practical_context or {}
    dims = session.dimensions or {}
    return {
        "lowTime": isinstance(pc.get("hours_per_week"), (int, float)) and pc["hours_per_week"] < -0.4,
        "moneyPressure": dims.get("income_urgency", {}).get("estimate", 0) > 0.3,
        "lowRisk": dims.get("risk_tolerance", {}).get("estimate", 0) < -0.2,
        "hasCommercial": bool(pc.get("commercial_evidence")),
    }


def generate(session: DiscoverSession, direction: dict) -> dict:
    """One experiment for one direction. Returns {action, teaches, effort, safety}.
    Two directions sharing a pathway must still get distinguishable tests —
    the experiment names the direction it is testing."""
    cons = _constraints(session)
    licensing = direction.get("licensing") or {}
    missing = direction.get("missing") or direction.get("skillGaps") or []
    pathway = direction.get("pathway") or direction.get("pathwayType") or "employment"

    # a closed regulatory door is the cheapest thing to check first
    if licensing.get("required") and not licensing.get("eligible"):
        action, teaches = REGULATED_TEST
        return {"action": action, "teaches": teaches, "effort": "one phone call", "safety": "no risk"}

    action = teaches = None
    for cap in missing:
        key = cap if isinstance(cap, str) else ""
        key = key.replace(" ", "_")
        if key in CAPABILITY_TESTS:
            action, teaches = CAPABILITY_TESTS[key]
            break
    if not action and pathway in PATHWAY_TESTS:
        action, teaches = PATHWAY_TESTS[pathway]
        label = direction.get("label") or direction.get("name")
        if label:
            # anchor the generic pathway test to THIS direction
            subject = label.split(" — ")[0]
            action = f"{action} — specifically for {subject}"
            teaches = f"{teaches}, in {subject} rather than in general"
    if not action:
        label = direction.get("label") or direction.get("name") or "this direction"
        action = f"Find one person already doing {label} and ask what the first year cost them"
        teaches = "what this actually involves before committing anything"

    # constraints shape the framing, never the honesty
    effort = "a few conversations"
    if cons["lowTime"]:
        effort = "one evening"
        action = action.replace("two weeks", "one week").replace("a month", "two weeks")
    if cons["moneyPressure"] and pathway in ("business_ownership", "practice_ownership"):
        action = action + " — including how they paid themselves in year one"
        teaches = teaches + ", given you need income now"
    safety = "reversible" if pathway not in ("business_ownership", "practice_ownership") else "no capital committed"
    return {"action": action, "teaches": teaches, "effort": effort, "safety": safety}


def persist(db: Session, session: DiscoverSession, direction_key: str, experiment: dict,
            material_object_id: str | None = None):
    from .models import ExperimentRun
    run = ExperimentRun(session_id=session.id, material_object_id=material_object_id,
                        direction_key=direction_key, action=experiment["action"],
                        teaches=experiment.get("teaches", ""), effort=experiment.get("effort", ""))
    db.add(run)
    db.flush()
    return run
