"""LinUCB contextual bandit — the Phase-2 ExperiencePolicy implementation.

INACTIVE by default: it trains offline from propensity-logged decisions and
must pass offline evaluation (ml/evaluation/policy_evaluation.py) and shadow
review before ever being promoted. It only chooses among eligible safe actions."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np


class LinUCBPolicy:
    version = "linucb_v1"

    def __init__(self, n_features: int, alpha: float = 0.8):
        self.alpha = alpha
        self.n = n_features
        self.A: dict[str, np.ndarray] = {}
        self.b: dict[str, np.ndarray] = {}

    def _ensure(self, action: str) -> None:
        if action not in self.A:
            self.A[action] = np.eye(self.n)
            self.b[action] = np.zeros(self.n)

    def choose_action(self, context_vec: np.ndarray, eligible_actions: list[str]) -> tuple[str, float, dict]:
        scores = {}
        for a in eligible_actions:
            self._ensure(a)
            A_inv = np.linalg.inv(self.A[a])
            theta = A_inv @ self.b[a]
            ucb = float(theta @ context_vec + self.alpha * np.sqrt(context_vec @ A_inv @ context_vec))
            scores[a] = ucb
        chosen = max(scores, key=scores.get)
        # deterministic UCB argmax -> propensity 1.0 among eligibles at this belief state
        return chosen, 1.0, scores

    def update(self, context_vec: np.ndarray, action: str, reward: float) -> None:
        self._ensure(action)
        self.A[action] += np.outer(context_vec, context_vec)
        self.b[action] += reward * context_vec

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps({
            "version": self.version, "alpha": self.alpha, "n": self.n,
            "A": {k: v.tolist() for k, v in self.A.items()},
            "b": {k: v.tolist() for k, v in self.b.items()},
        }))

    @classmethod
    def load(cls, path: str | Path) -> "LinUCBPolicy":
        data = json.loads(Path(path).read_text())
        p = cls(data["n"], data["alpha"])
        p.A = {k: np.array(v) for k, v in data["A"].items()}
        p.b = {k: np.array(v) for k, v in data["b"].items()}
        return p
