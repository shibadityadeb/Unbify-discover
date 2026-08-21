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


def penetration_change(cur_mentions: int, cur_total: int,
                       prev_mentions: int, prev_total: int,
                       min_sample: int = 10) -> dict:
    """How a capability's share of relevant postings changed between two
    periods. Returns BOTH the percentage-point change and the relative change,
    labeled — they are different numbers and must never be conflated. Below
    the minimum sample in either period, the answer is insufficient."""
    if cur_total < min_sample or prev_total < min_sample:
        return {"state": "insufficient",
                "note": f"Insufficient sample (needs ≥{min_sample} postings per period; "
                        f"have {cur_total} current, {prev_total} previous)"}
    cur_share = cur_mentions / cur_total * 100
    prev_share = prev_mentions / prev_total * 100
    out = {"state": "ok",
           "currentSharePct": round(cur_share, 1),
           "previousSharePct": round(prev_share, 1),
           "ppChange": round(cur_share - prev_share, 1),
           "ppChangeUnit": "percentage_points",
           "currentMentions": cur_mentions, "currentTotal": cur_total,
           "previousMentions": prev_mentions, "previousTotal": prev_total}
    if prev_share > 0:
        out["relativeChangePct"] = round((cur_share - prev_share) / prev_share * 100, 1)
        out["relativeChangeUnit"] = "relative_percent"
    else:
        out["relativeChangePct"] = None
        out["relativeNote"] = "No baseline share — relative change undefined"
    return out


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
