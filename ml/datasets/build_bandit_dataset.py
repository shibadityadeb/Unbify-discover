"""Versioned bandit dataset builder: (context, eligible, action, propensity, reward).
Never trains on raw production tables directly — snapshots with metadata."""
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api"))

from app.db import SessionLocal  # noqa: E402
from app.models import PolicyDecision  # noqa: E402

DATASET_VERSION = "bandit_v1"
OUT = Path(__file__).resolve().parents[1] / "registry" / "datasets"


def build() -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    with SessionLocal() as db:
        for d in db.query(PolicyDecision).all():
            rows.append({
                "context": d.context, "eligible": d.eligible_actions,
                "action": d.chosen_action, "propensity": d.propensity,
                "policy_version": d.policy_version,
                "reward_components": d.reward_components,
                "at": d.created_at.isoformat(),
            })
    stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    path = OUT / f"{DATASET_VERSION}_{stamp}.jsonl"
    with path.open("w") as f:
        meta = {"_meta": {"dataset_version": DATASET_VERSION, "rows": len(rows), "built_at": stamp}}
        f.write(json.dumps(meta) + "\n")
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(f"wrote {len(rows)} decisions -> {path}")
    return path


if __name__ == "__main__":
    build()
