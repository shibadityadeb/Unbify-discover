"""PART TWO — the persistent Discover Workspace (My UNBIFY).

QUESTIONS: adaptive direct questions chosen by value, never a giant form.
ACTIONS: intelligence-generated modules; the Opportunity Map lives here.
Everything derives from Human State + catalog + ranking — the LLM may polish
wording, never decide content."""
from __future__ import annotations

from sqlalchemy.orm import Session

from .dimensions import DIMENSIONS, dim_phrase
from .models import DiscoverSession, Opportunity, RecommendationItem, RecommendationSet
from .opportunities import retrieve_candidates
from .ranking import HeuristicRankingModel, rank_and_persist

QUESTION_VERSION = "questions_v1"

# ---------------- adaptive direct questions ----------------
# effort ~ user cost; relevance ~ how much recommendations sharpen with the answer

QUESTIONS: list[dict] = [
    {"id": "q_role", "type": "micro_reflection", "practical_key": "current_role",
     "targets": ["domain_expertise"], "effort": 0.7, "relevance": 0.9,
     "content": {"headline": "In plain words —", "supportingText": "What do you do right now?",
                 "placeholder": "e.g. I run logistics for a mid-size retailer"}},
    {"id": "q_experience", "type": "spectrum", "practical_key": "years_experience",
     "targets": ["domain_expertise"], "effort": 0.2, "relevance": 0.85,
     "content": {"headline": "How long have you been at your craft?", "supportingText": None,
                 "left": {"label": "Just starting", "dim": "domain_expertise", "dir": -1},
                 "right": {"label": "Many years deep", "dim": "domain_expertise", "dir": 1}}},
    {"id": "q_skills", "type": "object_sort", "practical_key": "skills",
     "targets": ["implementation_affinity", "sales_comfort", "teaching", "analytical"], "effort": 0.45, "relevance": 0.9,
     "content": {"headline": "Which of these feel like yours?", "supportingText": "Pick what's honestly true.",
                 "maxSelect": 8, "minSelect": 1, "options": [
         {"id": "writing", "label": "Writing", "signals": [{"dim": "storytelling", "delta": .5, "weight": .45}]},
         {"id": "selling", "label": "Selling", "signals": [{"dim": "sales_comfort", "delta": .55, "weight": .5}]},
         {"id": "building", "label": "Building / coding", "signals": [{"dim": "implementation_affinity", "delta": .55, "weight": .5}]},
         {"id": "teaching", "label": "Teaching", "signals": [{"dim": "teaching", "delta": .55, "weight": .5}]},
         {"id": "analyzing", "label": "Analyzing", "signals": [{"dim": "analytical", "delta": .5, "weight": .45}]},
         {"id": "organizing", "label": "Organizing", "signals": [{"dim": "planning", "delta": .5, "weight": .45}]},
         {"id": "designing", "label": "Designing", "signals": [{"dim": "aesthetic_sensitivity", "delta": .55, "weight": .5}]},
         {"id": "connecting", "label": "Connecting people", "signals": [{"dim": "relationship_building", "delta": .5, "weight": .45}]},
     ]}},
    {"id": "q_industries", "type": "object_sort", "practical_key": "industries",
     "targets": ["domain_expertise"], "effort": 0.4, "relevance": 0.7,
     "content": {"headline": "Where have you spent real time?", "supportingText": None,
                 "maxSelect": 8, "minSelect": 1, "options": [
         {"id": "tech", "label": "Tech / software", "signals": []},
         {"id": "health", "label": "Health", "signals": []},
         {"id": "finance", "label": "Finance", "signals": []},
         {"id": "education", "label": "Education", "signals": []},
         {"id": "commerce", "label": "Commerce / retail", "signals": []},
         {"id": "creative", "label": "Creative / media", "signals": []},
         {"id": "trades", "label": "Trades / physical", "signals": []},
         {"id": "public", "label": "Public / nonprofit", "signals": []},
     ]}},
    {"id": "q_income_target", "type": "spectrum", "practical_key": "income_target",
     "targets": ["revenue_ambition"], "effort": 0.2, "relevance": 0.8,
     "content": {"headline": "What would “working” money look like?", "supportingText": "No judgment either way.",
                 "left": {"label": "Cover my life well", "dim": "revenue_ambition", "dir": -1},
                 "right": {"label": "Build real wealth", "dim": "revenue_ambition", "dir": 1}}},
    {"id": "q_capital", "type": "scenario_choice", "practical_key": "capital",
     "targets": ["capital_availability"], "effort": 0.25, "relevance": 0.75,
     "content": {"headline": "If the right opportunity needed money to start…", "supportingText": None, "options": [
         {"id": "none", "label": "Nothing to spare right now", "signals": [{"dim": "capital_availability", "delta": -.55, "weight": .5}]},
         {"id": "small", "label": "A small cushion", "signals": [{"dim": "capital_availability", "delta": .1, "weight": .3}]},
         {"id": "real", "label": "Real savings I could use", "signals": [{"dim": "capital_availability", "delta": .55, "weight": .5}]},
         {"id": "backers", "label": "People who might back me", "signals": [{"dim": "capital_availability", "delta": .4, "weight": .35}, {"dim": "network", "delta": .35, "weight": .3}]},
     ]}},
    {"id": "q_sales_exp", "type": "scenario_choice", "practical_key": "sales_experience",
     "targets": ["sales_comfort"], "effort": 0.25, "relevance": 0.8,
     "content": {"headline": "Have you ever sold something you made or did?", "supportingText": None, "options": [
         {"id": "never", "label": "Never, honestly", "signals": [{"dim": "sales_comfort", "delta": -.4, "weight": .4}]},
         {"id": "few", "label": "A few times", "signals": [{"dim": "sales_comfort", "delta": .15, "weight": .3}]},
         {"id": "regular", "label": "Regularly", "signals": [{"dim": "sales_comfort", "delta": .5, "weight": .45}]},
         {"id": "job", "label": "It's part of my job", "signals": [{"dim": "sales_comfort", "delta": .6, "weight": .55}]},
     ]}},
    {"id": "q_audience", "type": "spectrum", "practical_key": "audience_size",
     "targets": ["audience"], "effort": 0.2, "relevance": 0.6,
     "content": {"headline": "People who follow your work —", "supportingText": "Any channel counts.",
                 "left": {"label": "Nobody yet", "dim": "audience", "dir": -1},
                 "right": {"label": "A real audience", "dim": "audience", "dir": 1}}},
    {"id": "q_goal", "type": "scenario_choice", "practical_key": "current_goal",
     "targets": ["purpose", "income_urgency", "autonomy"], "effort": 0.25, "relevance": 0.85,
     "content": {"headline": "Right now, you mostly want…", "supportingText": "The honest one, not the noble one.", "options": [
         {"id": "income", "label": "More income", "signals": [{"dim": "income_urgency", "delta": .45, "weight": .4}]},
         {"id": "meaning", "label": "More meaning", "signals": [{"dim": "purpose", "delta": .5, "weight": .45}]},
         {"id": "freedom", "label": "More freedom", "signals": [{"dim": "autonomy", "delta": .5, "weight": .45}]},
         {"id": "growth", "label": "More growth", "signals": [{"dim": "mastery", "delta": .45, "weight": .4}]},
     ]}},
    {"id": "q_entrepreneur", "type": "spectrum", "practical_key": "entrepreneurial_interest",
     "targets": ["risk_tolerance", "revenue_ambition"], "effort": 0.2, "relevance": 0.85,
     "content": {"headline": "Owning something of your own, someday —", "supportingText": None,
                 "left": {"label": "Not really for me", "dim": "risk_tolerance", "dir": -1},
                 "right": {"label": "Definitely calling", "dim": "revenue_ambition", "dir": 1}}},
]


