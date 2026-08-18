"""Reward components attached to policy decisions. Raw components are stored
separately; the composite definition is versioned and computed offline."""
from __future__ import annotations

from sqlalchemy.orm import Session

from .models import PolicyDecision

REWARD_VERSION = "reward_v1"

CALIBRATION_REWARD = {"yes": 1.0, "first": 0.8, "second": 0.8, "kind_of": 0.45, "depends": 0.45, "no": 0.1}


def record(db: Session, decision_id: str | None, components: dict) -> None:
    if not decision_id:
        return
    decision = db.get(PolicyDecision, decision_id)
    if not decision:
        return
    merged = dict(decision.reward_components or {})
    merged.update(components)
    decision.reward_components = merged
    decision.reward_version = REWARD_VERSION
