"""Matching & ranking: the point where HUMAN intelligence meets WORLD
intelligence — and the only place they meet.

HUMAN PROFILE → CAPABILITY VECTOR → ELIGIBILITY → OPPORTUNITY GRAPH →
MARKET SIGNALS → CANDIDATES → MULTI-FACTOR RANKING → DIVERSITY → SNAPSHOT.

Never "similarity = good"; never prestige; never fabricated timing; abstains
with insufficient_world_evidence rather than inventing coverage.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import (DiscoverSession, Opportunity, RecommendationItem,
                      RecommendationSet, WILicenseRequirement, WIOccupation,
                      WIOccupationTransition, WIOpportunitySnapshot, WIProblem)
from . import ontology, signals

RANKING_VERSION = "world_rank_v1"

PATHWAY_LABEL = {
    "employment": "employed role", "specialization": "specialization",
    "contracting": "independent contracting", "business_ownership": "owning the business",
    "consulting": "consulting / advisory", "training": "training others",
    "advisory": "advisory work", "part_time": "part-time / flexible work",
    "practice_ownership": "own practice", "freelancing": "freelancing",
    "product_building": "building a product", "independent_tutoring": "independent tutoring",
    "inspection": "inspection work", "operations_transition": "civilian operations",
    "project_leadership": "project leadership", "quality_path": "quality specialization",
    "problem_business": "a business around a known problem",
}

# user intent changes ranking — explicitly, never via personality inference
INTENT_WEIGHTS = {
    "max_income": {"demand": 1.3, "economic": 1.4, "capability_fit": 1.0, "feasibility": 1.0},
    "part_time": {"part_time_bonus": 1.5, "capability_fit": 1.0, "demand": 0.7, "feasibility": 1.2},
    "build": {"business_bonus": 1.5, "capability_fit": 1.0, "demand": 0.8, "feasibility": 1.0},
    "stability": {"employment_bonus": 1.3, "demand": 1.2, "capability_fit": 1.1, "feasibility": 1.2},
    None: {"capability_fit": 1.0, "demand": 1.0, "feasibility": 1.0},
}


def _capability_fit(user_vec: dict[str, float], occ_caps: dict[str, float]) -> tuple[float, list, list]:
    if not occ_caps:
        return 0.0, [], []
    transfers, missing = [], []
    total = got = 0.0
    for cap, w in occ_caps.items():
        total += w
        u = user_vec.get(cap, 0.0)
        got += min(u, 1.0) * w
        if u >= 0.35:
            transfers.append(cap)
        elif w >= 0.7:
            missing.append(cap)
    fit = got / total if total else 0.0
    # specificity: a 3-capability occupation is easier to "fit" than a
    # 9-capability trade — don't let shallow profiles outrank deep overlap
    fit *= 0.7 + 0.3 * min(1.0, len(occ_caps) / 6)
    return fit, transfers[:5], missing[:4]


def _license_gate(db: Session, session: DiscoverSession, occ: WIOccupation,
                  current_occ_ids: set[str], specialization_of_current: bool = False) -> dict:
    """Never recommend regulated practice without eligibility awareness. A
    specialization of the user's own licensed field builds on that license."""
    if not occ.regulated:
        return {"required": False, "eligible": True, "note": None}
    reqs = db.query(WILicenseRequirement).filter_by(occupation_id=occ.id).all()
    note = reqs[0].requirement if reqs else "professional licensing applies"
    if occ.id in current_occ_ids:
        return {"required": True, "eligible": True, "note": f"{note} — your current field"}
    if specialization_of_current:
        return {"required": True, "eligible": True,
                "note": f"{note} — builds on your existing qualification; verify local specifics"}
    pc = session.practical_context or {}
    if pc.get(f"license_{occ.id}"):
        return {"required": True, "eligible": True, "note": note}
    return {"required": True, "eligible": False,
            "note": f"requires {note}; eligibility unverified"}


