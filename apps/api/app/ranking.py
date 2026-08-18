"""Explainable ranking. Heuristic first; XGBoost behind the same interface,
shadow-only until real outcome data justifies promotion. Factor contributions
are persisted — explanation derives from actual scoring, never post-hoc."""
from __future__ import annotations

from abc import ABC, abstractmethod

from sqlalchemy.orm import Session

from .models import DiscoverSession, ModelRegistryEntry, Opportunity, RecommendationItem, RecommendationSet, ShadowPrediction

RANKING_VERSION = "heuristic_v1"


class RankingModel(ABC):
    version: str

    @abstractmethod
    def score(self, session: DiscoverSession, opp: Opportunity) -> tuple[float, dict]:
        """returns (score, factor_contributions)"""


class HeuristicRankingModel(RankingModel):
    version = RANKING_VERSION

    def score(self, session: DiscoverSession, opp: Opportunity) -> tuple[float, dict]:
        dims = session.dimensions or {}

        def est(dim: str) -> float:
            return dims.get(dim, {}).get("estimate", 0.0)

        def conf(dim: str) -> float:
            return dims.get(dim, {}).get("confidence", 0.0)

        factors: dict[str, float] = {}
        fit = 0.0
        total_w = 0.0
        for dim, w in (opp.preferred_features or {}).items():
            contribution = est(dim) * conf(dim) * w
            fit += contribution
            total_w += abs(w)
            if abs(contribution) > 0.04:
                factors[f"fit:{dim}"] = round(contribution, 3)
        fit = fit / total_w if total_w else 0.0

        leverage = 0.3 * est("domain_expertise") + 0.25 * est("network") + 0.2 * est("audience") + 0.25 * est("reputation")
        factors["leverage"] = round(leverage, 3)
        demand = opp.demand_score - 0.5
        factors["market_demand"] = round(demand, 3)
        ai_lev = (opp.ai_leverage_score - 0.5) * max(0.0, est("ai_leverage"))
        factors["ai_leverage"] = round(ai_lev, 3)

        risk_map = {"low": 0.15, "medium": 0.45, "medium-high": 0.65, "high": 0.85}
        opp_risk = risk_map.get(opp.risk_profile, 0.5)
        user_risk = (est("risk_tolerance") + 1) / 2
        risk_mismatch = max(0.0, opp_risk - user_risk)
        factors["risk_mismatch"] = round(-risk_mismatch, 3)

        constraint_penalty = 0.0
        if opp.time_to_first_value == "months" and est("time_availability") < -0.3:
            constraint_penalty += 0.25
            factors["time_constraint"] = -0.25
        if opp.startup_capital in ("medium", "high") and est("capital_availability") < 0:
            constraint_penalty += 0.2
            factors["capital_constraint"] = -0.2
        if est("income_urgency") > 0.4 and opp.time_to_first_value == "months":
            constraint_penalty += 0.2
            factors["income_urgency"] = -0.2

        score = 0.45 * fit + 0.2 * leverage + 0.15 * demand + 0.1 * ai_lev - 0.5 * risk_mismatch - constraint_penalty
        factors["_fit_total"] = round(fit, 3)
        return score, factors


class XGBoostRankingModel(RankingModel):
    """Learned ranker scaffold. Loads a registered artifact; runs in SHADOW mode
    only — never authoritative until explicitly promoted through the registry."""
    version = "xgboost_shadow"

    def __init__(self, artifact_uri: str):
        import xgboost as xgb  # optional heavy import
        self._model = xgb.Booster()
        self._model.load_model(artifact_uri)

    def score(self, session: DiscoverSession, opp: Opportunity) -> tuple[float, dict]:
        import numpy as np
        import xgboost as xgb
        from .dimensions import DIMENSIONS
        dims = session.dimensions or {}
        row = [dims.get(d, {}).get("estimate", 0.0) for d in sorted(DIMENSIONS)]
        row += [opp.demand_score, opp.ai_leverage_score, opp.human_differentiation_score]
        pred = float(self._model.predict(xgb.DMatrix(np.array([row])))[0])
        return pred, {"learned_score": round(pred, 4)}


def diversity_rerank(scored: list[tuple[Opportunity, float, dict]], n: int = 3) -> list[tuple[Opportunity, float, dict]]:
    """Deliberately diverse: at most one opportunity per pathway family
    until every family is represented or candidates run out."""
    scored = sorted(scored, key=lambda t: t[1], reverse=True)
    out: list[tuple[Opportunity, float, dict]] = []
    used_pathways: set[str] = set()
    for item in scored:
        if len(out) >= n:
            break
        if item[0].pathway_type not in used_pathways:
            out.append(item)
            used_pathways.add(item[0].pathway_type)
    for item in scored:  # backfill if fewer families than n
        if len(out) >= n:
            break
        if item not in out:
            out.append(item)
    return out


def rank_and_persist(db: Session, session: DiscoverSession, candidates: list[Opportunity],
                     profile_version_id: str | None = None) -> RecommendationSet:
    ranker = HeuristicRankingModel()
    scored = []
    for opp in candidates:
        score, factors = ranker.score(session, opp)
        scored.append((opp, score, factors))
    top = diversity_rerank(scored, n=3)

    rec_set = RecommendationSet(session_id=session.id, ranking_model=ranker.version,
                                profile_version_id=profile_version_id)
    db.add(rec_set)
    db.flush()
    for rank, (opp, score, factors) in enumerate(top, start=1):
        db.add(RecommendationItem(set_id=rec_set.id, opportunity_id=opp.id, rank=rank,
                                  score=round(score, 4), factor_contributions=factors))
    # shadow inference: log learned-model predictions alongside, never affecting rank
    shadow = db.query(ModelRegistryEntry).filter_by(family="ranking", state="shadow").first()
    if shadow:
        try:
            model = XGBoostRankingModel(shadow.artifact_uri)
            for opp, score, _ in top:
                s_score, s_factors = model.score(session, opp)
                db.add(ShadowPrediction(model_id=shadow.id, session_id=session.id,
                                        subject=f"rank:{opp.id}",
                                        production_value={"score": score},
                                        shadow_value={"score": s_score, **s_factors}))
        except Exception:
            pass
    db.flush()
    return rec_set