def question_value(session: DiscoverSession, q: dict) -> float:
    """question_value = information_gain × relevance × uncertainty − effort"""
    dims = session.dimensions or {}
    if q["practical_key"] in (session.practical_context or {}):
        return -1.0  # already answered
    confs = [dims.get(d, {}).get("confidence", 0.0) for d in q["targets"]] or [0.0]
    uncertainty = 1.0 - (sum(confs) / len(confs))
    return uncertainty * q["relevance"] - q["effort"] * 0.3


def pending_questions(session: DiscoverSession, n: int = 3) -> list[dict]:
    scored = [(question_value(session, q), q) for q in QUESTIONS]
    scored = [x for x in scored if x[0] > 0]
    scored.sort(key=lambda x: -x[0])
    return [q for _, q in scored[:n]]


def profile_clarity(session: DiscoverSession) -> str:
    dims = session.dimensions or {}
    covered = sum(1 for d in DIMENSIONS if dims.get(d, {}).get("confidence", 0) >= 0.35)
    frac = covered / len(DIMENSIONS)
    if frac < 0.2:
        return "Early"
    if frac < 0.45:
        return "Developing"
    if frac < 0.7:
        return "Strong"
    return "Very strong"


# ---------------- actions (intelligence-generated) ----------------

def _facts_fingerprint(session: DiscoverSession) -> str:
    import hashlib, json as _json
    pc = session.practical_context or {}
    basis = {k: v for k, v in pc.items() if not k.startswith("_") and k not in ("notes",)}
    return hashlib.sha256(_json.dumps(basis, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _latest_lives(db: Session, session: DiscoverSession, refresh: bool = False) -> list[dict]:
    # opportunities change when evidence changes: a map cached before new
    # professional facts arrived must not be silently re-served (new snapshot
    # instead — old snapshots stay persisted, never mutated)
    pc0 = session.practical_context or {}
    if pc0.get("_lives") and pc0.get("_lives_fingerprint") != _facts_fingerprint(session):
        refresh = True
    if refresh or not (session.practical_context or {}).get("_lives"):
        from .config import settings as _settings
        rec_set = None
        if _settings.world_intelligence_enabled:
            from .world.matching import recommend as world_recommend
            rec_set = world_recommend(db, session)
        if rec_set is None:
            candidates = retrieve_candidates(db, session)
            rec_set = rank_and_persist(db, session, candidates)
        items = (db.query(RecommendationItem).filter_by(set_id=rec_set.id)
                 .order_by(RecommendationItem.rank).all())
        lives = []
        for item in items:
            opp = db.get(Opportunity, item.opportunity_id)
            lives.append(_life_payload(opp, item))
        pc = dict(session.practical_context or {})
        pc["_lives"] = lives
        pc["_lives_fingerprint"] = _facts_fingerprint(session)
        session.practical_context = pc
    return (session.practical_context or {}).get("_lives", [])


def _life_payload(opp: Opportunity, item: RecommendationItem) -> dict:
    factors = item.factor_contributions or {}
    narrative = item.narrative or {}
    # world-engine recommendations carry evidence-honest narrative fields;
    # catalog fallbacks derive whyYou from their fit factors as before
    why_you = narrative.get("whyYou") or _factors_to_why(factors)
    freshness = narrative.get("freshnessDays")
    return {
        "key": opp.id, "name": opp.title, "essence": opp.value_proposition,
        "pathway": opp.pathway_type,
        "whyYou": why_you,
        "whyNow": narrative.get("whyNow") or opp.description or "No strong timing signal yet.",
        "friction": narrative.get("friction"),
        "requires": ", ".join(opp.skill_gaps) or "focused first steps",
        "risk": opp.risk_profile, "timeToValue": opp.time_to_first_value,
        "confidence": max(35, min(85, int(50 + item.score * 40))),
        "confidenceLabel": narrative.get("confidenceLabel"),
        "evidenceFreshness": (f"market evidence refreshed {freshness}d ago"
                              if isinstance(freshness, int) else None),
        "whyThis": [{"factor": k.replace("fit:", "").replace("_", " "), "value": round(v, 2)}
                    for k, v in sorted(factors.items(), key=lambda kv: -abs(kv[1]))
                    if not k.startswith("_")][:5],
        "firstExperiment": f"Give {opp.title} two honest hours this week: " +
                           (opp.skill_gaps[0] if opp.skill_gaps else "sketch the first concrete step") + ".",
        "skillGaps": opp.skill_gaps,
    }


def _factors_to_why(factors: dict) -> str:
    tops = sorted(((k, v) for k, v in factors.items() if k.startswith("fit:") and v > 0),
                  key=lambda kv: kv[1], reverse=True)[:2]
    if not tops:
        return "The overall shape of your evidence points here."
    names = [k.split(":")[1].replace("_", " ") for k, _ in tops]
    return f"Your strongest signals — {' and '.join(names)} — concentrate where this path pays."


def available_actions(session: DiscoverSession) -> list[dict]:
    dims = session.dimensions or {}

    def est(d):
        return dims.get(d, {}).get("estimate", 0.0)

    actions = [
        {"id": "position", "label": "Analyze my current professional position", "hint": "Fit, friction, leverage, optionality"},
        {"id": "explore", "label": "Explore my possibilities", "hint": "Your ranked Opportunity Map"},
        {"id": "next_move", "label": "My best next move", "hint": "One high-value step, this week"},
        {"id": "test_direction", "label": "Test a direction", "hint": "A small, low-risk experiment"},
        {"id": "gaps", "label": "What am I missing?", "hint": "Skill and evidence gaps that matter"},
    ]
    if str((session.practical_context or {}).get("career_stage", "")).startswith("employed"):
        actions.append({"id": "improve", "label": "Improve where I am", "hint": "Leverage without leaving"})
    if est("domain_expertise") > 0.15:
        actions.append({"id": "expertise_income", "label": "Turn my expertise into income", "hint": "Consulting and service leverage"})
    if est("implementation_affinity") > 0.15 or est("originality") > 0.2:
        actions.append({"id": "build", "label": "Build something", "hint": "Builder-path possibilities"})
    actions.append({"id": "whats_changing", "label": "See what's changing in my field",
                    "hint": "Current evidence, checked now"})
    actions.append({"id": "transfer", "label": "Where my experience transfers",
                    "hint": "Capability overlap against the live map"})
    if (session.practical_context or {}).get("commercial_evidence") or \
            (session.practical_context or {}).get("freelance_experience"):
        actions.append({"id": "independent_paths", "label": "Look for independent paths",
                        "hint": "Contracting, services, practice"})
    actions.append({"id": "ai_leverage", "label": "AI leverage", "hint": "Multiply what you already do"})
    actions.append({"id": "compare", "label": "Compare paths", "hint": "Two futures, side by side"})
    return actions


# actions whose value depends on CURRENT world evidence go through the
# real-time pipeline: freshness check → targeted refresh if needed → rerank
LIVE_ACTIONS = {
    "whats_changing": ("whats_changing", "What's changing in your field"),
    "active_now": ("active_now", "What the market is rewarding right now"),
    "transfer": ("transfer", "Where your experience transfers"),
    "independent_paths": ("independent_work", "Independent paths worth examining"),
}


def live_analysis(db: Session, session: DiscoverSession, action_id: str) -> dict:
    from .world.analysis import analyze
    intent, headline = LIVE_ACTIONS[action_id]
    out = analyze(db, session, intent)
    fresh = out["marketFreshness"]
    refreshing = out["status"] == "refreshing"
    return {
        "kind": "live_map",
        "headline": headline,
        "supportingText": ("Checking the current landscape — showing what we already have "
                           "while that finishes." if refreshing else
                           "Computed just now from your latest profile and current evidence."),
        "status": out["status"],
        "refreshId": out.get("refreshId"),
        "lives": [_direction_to_life(d) for d in out["analysis"]["directions"]],
        "marketFreshness": fresh,
        "evidenceNote": out["analysis"].get("worldEvidenceNote"),
        "changeSummary": out["analysis"].get("changeSummary"),
        "versions": out["versions"],
    }


def _direction_to_life(d: dict) -> dict:
    return {
        "key": d["key"], "name": d["label"], "pathway": d.get("pathway"),
        "essence": d.get("whyThisAppeared", ""),
        "whyYou": d.get("whyThisAppeared", ""),
        "whyNow": d.get("marketEvidence", "No strong timing signal yet."),
        "friction": d.get("whatMakesItRisky"),
        "requires": ", ".join(d.get("missing") or []) or "focused first steps",
        "risk": "medium", "timeToValue": "varies",
        "confidence": 55, "confidenceLabel": d.get("confidenceLabel"),
        "evidenceFreshness": (f"market evidence refreshed {d['evidenceFreshness']}d ago"
                              if isinstance(d.get("evidenceFreshness"), int) else None),
        "whyThis": [{"factor": k.replace("_", " "), "value": round(v, 2)}
                    for k, v in list((d.get("rankingFactors") or {}).items())[:5]],
        "firstExperiment": (d.get("experiment") or {}).get("action", ""),
        "skillGaps": d.get("missing") or [],
    }


def action_content(db: Session, session: DiscoverSession, action_id: str) -> dict:
    lives = _latest_lives(db, session, refresh=(action_id == "explore"))
    dims = session.dimensions or {}
    resonant = (session.practical_context or {}).get("resonant_life")
    primary = next((l for l in lives if l["key"] == resonant), lives[0] if lives else None)

    if action_id == "position":
        from .professional import get_position, current_status
        prof = get_position(session)
        status = current_status(session) or "not yet shared"
        tops = sorted(dims.items(), key=lambda kv: -abs(kv[1].get("estimate", 0)) * kv[1].get("confidence", 0))[:2]
        friction = next((c for c in (session.contradictions or [])), None)
        unknown = sorted(((d, v.get("confidence", 0)) for d, v in dims.items() if v.get("confidence", 0) < 0.3),
                         key=lambda x: x[1])[:2]
        items = [
            f"Current position — {status}" + (f", in {prof.get('domain')}" if prof.get("domain") else "") +
            (f" ({prof.get('industry')})" if prof.get("industry") else "") + ".",
        ]
        if tops:
            d, v = tops[0]
            items.append(f"Alignment — your work fits best where {dim_phrase(d, v.get('estimate', 0))} matters; that pattern held across chapters.")
        if friction:
            items.append(f"Friction — the pull between {dim_phrase(friction['dim'], 1)} and {dim_phrase(friction['dim'], -1)} shapes what roles will wear on you.")
        if prof.get("activities"):
            items.append(f"Leverage — repeated exposure to {', '.join(prof['activities'][:3])} is compounding, whether or not your title says so.")
        else:
            items.append("Leverage — answer the professional questions and this section sharpens considerably.")
        items.append("Transferability — your evidence spans more than one function, which creates more options than a single-track profile.")
        items.append("Optionality — see 'Explore my possibilities' for the paths this position realistically opens.")
        if unknown:
            items.append(f"Still unknown — we have little evidence on {dim_phrase(unknown[0][0], 1)}; we'd rather ask than guess.")
        return {"kind": "list", "headline": "Your professional position", "items": items,
                "note": "Analysis, not a verdict — it updates as your evidence does."}
    if action_id in LIVE_ACTIONS:
        return live_analysis(db, session, action_id)
    if action_id == "explore":
        return {"kind": "map", "headline": "Your Opportunity Map",
                "supportingText": "Three credible futures — explainable, none of them destiny.",
                "lives": lives}
    if action_id == "next_move" and primary:
        return {"kind": "single", "headline": "My best next move",
                "title": primary["name"],
                "text": primary["firstExperiment"],
                "note": "Chosen from your top-ranked path and its first missing piece."}
    if action_id == "test_direction" and primary:
        return {"kind": "single", "headline": "Test a direction",
                "title": f"A 7-day experiment toward {primary['name']}",
                "text": f"Timebox it: two evenings. {primary['firstExperiment']} "
                        f"Then write one honest paragraph — did it give energy or take it?",
                "note": "Small enough to be safe. Real enough to produce evidence."}
    if action_id == "gaps":
        gap_dims = sorted(((d, v.get("confidence", 0)) for d, v in dims.items() if v.get("confidence", 0) < 0.3),
                          key=lambda x: x[1])[:3]
        items = [f"{primary['name']}: {', '.join(primary['skillGaps'])}" if primary and primary.get("skillGaps") else None]
        items += [f"We still know little about {dim_phrase(d, 1)} — a few Questions would sharpen this." for d, _ in gap_dims]
        return {"kind": "list", "headline": "What am I missing?",
                "items": [i for i in items if i],
                "note": "Gaps are direction, not verdicts."}
    if action_id == "improve":
        tops = sorted(dims.items(), key=lambda kv: -abs(kv[1].get("estimate", 0)) * kv[1].get("confidence", 0))[:2]
        items = [f"Your {dim_phrase(d, v.get('estimate', 0))} is under-used where you are — name one place it could run freer."
                 for d, v in tops]
        items.append("Fix one broken process end-to-end without being asked. Quiet leverage compounds.")
        return {"kind": "list", "headline": "Improve where I am", "items": items,
                "note": "Position often beats motion."}
    if action_id == "expertise_income":
        consult = next((l for l in lives if l["pathway"] == "consulting"), None)
        return {"kind": "single", "headline": "Turn my expertise into income",
                "title": consult["name"] if consult else "Package what people already borrow",
                "text": (consult["whyYou"] + " " if consult else "") +
                        "Offer one person a small, paid version of the help you already give away free.",
                "note": "First revenue is evidence, not commitment."}
    if action_id == "build":
        builder = next((l for l in lives if l["pathway"] in ("builder", "entrepreneurship")), None)
        return {"kind": "single", "headline": "Build something",
                "title": builder["name"] if builder else "The smallest shippable thing",
                "text": (builder["firstExperiment"] if builder else
                         "Build the smallest version of one idea in 14 days and put it in front of ten strangers."),
                "note": "Ship rough. Learn real."}
    if action_id == "ai_leverage":
        ai_est = dims.get("ai_leverage", {}).get("estimate", 0)
        lead = ("You're already comfortable with the tools — the play is packaging that comfort."
                if ai_est > 0.2 else "You don't need to become technical — you need one workflow that pays.")
        return {"kind": "list", "headline": "AI leverage",
                "items": [lead,
                          "Pick the most repetitive hour of your week and automate half of it this month.",
                          "The scarce skill isn't using AI — it's knowing which of your judgments it can't replace."],
                "note": "Leverage compounds quietly."}
    if action_id == "compare" and len(lives) >= 2:
        return {"kind": "compare", "headline": "Compare paths",
                "a": lives[0], "b": lives[1],
                "note": "Weighed against your actual constraints, not a generic pro/con list."}
    return {"kind": "single", "headline": "Not enough evidence yet",
            "title": "A few Questions would unlock this",
            "text": "Answer the highest-value questions in the Questions tab and this action sharpens.",
            "note": ""}


def _question_invite(db: Session, session: DiscoverSession, pending: list[dict]) -> str:
    """A question earns its place by naming what it would change (§22/§23) —
    never 'Question 19'."""
    if not pending:
        return "Nothing pressing to ask right now. New questions appear as your evidence changes."
    from .models import MaterialObject
    blocking = (db.query(MaterialObject)
                .filter_by(session_id=session.id, kind="gap")
                .order_by(MaterialObject.created_at.asc()).all())
    for gap in blocking:
        blocks = (gap.detail or {}).get("blocks")
        if blocks:
            return (f"One answer would change whether {blocks} is realistically worth "
                    f"exploring — {(gap.detail or {}).get('why', 'it decides the ranking')}.")
    if blocking:
        g = blocking[0]
        return (f"The most useful thing you could tell us next: {g.label} — "
                f"{(g.detail or {}).get('why', 'it sharpens everything downstream')}.")
    return (f"{len(pending)} answers would materially sharpen which directions are "
            "realistic for you.")


def workspace_summary(db: Session, session: DiscoverSession) -> dict:
    pending = pending_questions(session)
    actions = available_actions(session)
    ranked = rank_actions(db, session, actions)
    return {
        "type": "workspace",
        "headline": "My UNBIFY",
        "clarity": profile_clarity(session),
        "questions": {
            "available": len(pending),
            "invite": _question_invite(db, session, pending),
        },
        "actions": ranked,
        "mostUseful": (ranked[0]["id"] if ranked else None),
        "saved": len([o for o in _saved(db, session)]),
    }


def _saved(db: Session, session: DiscoverSession) -> list:
    from .models import MaterialObject
    return (db.query(MaterialObject)
            .filter(MaterialObject.session_id == session.id,
                    MaterialObject.saved.is_(True)).all())


# §25: actions themselves are ranked — the top one is "most useful right now",
# never "the objectively correct action"
ACTION_PRIORS = {
    "whats_changing": {"value": 0.8, "effort": 0.15},
    "transfer": {"value": 0.75, "effort": 0.15},
    "independent_paths": {"value": 0.7, "effort": 0.2},
    "explore": {"value": 0.9, "effort": 0.1}, "position": {"value": 0.8, "effort": 0.15},
    "test_direction": {"value": 0.85, "effort": 0.3}, "next_move": {"value": 0.7, "effort": 0.15},
    "gaps": {"value": 0.65, "effort": 0.1}, "build": {"value": 0.6, "effort": 0.35},
    "improve": {"value": 0.6, "effort": 0.2}, "expertise_income": {"value": 0.65, "effort": 0.3},
    "ai_leverage": {"value": 0.5, "effort": 0.2}, "compare": {"value": 0.55, "effort": 0.25},
}


def rank_actions(db: Session, session: DiscoverSession, actions: list[dict]) -> list[dict]:
    from .models import MaterialObject
    objs = db.query(MaterialObject).filter_by(session_id=session.id).all()
    has_directions = any(o.kind == "direction" for o in objs)
    testing = any(o.kind == "direction" and o.status in ("testing", "active") for o in objs)
    open_gaps = len([o for o in objs if o.kind == "gap"])
    clarity = profile_clarity(session)
    out = []
    for a in actions:
        prior = ACTION_PRIORS.get(a["id"], {"value": 0.5, "effort": 0.25})
        relevance = 1.0
        if a["id"] == "explore" and has_directions:
            relevance = 1.2                      # the map already exists — cheap to open
        if a["id"] == "test_direction":
            relevance = 1.3 if (has_directions and not testing) else 0.6
        if a["id"] == "gaps":
            relevance = 1.0 + 0.06 * min(4, open_gaps)
        if a["id"] == "position" and clarity in ("Early", "Developing"):
            relevance = 1.15
        score = prior["value"] * relevance - prior["effort"]
        out.append({**a, "score": round(score, 3)})
    out.sort(key=lambda x: -x["score"])
    if out:
        out[0] = {**out[0], "mostUsefulNow": True,
                  "note": "Most useful right now — not the only right move."}
    return out
