"""Profile Growth Intelligence — is THIS PERSON's capability set becoming more
valuable in the AI economy?

Different question from "is this job title growing": a capability can rise
inside occupations that are flat, and a person's future value may be a job, a
business, a service, a specialization or an AI-enabled version of what they
already do. The engine does not assume which before researching the profile.

Division of labor, same as the rest of the intelligence package: the LLM plans
(decomposes capabilities, proposes combinations and research queries) and
explains; the market/evidence/growth layers measure; a deterministic scorer
and classifier produce the verdicts. The LLM never supplies a number."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from ..llm import gateway
from ..models import DiscoverSession, DiscoveryCache
from . import growth, impact, market
from . import profile as profile_svc

CACHE_KIND = "profile_growth"
CACHE_TTL_HOURS = 24
MAX_LIVE_QUERIES = 6
MIN_SAMPLE = 10               # postings per period before a share is stated

GROWTH_SIGNALS = ("STRUCTURAL_GROWTH", "ACCELERATING_GROWTH", "STABLE",
                  "DECLINING", "EMERGING", "INSUFFICIENT_DATA")

# deterministic profile-growth score — configuration, not model output
SCORE_WEIGHTS = {
    "capability_demand_growth": 0.30,
    "ai_leverage": 0.20,
    "emerging_skill_growth": 0.20,
    "human_complementarity": 0.15,
    "market_breadth": 0.10,
    "recent_acceleration": 0.05,
}


# ---------------- the research plan ----------------

def _fallback_plan(profile: dict) -> dict:
    """Model unavailable: a thinner plan composed from the profile's own
    contents. Parameterized templates over THEIR capabilities — never a stored
    list of queries."""
    caps = profile_svc.capability_names(profile)[:8]
    industries = [str(x).lower() for x in profile.get("industry") or []]
    domain = industries[0] if industries else (profile.get("current_occupation") or "").lower()
    combos = []
    if domain and caps:
        combos.append({"label": f"{domain} + AI", "parts": [caps[0], domain, "AI"],
                       "why": f"their {caps[0]} applied where {domain} adopts AI"})
    if len(caps) >= 2:
        combos.append({"label": f"{caps[0]} + {caps[1]} + AI",
                       "parts": [caps[0], caps[1], "AI"],
                       "why": "their two strongest capabilities, AI-amplified"})
    queries = []
    for c in caps[:3]:
        queries.append({"query": c, "kind": "capability"})
        queries.append({"query": f"{c} AI", "kind": "capability_ai"})
    if domain:
        queries.append({"query": f"{domain} automation", "kind": "automation"})
        queries.append({"query": f"{domain} AI", "kind": "industry"})
    return {
        "core_capabilities": caps[:5],
        "transferable_capabilities": caps[2:6],
        "ai_adjacent_capabilities": [f"{c} with AI tools" for c in caps[:3]],
        "ai_complementary_capabilities": caps[:3],
        "vulnerable_capabilities": [],
        "emerging_combinations": combos,
        "capability_terms": [{"capability": c, "matchTerms": [c]} for c in caps[:6]],
        "queries": queries[:10],
    }


def _clean_plan(out: dict, profile: dict) -> dict | None:
    if not isinstance(out, dict):
        return None
    terms = [t for t in out.get("capability_terms") or []
             if isinstance(t, dict) and t.get("capability") and t.get("matchTerms")]
    queries = [q for q in out.get("queries") or []
               if isinstance(q, dict) and q.get("query")]
    if not terms or not queries:
        return None
    plan = {k: [str(x)[:80] for x in (out.get(k) or [])][:8] for k in
            ("core_capabilities", "transferable_capabilities", "ai_adjacent_capabilities",
             "ai_complementary_capabilities", "vulnerable_capabilities")}
    plan["emerging_combinations"] = [
        {"label": str(c.get("label", ""))[:80],
         "parts": [str(p)[:60] for p in (c.get("parts") or [])][:4],
         "why": str(c.get("why", ""))[:200]}
        for c in (out.get("emerging_combinations") or [])
        if isinstance(c, dict) and c.get("parts")][:5]
    plan["capability_terms"] = [
        {"capability": str(t["capability"]).lower()[:60],
         "matchTerms": [str(m).lower()[:60] for m in t["matchTerms"]][:6]}
        for t in terms][:8]
    plan["queries"] = [{"query": str(q["query"])[:80],
                        "kind": str(q.get("kind", "capability"))[:20]}
                       for q in queries][:14]
    return plan


def build_plan(db: Session, profile: dict) -> dict:
    out = gateway.generate(db, "profile_growth_plan_v1", {
        "capabilities": profile.get("capabilities", []),
        "current_occupation": profile.get("current_occupation", ""),
        "industry": profile.get("industry", []),
        "experience": profile.get("experience", []),
        "location": profile.get("location", ""),
        "career_goals": profile.get("career_goals", []),
        "ai_experience": profile.get("ai_experience", []),
    })
    plan = _clean_plan(out, profile) if out else None
    if plan:
        return {**plan, "basis": "llm"}
    return {**_fallback_plan(profile), "basis": "deterministic_fallback"}


# ---------------- measurement ----------------

def classify_growth(pen: dict, comparisons: dict) -> str:
    """Deterministic classification from computed observations only.
    pen: penetration_windows output; comparisons: penetration_change per window."""
    c30, c90, c12 = comparisons.get("30d"), comparisons.get("90d"), comparisons.get("12m")
    ok = [c for c in (c30, c90, c12) if c and c.get("state") == "ok"]
    w12 = pen.get("12m", {})
    recent_hits = pen.get("90d", {}).get("currentMentions", 0)
    recent_total = pen.get("90d", {}).get("currentTotal", 0)
    if not ok:
        # no valid comparison anywhere — but a dense, recent presence with no
        # measurable history is exactly what "emerging" means
        if recent_total >= MIN_SAMPLE and recent_hits / max(1, recent_total) >= 0.25 \
                and w12.get("previousTotal", 0) < MIN_SAMPLE:
            return "EMERGING"
        return "INSUFFICIENT_DATA"
    if all(c["ppChange"] < -1.0 for c in ok) and len(ok) >= 2:
        return "DECLINING"
    if c12 and c12.get("state") == "ok" and c12["ppChange"] >= 2.0:
        if c30 and c30.get("state") == "ok" and c30["ppChange"] >= c12["ppChange"] + 2.0:
            return "ACCELERATING_GROWTH"
        return "STRUCTURAL_GROWTH"
    if c30 and c30.get("state") == "ok" and c30["ppChange"] >= 3.0:
        return "ACCELERATING_GROWTH"
    return "STABLE"


def measure_capability(postings, capability: str, terms: list[str]) -> dict:
    pen = market.penetration_windows(postings, terms)
    comparisons = {name: growth.penetration_change(
        w["currentMentions"], w["currentTotal"],
        w["previousMentions"], w["previousTotal"], min_sample=MIN_SAMPLE)
        for name, w in pen.items()}
    signal = classify_growth(pen, comparisons)
    evidence = []
    best = comparisons.get("12m") if (comparisons.get("12m") or {}).get("state") == "ok" \
        else next((c for c in comparisons.values() if c.get("state") == "ok"), None)
    for name, c in comparisons.items():
        if c.get("state") == "ok":
            evidence.append({
                "source": "Live job postings (company career sites via Apify)",
                "metric": f"{capability} — share of relevant postings",
                "window": name,
                "previousSharePct": c["previousSharePct"],
                "currentSharePct": c["currentSharePct"],
                "ppChange": c["ppChange"], "ppChangeUnit": "percentage_points",
                "relativeChangePct": c.get("relativeChangePct"),
                "relativeChangeUnit": c.get("relativeChangeUnit"),
                "sample": {"current": c["currentTotal"], "previous": c["previousTotal"]},
                "retrieved_at": datetime.utcnow().isoformat() + "Z",
            })
    return {"capability": capability, "matchTerms": terms,
            "growthSignal": signal,
            "growth": ({"value": best.get("relativeChangePct"),
                        "unit": "relative_percent",
                        "ppChange": best.get("ppChange"),
                        "ppUnit": "percentage_points"} if best else None),
            "penetration": pen, "evidence": evidence}


def measure_combination(postings, combo: dict) -> dict:
    """A combination is present when a posting mentions at least two of its
    parts (AI terms included)."""
    parts = combo.get("parts") or []
    term_groups = [[p.lower()] + (["artificial intelligence", "llm", "machine learning"]
                                  if p.lower() == "ai" else [])
                   for p in parts]
    hits = total = 0
    now_hits_recent = 0
    for p in postings:
        text = market._posting_text(p)
        matched = sum(1 for group in term_groups
                      if any(t in text for t in group))
        total += 1
        if matched >= 2:
            hits += 1
    share = round(hits / total * 100, 1) if total >= MIN_SAMPLE else None
    signal = ("EMERGING" if share is not None and share >= 5 else
              "STABLE" if share is not None and share > 0 else
              "INSUFFICIENT_DATA")
    ev = []
    if share is not None:
        ev.append({"source": "Live job postings (company career sites via Apify)",
                   "metric": "combination presence in relevant postings",
                   "value": f"{hits}/{total} ({share}%)",
                   "retrieved_at": datetime.utcnow().isoformat() + "Z"})
    return {"combination": parts, "label": combo.get("label"),
            "why": combo.get("why"), "signal": signal,
            "postings": hits if total >= MIN_SAMPLE else None, "sharePct": share,
            "evidence": ev}


# ---------------- scoring, trajectory, gaps ----------------

def score_components(cap_reads: list[dict], combos: list[dict],
                     impact_reads: list[dict], breadth_queries: int) -> dict:
    grow = [c for c in cap_reads if c["growthSignal"] in
            ("STRUCTURAL_GROWTH", "ACCELERATING_GROWTH")]
    known = [c for c in cap_reads if c["growthSignal"] != "INSUFFICIENT_DATA"]
    demand_growth = len(grow) / len(known) if known else 0.0
    lev = [i["aiLeverage"] for i in impact_reads] or [0.0]
    human = [i["humanComplementarity"] for i in impact_reads] or [0.0]
    emerging = [c for c in combos if c["signal"] == "EMERGING"]
    emerging_growth = min(1.0, len(emerging) / 2) if combos else 0.0
    accel = sum(1 for c in cap_reads if c["growthSignal"] == "ACCELERATING_GROWTH")
    return {
        "capability_demand_growth": round(demand_growth, 3),
        "ai_leverage": round(sum(lev) / len(lev), 3),
        "emerging_skill_growth": round(emerging_growth, 3),
        "human_complementarity": round(sum(human) / len(human), 3),
        "market_breadth": round(min(1.0, breadth_queries / 8), 3),
        "recent_acceleration": round(min(1.0, accel / 2), 3),
        "measuredCapabilities": len(known),
    }


def score(comps: dict) -> dict:
    total = sum(SCORE_WEIGHTS[k] * float(comps.get(k) or 0) for k in SCORE_WEIGHTS)
    return {"score": round(total * 100),
            "weights": SCORE_WEIGHTS,
            "breakdown": {k: round(float(comps.get(k) or 0) * 100)
                          for k in SCORE_WEIGHTS}}


def trajectory(comps: dict, cap_reads: list[dict], vulnerable: list[str]) -> str:
    known = comps.get("measuredCapabilities", 0)
    signals = [c["growthSignal"] for c in cap_reads]
    if known == 0 and not any(s == "EMERGING" for s in signals):
        return "INSUFFICIENT_DATA"
    if signals.count("DECLINING") > max(1, len(signals) // 3) or \
            (len(vulnerable) >= 3 and comps.get("ai_leverage", 0) < 0.4):
        return "AT_RISK"
    if comps.get("recent_acceleration", 0) >= 0.5 or \
            signals.count("ACCELERATING_GROWTH") >= 1 and comps.get("capability_demand_growth", 0) >= 0.5:
        return "ACCELERATING"
    if signals.count("EMERGING") >= 1 or comps.get("emerging_skill_growth", 0) >= 0.5:
        return "EMERGING"
    return "STABLE"


def confidence(cap_reads: list[dict], live_postings: int) -> str:
    measured = sum(1 for c in cap_reads if c["growthSignal"] != "INSUFFICIENT_DATA")
    with_history = sum(1 for c in cap_reads if c["evidence"])
    if measured >= 3 and with_history >= 2 and live_postings >= 100:
        return "HIGH"
    if measured >= 2 and live_postings >= 30:
        return "MODERATE"
    if measured >= 1 or live_postings >= 10:
        return "LIMITED"
    return "INSUFFICIENT"


def skill_gaps(user_caps: list[str], combos: list[dict], cap_reads: list[dict]) -> list[dict]:
    from . import matcher
    gaps = []
    for combo in combos:
        if combo["signal"] == "INSUFFICIENT_DATA":
            continue
        for part in combo["combination"]:
            best = max((matcher._similarity(part, u) for u in user_caps), default=0.0)
            if best < 0.4 and part.lower() not in ("ai",):
                gaps.append({"skill": part,
                             "importance": "HIGH" if combo["signal"] == "EMERGING" else "MEDIUM",
                             "reason": f"Part of the {combo.get('label') or ' + '.join(combo['combination'])} "
                                       f"combination, which the market evidence marks {combo['signal'].lower()}",
                             "evidence": combo["evidence"]})
    if any(c.get("label") and "ai" in " ".join(c["combination"]).lower() for c in combos) \
            and not any("ai" in g["skill"].lower() for g in gaps):
        ai_present = max((matcher._similarity("ai tools", u) for u in user_caps), default=0.0)
        if ai_present < 0.4:
            gaps.append({"skill": "AI workflow fundamentals", "importance": "HIGH",
                         "reason": "Every measured combination pairs existing capabilities with AI",
                         "evidence": []})
    seen, out = set(), []
    for g in gaps:
        if g["skill"] not in seen:
            seen.add(g["skill"])
            out.append(g)
    return out[:5]


# ---------------- explanation (words for computed numbers) ----------------

def _fallback_explanation(payload: dict) -> dict:
    traj = payload["trajectory"]
    growing = [c["capability"] for c in payload["capabilities"]
               if c["growthSignal"] in ("STRUCTURAL_GROWTH", "ACCELERATING_GROWTH", "EMERGING")]
    vulnerable = payload["plan"].get("vulnerable_capabilities") or []
    combos = payload["emergingCombinations"]
    best_combo = next((c for c in combos if c["signal"] == "EMERGING"), combos[0] if combos else None)
    return {
        "trajectoryReading": {
            "ACCELERATING": "The parts of your work the market is asking for are growing, and recently faster.",
            "EMERGING": "Your capabilities are starting to show up in new, AI-adjacent combinations — early, but visible.",
            "STABLE": "Demand for what you do exists and is holding; no strong growth signal either way yet.",
            "AT_RISK": "Several of your capabilities face automation pressure without offsetting growth — worth acting on, not panicking over.",
            "INSUFFICIENT_DATA": "We don't yet hold enough market observations to read your trajectory honestly.",
        }.get(traj, ""),
        "whatIsBecomingValuable": (f"Measured against live postings: {', '.join(growing[:3])}."
                                   if growing else
                                   "Nothing can be called 'growing' yet from the evidence we hold — that is a data statement, not a judgment of you."),
        "mostExposed": (f"The most automation-exposed part of your current work: {', '.join(vulnerable[:2])}."
                        if vulnerable else
                        "No capability of yours stood out as strongly automation-exposed in this analysis."),
        "unusualCombination": (f"{' + '.join(best_combo['combination'])} — "
                               f"{best_combo.get('why') or 'your existing strengths, AI-amplified'}."
                               if best_combo else
                               "No combination could be measured yet."),
        "basis": "deterministic_fallback",
    }


def explain(db: Session, payload: dict) -> dict:
    fb = _fallback_explanation(payload)
    out = gateway.generate(db, "profile_growth_explain_v1", {
        "trajectory": payload["trajectory"],
        "score": payload["profileGrowthScore"],
        "capabilities": [{k: c[k] for k in ("capability", "growthSignal", "growth")}
                         for c in payload["capabilities"]],
        "emergingCombinations": payload["emergingCombinations"],
        "vulnerable": payload["plan"].get("vulnerable_capabilities"),
        "gaps": payload["skillGaps"],
        "confidence": payload["confidence"],
    })
    if out and out.get("trajectoryReading"):
        return {**fb, **{k: str(out.get(k))[:500] for k in
                         ("trajectoryReading", "whatIsBecomingValuable",
                          "mostExposed", "unusualCombination") if out.get(k)},
                "basis": "llm"}
    return fb


# ---------------- orchestration ----------------

def analyze(db: Session, session: DiscoverSession, force: bool = False) -> dict:
    prof_payload = profile_svc.extract(db, session)
    h = prof_payload["profileHash"]
    if not force:
        row = (db.query(DiscoveryCache)
               .filter_by(session_id=session.id, kind=CACHE_KIND, profile_hash=h)
               .order_by(DiscoveryCache.created_at.desc()).first())
        if row and (datetime.utcnow() - row.created_at).total_seconds() < CACHE_TTL_HOURS * 3600:
            return {**row.payload, "cache": {"hit": True}}

    profile = prof_payload["profile"]
    plan = build_plan(db, profile)
    geography = (profile.get("location") or "").strip() or "*"

    # live sweep through the existing market service (cached per query)
    live_ok, live_why = market.live_available(db)
    live_runs = []
    if live_ok:
        for q in plan["queries"][:MAX_LIVE_QUERIES]:
            live_runs.append({"query": q["query"], "kind": q.get("kind"),
                              **market.search(db, q["query"], geography)})

    postings = market.recent_postings(db)
    cap_reads = [measure_capability(postings, t["capability"], t["matchTerms"])
                 for t in plan["capability_terms"]]
    combos = [measure_combination(postings, c) for c in plan["emerging_combinations"]]

    # AI impact per core capability (reference-anchored where resolvable)
    impact_reads = []
    for cap in (plan["core_capabilities"] or [c["capability"] for c in cap_reads])[:6]:
        impact_reads.append({"capability": cap,
                             **impact.analyze(db, {"title": cap, "aiLeverage": 0.6,
                                                   "automationRisk": 0.4, "humanAdvantage": 0.6})})
    # attach ai leverage labels to capability reads where names line up
    for c in cap_reads:
        m = next((i for i in impact_reads if i["capability"] == c["capability"]), None)
        c["aiLeverage"] = (m or {}).get("aiLeverageLabel", "medium").upper()

    comps = score_components(cap_reads, combos, impact_reads, len(plan["queries"]))
    scored = score(comps)
    traj = trajectory(comps, cap_reads, plan.get("vulnerable_capabilities") or [])
    user_caps = profile_svc.capability_names(profile)

    payload = {
        "trajectory": traj,
        "overallGrowthSignal": ("ACCELERATING_GROWTH" if traj == "ACCELERATING" else
                                "EMERGING" if traj == "EMERGING" else
                                "DECLINING" if traj == "AT_RISK" else
                                "INSUFFICIENT_DATA" if traj == "INSUFFICIENT_DATA" else "STABLE"),
        "confidence": confidence(cap_reads, len(postings)),
        "profileGrowthScore": scored,
        "capabilities": cap_reads,
        "emergingCombinations": combos,
        "skillGaps": skill_gaps(user_caps, combos, cap_reads),
        "impact": impact_reads,
        "plan": {k: plan[k] for k in ("core_capabilities", "transferable_capabilities",
                                      "ai_adjacent_capabilities", "ai_complementary_capabilities",
                                      "vulnerable_capabilities", "queries", "basis")},
        "meta": {
            "profileHash": h, "geography": geography,
            "liveMarket": ({"enabled": True, "runs": live_runs}
                           if live_ok else {"enabled": False, "why": live_why}),
            "postingsAnalyzed": len(postings),
            "computedAt": datetime.utcnow().isoformat() + "Z",
        },
    }
    payload["explanation"] = explain(db, payload)
    db.add(DiscoveryCache(session_id=session.id, kind=CACHE_KIND,
                          profile_hash=h, payload=payload))
    db.flush()
    return {**payload, "cache": {"hit": False}}
