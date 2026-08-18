"""Canonical Opportunity Catalog + retrieval pipeline:
HARD FILTERS -> CANDIDATE RETRIEVAL -> (ranking in ranking.py) -> DIVERSITY -> EXPLANATION.
The LLM never invents the candidate set."""
from __future__ import annotations

from sqlalchemy.orm import Session

from .models import DiscoverSession, Opportunity

SEED_OPPORTUNITIES: list[dict] = [
    # career
    {"id": "career_ai_ops_lead", "title": "AI Operations Lead", "pathway_type": "career",
     "industries": ["saas", "services", "logistics"],
     "description": "Own the retooling of a team's workflows around AI systems inside an existing organization.",
     "value_proposition": "Organizations are refitting everything; people who bridge old process and new leverage are scarce.",
     "preferred_features": {"systems_thinking": .9, "planning": .7, "ai_leverage": .8, "stability": .4, "facilitation": .5},
     "disqualifiers": {"income_urgency_max_wait": False},
     "skill_gaps": ["workflow mapping", "change management", "AI tool fluency"],
     "startup_capital": "none", "time_to_first_value": "weeks", "income_range": "salary + premium",
     "risk_profile": "low", "ai_leverage_score": .85, "human_differentiation_score": .6, "demand_score": .8},
    {"id": "career_product_translator", "title": "Domain-to-Product Translator", "pathway_type": "career",
     "industries": ["health", "finance", "education", "industry"],
     "description": "Become the person who turns deep domain knowledge into product decisions teams can build on.",
     "value_proposition": "Product teams overflow with builders and starve for domain judgment.",
     "preferred_features": {"domain_expertise": 1.0, "synthesis": .7, "empathy": .5, "teaching": .5},
     "skill_gaps": ["product discovery basics", "writing crisp specs"],
     "startup_capital": "none", "time_to_first_value": "weeks", "income_range": "salary",
     "risk_profile": "low", "ai_leverage_score": .6, "human_differentiation_score": .85, "demand_score": .7},
    {"id": "career_quiet_operator", "title": "Operations Backbone", "pathway_type": "career",
     "industries": ["any"],
     "description": "Run the machinery of a growing company — the person everything quietly routes through.",
     "value_proposition": "Every scaling company hits the moment it needs one person who sees the whole system.",
     "preferred_features": {"planning": .9, "detail_orientation": .7, "persistence": .7, "stability": .6, "facilitation": .4},
     "skill_gaps": ["tooling automation", "process design"],
     "startup_capital": "none", "time_to_first_value": "weeks", "income_range": "salary",
     "risk_profile": "low", "ai_leverage_score": .7, "human_differentiation_score": .55, "demand_score": .75},
    # consulting
    {"id": "consult_expertise", "title": "Independent Domain Consultant", "pathway_type": "consulting",
     "industries": ["any"],
     "description": "Package the judgment people already borrow from you into paid engagements.",
     "value_proposition": "Distribution costs almost nothing now; a small reputation compounds fast.",
     "prerequisite_features": {"domain_expertise": .15},
     "preferred_features": {"domain_expertise": 1.0, "autonomy": .7, "sales_comfort": .6, "network": .6, "teaching": .4},
     "skill_gaps": ["pricing", "positioning", "pipeline"],
     "startup_capital": "low", "time_to_first_value": "weeks-months", "income_range": "per-engagement",
     "risk_profile": "medium", "ai_leverage_score": .7, "human_differentiation_score": .9, "demand_score": .65},
    {"id": "consult_ai_adoption", "title": "AI Adoption Guide for SMBs", "pathway_type": "consulting",
     "industries": ["local business", "professional services"],
     "description": "Help ordinary businesses adopt AI tooling they don't have time to understand.",
     "value_proposition": "Millions of small firms know they're behind and will pay someone practical they trust.",
     "preferred_features": {"ai_leverage": .9, "teaching": .7, "relationship_building": .6, "implementation_affinity": .6},
     "skill_gaps": ["service packaging", "local outreach"],
     "startup_capital": "low", "time_to_first_value": "weeks", "income_range": "per-engagement",
     "risk_profile": "medium", "ai_leverage_score": .95, "human_differentiation_score": .7, "demand_score": .85},
    {"id": "consult_fractional", "title": "Fractional Specialist", "pathway_type": "consulting",
     "industries": ["startups", "saas"],
     "description": "Give several small companies a slice of a senior capability none can afford full-time.",
     "value_proposition": "Early companies need senior judgment in fractional doses.",
     "prerequisite_features": {"domain_expertise": .1},
     "preferred_features": {"domain_expertise": .9, "velocity": .5, "autonomy": .7, "planning": .5},
     "skill_gaps": ["scoping discipline", "parallel client management"],
     "startup_capital": "none", "time_to_first_value": "weeks-months", "income_range": "retainers",
     "risk_profile": "medium", "ai_leverage_score": .65, "human_differentiation_score": .8, "demand_score": .7},
    # entrepreneurship
    {"id": "ent_service_business", "title": "Productized Service Business", "pathway_type": "entrepreneurship",
     "industries": ["services"],
     "description": "Turn a repeatable skill into a fixed-scope, fixed-price service that can eventually run without you.",
     "value_proposition": "Productized services reach revenue faster than products and teach you the market.",
     "preferred_features": {"implementation_affinity": .7, "sales_comfort": .7, "planning": .5, "revenue_ambition": .6},
     "skill_gaps": ["offer design", "delivery systemization"],
     "startup_capital": "low", "time_to_first_value": "weeks-months", "income_range": "revenue",
     "risk_profile": "medium", "ai_leverage_score": .8, "human_differentiation_score": .6, "demand_score": .7},
    {"id": "ent_niche_audience", "title": "Niche Audience Business", "pathway_type": "entrepreneurship",
     "industries": ["media", "education"],
     "description": "Build a small, devoted audience around what you genuinely know, then serve it products.",
     "value_proposition": "A thousand true readers beat a million impressions.",
     "prerequisite_features": {"storytelling": -.2},
     "preferred_features": {"storytelling": .8, "audience": .7, "persistence": .7, "originality": .5, "teaching": .5},
     "skill_gaps": ["consistent publishing", "audience economics"],
     "startup_capital": "low", "time_to_first_value": "months", "income_range": "compounding",
     "risk_profile": "medium-high", "ai_leverage_score": .7, "human_differentiation_score": .9, "demand_score": .6},
    {"id": "ent_local_modernizer", "title": "Local Business Modernizer", "pathway_type": "entrepreneurship",
     "industries": ["local business"],
     "description": "Buy or partner into an unglamorous local business and modernize its operations.",
     "value_proposition": "A generation of owners is retiring; operational leverage is sitting on the table.",
     "preferred_features": {"planning": .7, "persistence": .8, "risk_tolerance": .7, "capital_availability": .7, "relationship_building": .5},
     "disqualifiers": {"min_capital": "medium"},
     "skill_gaps": ["deal evaluation", "small business finance"],
     "startup_capital": "high", "time_to_first_value": "months", "income_range": "equity + cashflow",
     "risk_profile": "high", "ai_leverage_score": .75, "human_differentiation_score": .7, "demand_score": .65},
    # builder
    {"id": "build_micro_product", "title": "Micro-Product Builder", "pathway_type": "builder",
     "industries": ["software"],
     "description": "Ship small, focused software products solving one sharp problem for one clear group.",
     "value_proposition": "AI-leveraged building means one person can now ship what took a team.",
     "preferred_features": {"implementation_affinity": .9, "originality": .7, "experimentation": .7, "autonomy": .6, "ai_leverage": .7},
     "skill_gaps": ["distribution", "pricing"],
     "startup_capital": "low", "time_to_first_value": "months", "income_range": "product revenue",
     "risk_profile": "medium-high", "ai_leverage_score": .95, "human_differentiation_score": .6, "demand_score": .6},
    {"id": "build_internal_tools", "title": "Internal Tools Builder", "pathway_type": "builder",
     "industries": ["any"],
     "description": "Build the small systems your organization or clients desperately need but never prioritize.",
     "value_proposition": "The gap between what teams need and what IT ships is a career.",
     "preferred_features": {"implementation_affinity": .8, "systems_thinking": .7, "detail_orientation": .5, "stability": .4},
     "skill_gaps": ["low-code/AI stack fluency", "requirements listening"],
     "startup_capital": "none", "time_to_first_value": "weeks", "income_range": "salary or contracts",
     "risk_profile": "low", "ai_leverage_score": .9, "human_differentiation_score": .55, "demand_score": .8},
    {"id": "build_creative_studio", "title": "One-Person Creative Studio", "pathway_type": "builder",
     "industries": ["design", "media"],
     "description": "Run a tiny studio delivering taste — brand, story, visuals — amplified by AI production tools.",
     "value_proposition": "Production got cheap; judgment and taste got scarce.",
     "prerequisite_features": {"aesthetic_sensitivity": 0.0},
     "preferred_features": {"aesthetic_sensitivity": .9, "originality": .7, "storytelling": .7, "autonomy": .6},
     "skill_gaps": ["client pipeline", "scope control"],
     "startup_capital": "low", "time_to_first_value": "weeks-months", "income_range": "project fees",
     "risk_profile": "medium", "ai_leverage_score": .85, "human_differentiation_score": .85, "demand_score": .6},
]


def seed_opportunities(db: Session) -> int:
    count = 0
    for opp in SEED_OPPORTUNITIES:
        if not db.get(Opportunity, opp["id"]):
            db.add(Opportunity(**opp))
            count += 1
    return count


def hard_filters(session: DiscoverSession, candidates: list[Opportunity]) -> list[Opportunity]:
    p = session.practical_context or {}
    out = []
    for opp in candidates:
        dq = opp.disqualifiers or {}
        # capital constraint: never propose high-capital paths to users without capital
        if dq.get("min_capital") == "medium":
            cap = (session.dimensions or {}).get("capital_availability", {}).get("estimate", 0)
            if cap < 0.15:
                continue
        # time constraint: months-to-value paths need real hours
        if opp.time_to_first_value == "months":
            hours = p.get("hours_per_week")
            if isinstance(hours, (int, float)) and hours < -0.6:
                continue
        out.append(opp)
    return out


def retrieve_candidates(db: Session, session: DiscoverSession) -> list[Opportunity]:
    candidates = db.query(Opportunity).filter(Opportunity.status == "active").all()
    return hard_filters(session, candidates)