def generate_candidates(db: Session, session: DiscoverSession,
                        geography: str = "*") -> dict:
    """Candidate generation across pathway types. Returns
    {status, candidates, coverage} — status may be insufficient_world_evidence."""
    user_vec = ontology.user_capability_vector(db, session)
    resolution = ontology.resolve_user_occupation(db, session)
    current_ids = {c["occupationId"] for c in resolution.get("candidates", [])}

    if not user_vec:
        return {"status": "insufficient_world_evidence", "candidates": [],
                "why": "no supported capability evidence yet"}

    occs = db.query(WIOccupation).filter_by(status="active").all()
    candidates: list[dict] = []
    for occ in occs:
        occ_caps = ontology.occupation_capabilities(db, occ.id)
        fit, transfers, missing = _capability_fit(user_vec, occ_caps)
        if fit < 0.18 and occ.id not in current_ids:
            continue
        transitions_in = [t for t in db.query(WIOccupationTransition).all()
                          if t.to_occupation_id == occ.id and t.from_occupation_id in current_ids]
        is_transition_target = bool(transitions_in)
        is_specialization = any(t.kind == "specialization" for t in transitions_in)
        licensing = _license_gate(db, session, occ, current_ids, is_specialization)
        demand_sig = signals.signal_for(db, occ.id, "demand_direction", geography)
        se_sig = signals.signal_for(db, occ.id, "self_employment_prevalence", geography)
        pathways = list(occ.pathway_potentials or ["employment"])
        for pathway in pathways:
            if licensing["required"] and not licensing["eligible"] and pathway not in ("training",):
                continue     # regulated practice without verified eligibility: skip
            candidates.append({
                "occupationId": occ.id, "label": occ.preferred_label,
                "workClass": occ.work_class, "pathway": pathway,
                "pathwayLabel": PATHWAY_LABEL.get(pathway, pathway),
                "capabilityFit": round(fit, 3), "transfers": transfers, "missing": missing,
                "isCurrentField": occ.id in current_ids,
                "isKnownTransition": is_transition_target,
                "licensing": licensing,
                "selfEmployment": (se_sig.value if se_sig else occ.self_employment_prevalence),
                "market": {
                    "demand": demand_sig.value if demand_sig else None,
                    "confidence": demand_sig.confidence if demand_sig else 0.0,
                    "freshnessDays": signals.freshness_days(demand_sig),
                    "geography": demand_sig.geography if demand_sig else None,
                    "conflicts": (demand_sig.conflicts if demand_sig else []),
                    "snapshotVersion": demand_sig.snapshot_version if demand_sig else None,
                },
                "ai": {"automationExposure": occ.ai_automation_exposure,
                       "augmentationPotential": occ.ai_augmentation_potential},
            })
    # problem-grounded business candidates: only where the user's OWN
    # capabilities overlap problems the market verifiably pays to solve
    for prob in db.query(WIProblem).all():
        overlap = [c for c in prob.solved_by_capabilities if user_vec.get(c, 0) >= 0.4]
        if len(overlap) >= 1 and (session.practical_context or {}).get("commercial_evidence"):
            candidates.append({
                "occupationId": None, "label": prob.label, "workClass": "problem",
                "pathway": "problem_business", "pathwayLabel": PATHWAY_LABEL["problem_business"],
                "capabilityFit": round(sum(user_vec[c] for c in overlap) / len(prob.solved_by_capabilities), 3),
                "transfers": overlap, "missing": [], "isCurrentField": False,
                "isKnownTransition": False,
                "licensing": {"required": False, "eligible": True, "note": None},
                "selfEmployment": 1.0,
                "market": {"demand": None, "confidence": 0.3, "freshnessDays": None,
                           "geography": None, "conflicts": [],
                           "snapshotVersion": None, "evidenceNote": prob.evidence_note},
                "ai": {"automationExposure": 0.2, "augmentationPotential": 0.6},
                "problemId": prob.id,
            })
    if not candidates:
        # world coverage gap for this human: abstain and queue enrichment —
        # never fabricate (PART 87/88)
        title = ((session.practical_context or {}).get("professional") or {}).get("domain") or "unknown field"
        signals.request_targeted_refresh(db, None, [str(title)], geography, reason="coverage_gap")
        return {"status": "insufficient_world_evidence", "candidates": [],
                "why": "occupation coverage too thin for this profile"}
    return {"status": "ok", "candidates": candidates, "userVector": user_vec,
            "currentOccupations": sorted(current_ids)}


