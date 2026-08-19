"""Latency instrumentation.

Perceived latency is a product concern, so it is measured rather than guessed:
each response records how long persistence, signal processing, hypothesis
sync, policy selection and LLM generation actually took. Percentiles are
computed from these samples so a UX complaint can be traced to a real phase.
"""
from __future__ import annotations

import time
from contextlib import contextmanager

from sqlalchemy.orm import Session

from .models import RequestLatency

# starting targets (§16) — measured, not permanent
BUDGETS_MS = {
    "persist": 300,
    "signals": 300,
    "hypotheses": 300,
    "policy": 150,
    "llm": 6000,
    "total": 1000,
}


class PhaseTimer:
    """Collects phase durations for one request without touching the database."""

    def __init__(self) -> None:
        self.phases: dict[str, int] = {}
        self._t0 = time.perf_counter()

    @contextmanager
    def phase(self, name: str):
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed = int((time.perf_counter() - start) * 1000)
            self.phases[name] = self.phases.get(name, 0) + elapsed

    def total_ms(self) -> int:
        return int((time.perf_counter() - self._t0) * 1000)

    def over_budget(self) -> list[str]:
        out = [p for p, ms in self.phases.items() if ms > BUDGETS_MS.get(p, 10_000)]
        if self.total_ms() > BUDGETS_MS["total"]:
            out.append("total")
        return out


def record(db: Session, session_id: str | None, kind: str, timer: PhaseTimer,
           detail: dict | None = None) -> None:
    db.add(RequestLatency(
        session_id=session_id, kind=kind,
        total_ms=timer.total_ms(), phases=timer.phases,
        over_budget=timer.over_budget(), detail=detail or {}))


def percentiles(db: Session, kind: str | None = None, limit: int = 500) -> dict:
    q = db.query(RequestLatency).order_by(RequestLatency.created_at.desc())
    if kind:
        q = q.filter(RequestLatency.kind == kind)
    rows = q.limit(limit).all()
    if not rows:
        return {"samples": 0}

    def pct(values: list[int], p: float) -> int:
        if not values:
            return 0
        ordered = sorted(values)
        idx = min(len(ordered) - 1, int(round((p / 100) * (len(ordered) - 1))))
        return ordered[idx]

    totals = [r.total_ms for r in rows]
    out = {"samples": len(rows),
           "total": {f"p{p}": pct(totals, p) for p in (50, 75, 95, 99)}}
    phase_names = {name for r in rows for name in (r.phases or {})}
    out["phases"] = {
        name: {f"p{p}": pct([r.phases[name] for r in rows if name in (r.phases or {})], p)
               for p in (50, 95)}
        for name in sorted(phase_names)}
    out["overBudgetRate"] = round(
        sum(1 for r in rows if r.over_budget) / len(rows), 3)
    return out
