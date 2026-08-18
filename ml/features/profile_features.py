"""Versioned feature builders — identical online and offline."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api"))

from app.dimensions import DIMENSIONS  # noqa: E402

FEATURE_VERSION = "feat_v1"
DIM_ORDER = sorted(DIMENSIONS)


def profile_vector(dimensions: dict) -> list[float]:
    """estimate + confidence per dimension, fixed order — 84 features."""
    row: list[float] = []
    for dim in DIM_ORDER:
        d = dimensions.get(dim, {})
        row.append(float(d.get("estimate", 0.0)))
        row.append(float(d.get("confidence", 0.0)))
    return row


def feature_names() -> list[str]:
    names = []
    for dim in DIM_ORDER:
        names += [f"{dim}__est", f"{dim}__conf"]
    return names