def rank(candidates: list[dict], session: DiscoverSession, intent: str | None = None) -> list[dict]:
    w = INTENT_WEIGHTS.get(intent, INTENT_WEIGHTS[None])
    pc = session.practical_context or {}
    ranked = []
    for c in candidates:
        factors: dict[str, float] = {}
        factors["capability_fit"] = c["capabilityFit"] * 1.4 * w.get("capability_fit", 1.0)
        # actual experience is the strongest evidence there is — the user's
        # own field and its documented transitions outrank inferred fits
        factors["experience_leverage"] = 0.7 if c["isCurrentField"] else (0.4 if c["isKnownTransition"] else 0.0)
        demand = c["market"]["demand"]
        factors["market_demand"] = ((demand - 0.35) * c["market"]["confidence"]
                                    * w.get("demand", 1.0)) if demand is not None else 0.0
        factors["licensing_feasibility"] = 0.0 if c["licensing"]["eligible"] else -0.8
        factors["training_gap"] = -0.12 * len(c["missing"])
        if c["pathway"] in ("business_ownership", "contracting", "problem_business",
                            "practice_ownership", "freelancing", "consulting"):
            factors["independence_path"] = (0.25 if pc.get("commercial_evidence") or
                                            pc.get("freelance_experience") else -0.15)
            if intent == "build":
                factors["independence_path"] += 0.45
        if c["pathway"] in ("part_time", "independent_tutoring", "training", "advisory"):
            factors["part_time_fit"] = 0.08 + (0.5 if intent == "part_time" else 0.0)
        if c["pathway"] == "employment":
            factors["employment_fit"] = 0.1 + (0.4 if intent == "stability" else 0.0)
        if intent == "max_income" and c["selfEmployment"] and c["pathway"] in (
                "business_ownership", "contracting", "practice_ownership"):
            factors["income_upside"] = 0.3 * float(c["selfEmployment"])
        factors["ai_leverage"] = 0.15 * c["ai"]["augmentationPotential"] - 0.2 * c["ai"]["automationExposure"]
        score = sum(factors.values())
        # opportunity confidence blends HUMAN and WORLD evidence — either
        # side weak marks the whole thing uncertain (PART 86)
        human_conf = min(1.0, c["capabilityFit"] * 1.6)
        world_conf = c["market"]["confidence"] if c["market"]["demand"] is not None else 0.25
        overall = round(min(human_conf, 0.4 + 0.6 * world_conf) * (0.5 + 0.5 * human_conf), 3)
        label = ("grounded" if overall >= 0.55 else "emerging" if overall >= 0.35 else "uncertain")
        ranked.append({**c, "score": round(score, 3),
                       "factors": {k: round(v, 3) for k, v in factors.items()},
                       "confidence": overall, "confidenceLabel": label})
    ranked.sort(key=lambda x: -x["score"])
    # diversity: one candidate per occupation, spread across pathway types
    out, seen_occ, seen_pathways = [], set(), {}
    for c in ranked:
        key = c["occupationId"] or c.get("problemId")
        if key in seen_occ:
            continue
        if seen_pathways.get(c["pathway"], 0) >= 2:
            continue
        out.append(c)
        seen_occ.add(key)
        seen_pathways[c["pathway"]] = seen_pathways.get(c["pathway"], 0) + 1
        if len(out) >= 6:
            break
    return out


