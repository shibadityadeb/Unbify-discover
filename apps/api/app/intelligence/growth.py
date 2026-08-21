"""GrowthCalculator: pure arithmetic over stored observations.

Growth is only ever computed from two real numbers covering two real periods.
Anything else returns an explicit insufficient-data result — a missing history
is reported, never interpolated."""
from __future__ import annotations

INSUFFICIENT = {"state": "insufficient", "note": "Insufficient historical data"}


def pct_change(current: float | None, previous: float | None) -> dict:
    if current is None or previous is None:
        return dict(INSUFFICIENT)
    if previous <= 0:
        return {"state": "insufficient",
                "note": "No baseline period to compare against"}
    return {"state": "ok", "pct": round((current - previous) / previous * 100, 1),
            "current": current, "previous": previous}


def yoy_from_periods(periods: list[dict]) -> dict:
    """periods: [{"year": 2024, "value": 123}, ...] → {"2025": pct, ...}"""
    ordered = sorted((p for p in periods
                      if p.get("year") is not None and p.get("value") is not None),
                     key=lambda p: p["year"])
    if len(ordered) < 2:
        return dict(INSUFFICIENT)
    out = {}
    for prev, cur in zip(ordered, ordered[1:]):
        change = pct_change(cur["value"], prev["value"])
        if change["state"] == "ok":
            out[str(cur["year"])] = change["pct"]
    return ({"state": "ok", "yoy": out, "periods": ordered}
            if out else dict(INSUFFICIENT))


def window_comparison(windows: dict) -> dict:
    """windows: {"30d": {...}, "90d": {...}, "12m": {...}} each with
    current/previous counts → per-window change. Surfaces structural growth
    and recent acceleration separately."""
    out = {}
    for name, w in windows.items():
        out[name] = pct_change(w.get("current"), w.get("previous"))
        out[name]["currentCount"] = w.get("current")
        out[name]["previousCount"] = w.get("previous")
    return out
