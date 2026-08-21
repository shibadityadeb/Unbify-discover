"""AIImpactAnalyzer: three separate readings per opportunity, never conflated —
AI leverage (the tools multiply this work), automation risk (the tools replace
parts of it), and human advantage (the parts needing presence, trust, and
judgment). High exposure + high human complementarity is an ATTRACTIVE
combination, and the model must be able to say so.

Where the opportunity resolves to a reference occupation, its curated
exposure/augmentation figures temper the hypothesis; otherwise the values are
the generator's structural assessment, labeled as such."""
from __future__ import annotations

from sqlalchemy.orm import Session


def _resolve_reference(db: Session, title: str):
    from ..models import WIOccupation, WIOccupationAlias
    t = (title or "").lower().strip()
    if not t:
        return None
    alias = db.query(WIOccupationAlias).filter(WIOccupationAlias.alias == t).first()
    if alias:
        return db.get(WIOccupation, alias.occupation_id)
    return None


def analyze(db: Session, candidate: dict) -> dict:
    lev = float(candidate.get("aiLeverage") or 0.5)
    risk = float(candidate.get("automationRisk") or 0.5)
    human = float(candidate.get("humanAdvantage") or 0.5)
    basis = "model_hypothesis"
    ref = _resolve_reference(db, candidate.get("title", ""))
    if ref is not None:
        # curated reference figures anchor the hypothesis at half weight
        lev = round((lev + float(ref.ai_augmentation_potential or lev)) / 2, 2)
        risk = round((risk + float(ref.ai_automation_exposure or risk)) / 2, 2)
        basis = "reference_anchored"
    label = lambda v: "high" if v >= 0.65 else "medium" if v >= 0.4 else "low"
    complementarity = round(max(0.0, min(1.0, human * (1 - risk / 2))), 2)
    return {
        "aiLeverage": round(lev, 2), "aiLeverageLabel": label(lev),
        "automationRisk": round(risk, 2), "automationRiskLabel": label(risk),
        "humanAdvantage": round(human, 2), "humanAdvantageLabel": label(human),
        "humanComplementarity": complementarity,
        "basis": basis,
        "note": ("High AI involvement with strong human complementarity — the tools "
                 "multiply the work rather than removing the person"
                 if lev >= 0.6 and complementarity >= 0.5 else None),
    }
