"""QueryGenerator: capability profile + candidates + location → market search
queries. Queries are COMPOSED from the profile's own values — occupation × AI,
skills × AI, industry × automation, candidate search terms, location variants —
never copied from a stored query list."""
from __future__ import annotations

MAX_QUERIES = 10


def generate(profile: dict, candidates: list[dict], geography: str | None = None) -> dict:
    occupation = (profile.get("current_occupation") or "").strip().lower()
    industries = [str(x).lower() for x in profile.get("industry") or []]
    skills = [str(x).lower() for x in
              (profile.get("technical_skills") or []) + (profile.get("domain_knowledge") or [])]
    caps = [c.get("name", "") for c in profile.get("capabilities") or []]
    goals = [str(x).lower() for x in profile.get("career_goals") or []]
    intent = profile.get("entrepreneurial_intent", "none")

    queries: list[str] = []

    def add(q: str):
        q = " ".join(q.split()).strip()
        if q and len(q) > 2 and q not in queries:
            queries.append(q)

    if occupation:
        add(occupation)                       # 1. current occupation demand
        add(f"{occupation} AI")               # 4. AI-enabled version of current work
    for c in candidates:
        for t in c.get("searchTerms", [])[:2]:
            add(t)                            # 3/5. adjacent + AI-native roles, early —
                                              # these are what the sweep must cover
    for ind in industries[:2]:
        add(f"{ind} AI")
        add(f"{ind} automation")
    for s in (skills or caps)[:3]:
        add(f"{s} AI")                        # 2/7. transferable + emerging skills
    if intent in ("active", "operating"):
        base = industries[0] if industries else occupation
        if base:
            add(f"{base} consultant")         # 6. business/consulting demand
    for g in goals[:1]:
        add(g)
    return {"queries": queries[:MAX_QUERIES],
            "geography": (geography or profile.get("location") or "").strip() or None}