def _why_now(c: dict) -> str:
    """PART 37: never fake timing."""
    m = c["market"]
    if m["demand"] is not None and m["demand"] >= 0.5 and m["confidence"] >= 0.4:
        fresh = f" (evidence refreshed {m['freshnessDays']}d ago)" if m.get("freshnessDays") is not None else ""
        return f"current market evidence shows active demand{fresh}"
    if m.get("evidenceNote"):
        return f"documented problem: {m['evidenceNote']}"
    return "No strong timing signal yet."


def recommend(db: Session, session: DiscoverSession, intent: str | None = None,
              profile_version_id: str | None = None) -> RecommendationSet | None:
    """Full pipeline; materializes candidates as Opportunity rows + a ranked,
    explained RecommendationSet + a reproducible snapshot. None = abstained."""
    gen = generate_candidates(db, session)
    if gen["status"] != "ok":
        return None
    ranked = rank(gen["candidates"], session, intent)[:3]
    if not ranked:
        return None
    rec_set = RecommendationSet(session_id=session.id, ranking_model=RANKING_VERSION,
                                profile_version_id=profile_version_id)
    db.add(rec_set)
    db.flush()
    snapshot_versions = {c["market"].get("snapshotVersion") for c in ranked if c["market"].get("snapshotVersion")}
    for i, c in enumerate(ranked):
        opp_id = f"world_{(c['occupationId'] or c.get('problemId'))}_{c['pathway']}"[:60]
        opp = db.get(Opportunity, opp_id)
        title = f"{c['label']} — {c['pathwayLabel']}"[:120]
        if not opp:
            opp = Opportunity(id=opp_id, title=title, pathway_type=c["pathway"],
                              industries=[], is_seed=False)
            db.add(opp)
        opp.title = title
        opp.description = _why_now(c)
        opp.value_proposition = ("your existing capabilities transfer here: "
                                 + ", ".join(t.replace("_", " ") for t in c["transfers"][:3])
                                 if c["transfers"] else "worth examining against your evidence")
        opp.skill_gaps = [m.replace("_", " ") for m in c["missing"]]
        opp.risk_profile = "low" if c["pathway"] == "employment" else "medium"
        opp.demand_score = c["market"]["demand"] if c["market"]["demand"] is not None else 0.5
        opp.ai_leverage_score = c["ai"]["augmentationPotential"]
        opp.startup_capital = "low" if c["pathway"] in ("contracting", "consulting", "training") else \
                              ("medium" if c["pathway"] in ("business_ownership", "practice_ownership") else "none")
        opp.time_to_first_value = "weeks" if c["isCurrentField"] else "months"
        db.flush()
        db.add(RecommendationItem(
            set_id=rec_set.id, opportunity_id=opp_id, rank=i + 1, score=c["score"],
            factor_contributions=c["factors"],
            narrative={
                "whyYou": ("your evidence shows " + ", ".join(t.replace("_", " ") for t in c["transfers"][:3])
                           if c["transfers"] else "capability overlap with your supported evidence"),
                "whyNow": _why_now(c),
                "friction": (c["licensing"]["note"] or
                             (("still missing: " + ", ".join(m.replace("_", " ") for m in c["missing"]))
                              if c["missing"] else "mostly the discipline of testing it small")),
                "confidenceLabel": c["confidenceLabel"],
                "freshnessDays": c["market"].get("freshnessDays"),
                "marketConflicts": c["market"].get("conflicts", []),
            }))
    db.add(WIOpportunitySnapshot(
        session_id=session.id, recommendation_set_id=rec_set.id,
        profile_version_id=profile_version_id,
        market_snapshot_version=(sorted(snapshot_versions)[-1] if snapshot_versions else "none"),
        ranking_model_version=RANKING_VERSION,
        candidates=[{k: c[k] for k in ("occupationId", "label", "pathway", "score",
                                       "confidence", "factors", "transfers", "missing",
                                       "licensing")} for c in ranked]))
    db.flush()
    return rec_set
