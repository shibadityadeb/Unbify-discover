"""Offline policy evaluation from propensity-logged decisions.
Inverse Propensity Scoring (IPS) + a simple direct-method hybrid — the gate a
candidate policy must pass before shadow deployment."""
from __future__ import annotations

import json
from pathlib import Path

REWARD_WEIGHTS = {"completed": 0.4, "calibration": 0.6}  # reward_v1 composite


def composite_reward(components: dict) -> float:
    return sum(REWARD_WEIGHTS.get(k, 0.0) * v for k, v in (components or {}).items()
               if isinstance(v, (int, float)))


def ips_estimate(dataset_path: str | Path, candidate_choose) -> dict:
    """candidate_choose(context, eligible) -> action. Returns IPS value estimate."""
    total, matched, value = 0, 0, 0.0
    for line in Path(dataset_path).read_text().splitlines():
        row = json.loads(line)
        if "_meta" in row:
            continue
        total += 1
        candidate_action = candidate_choose(row["context"], row["eligible"])
        if candidate_action == row["action"] and row["propensity"] > 0:
            matched += 1
            value += composite_reward(row["reward_components"]) / row["propensity"]
    return {"n": total, "matched": matched,
            "ips_value": value / total if total else 0.0,
            "match_rate": matched / total if total else 0.0}
