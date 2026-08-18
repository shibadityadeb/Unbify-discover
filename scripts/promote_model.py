"""Explicit model promotion: candidate -> evaluated -> shadow -> canary -> production."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.db import SessionLocal
from app.models import ModelRegistryEntry

ORDER = ["candidate", "evaluated", "shadow", "canary", "production", "retired"]

if __name__ == "__main__":
    model_id, target = sys.argv[1], sys.argv[2]
    assert target in ORDER
    with SessionLocal() as db:
        m = db.get(ModelRegistryEntry, model_id)
        assert m, "unknown model"
        current = ORDER.index(m.state)
        assert ORDER.index(target) == current + 1 or target == "retired", \
            f"cannot jump {m.state} -> {target}; promote one stage at a time"
        m.state = target
        db.commit()
        print(f"{m.name} v{m.version}: -> {target}")
