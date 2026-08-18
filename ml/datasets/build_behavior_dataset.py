"""Behavior dataset: per-interaction features -> completed/skipped label."""
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api"))

from app.db import SessionLocal  # noqa: E402
from app.models import DiscoverSession, InteractionInstance, Response  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from features.profile_features import FEATURE_VERSION, profile_vector  # noqa: E402

DATASET_VERSION = "behavior_v1"
OUT = Path(__file__).resolve().parents[1] / "registry" / "datasets"


def build() -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    with SessionLocal() as db:
        for inst in db.query(InteractionInstance).filter(InteractionInstance.status != "pending").all():
            session = db.get(DiscoverSession, inst.session_id)
            resp = db.query(Response).filter_by(instance_id=inst.id).first()
            rows.append({
                "features": profile_vector(session.dimensions or {}),
                "type": inst.type, "chapter": inst.chapter,
                "label_completed": 1 if inst.status == "answered" else 0,
                "latency_ms": resp.latency_ms if resp else None,
            })
    stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    path = OUT / f"{DATASET_VERSION}_{stamp}.jsonl"
    with path.open("w") as f:
        f.write(json.dumps({"_meta": {"dataset_version": DATASET_VERSION,
                                      "feature_version": FEATURE_VERSION,
                                      "rows": len(rows), "built_at": stamp}}) + "\n")
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(f"wrote {len(rows)} rows -> {path}")
    return path


if __name__ == "__main__":
    build()
