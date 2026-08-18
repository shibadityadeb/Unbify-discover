"""Phase-1 behavior model: P(interaction completed | profile, type).
Registers the artifact as `candidate` — promotion is always explicit."""
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal  # noqa: E402
from app.models import ModelRegistryEntry  # noqa: E402
from features.profile_features import FEATURE_VERSION  # noqa: E402

MIN_ROWS = 200  # never fabricate performance from tiny data


def train(dataset_path: str) -> None:
    rows = [json.loads(l) for l in Path(dataset_path).read_text().splitlines()]
    meta = rows[0]["_meta"]
    data = [r for r in rows[1:]]
    if len(data) < MIN_ROWS:
        print(f"refusing to train: {len(data)} rows < {MIN_ROWS}. "
              "Collect real usage first — an untrained model is not intelligence.")
        return
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import cross_val_score
    X = np.array([r["features"] for r in data])
    y = np.array([r["label_completed"] for r in data])
    model = LogisticRegression(max_iter=1000)
    auc = cross_val_score(model, X, y, cv=5, scoring="roc_auc").mean()
    model.fit(X, y)
    out_dir = Path(__file__).resolve().parents[1] / "registry" / "artifacts"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    artifact = out_dir / f"behavior_logreg_{stamp}.json"
    artifact.write_text(json.dumps({"coef": model.coef_.tolist(), "intercept": model.intercept_.tolist()}))
    with SessionLocal() as db:
        db.add(ModelRegistryEntry(name="behavior_completion", family="behavior",
                                  version=stamp, artifact_uri=str(artifact),
                                  feature_version=FEATURE_VERSION,
                                  dataset_ref=meta.get("built_at"),
                                  metrics={"cv_auc": round(float(auc), 4), "rows": len(data)},
                                  state="candidate"))
        db.commit()
    print(f"registered candidate behavior model, cv_auc={auc:.3f}")


if __name__ == "__main__":
    train(sys.argv[1])
