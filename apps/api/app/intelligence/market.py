"""MarketSearchService + ApifyService: live postings through the existing
Apify boundary. All calls are server-side; the token never appears in any
payload this module returns. Postings are normalized, deduplicated, timestamped
and stored — every statistic downstream is computed from these rows."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import settings
from ..models import MarketPosting, MarketQueryRun, WIApifyActorConfig
from ..world import apify_gateway

SOURCE_ID = "src_apify_job_postings"
QUERY_TTL_HOURS = 12          # live postings: refresh every 6-12h
MAX_ITEMS_PER_QUERY = 30    # per live query per refresh; balances trend sample vs cost

_NOISE_TOKENS = {
    "senior", "sr", "junior", "jr", "lead", "staff", "principal", "head",
    "i", "ii", "iii", "iv", "entry", "level", "mid", "remote", "hybrid",
    "contract", "fulltime", "full", "time", "part", "the", "of", "and", "-",
    "(m/w/d)", "m/w/d", "m/f/d", "urgent", "new",
}
_STEMS = [("agentic", "agent"), ("agents", "agent"), ("engineers", "engineer"),
          ("developers", "developer"), ("specialists", "specialist"),
          ("consultants", "consultant"), ("managers", "manager"),
          ("scientists", "scientist"), ("analysts", "analyst")]


def cluster_key(title: str) -> str:
    """Normalize a posting title into a cluster key so 'Agentic AI Engineer',
    'AI Agent Engineer' and 'Senior LLM Agent Engineer' land together —
    emerging categories are discovered from the market, not pre-seeded."""
    t = re.sub(r"[^\w\s/]", " ", (title or "").lower())
    tokens = []
    for tok in t.split():
        if tok in _NOISE_TOKENS:
            continue
        for a, b in _STEMS:
            if tok == a:
                tok = b
                break
        tokens.append(tok)
    return " ".join(sorted(set(tokens)))[:120] or "unclassified"


def title_norm(title: str) -> str:
    t = re.sub(r"[^\w\s/&+-]", " ", (title or "")).strip()
    return " ".join(t.split())[:200]


def _parse_date(raw) -> datetime | None:
    if not raw:
        return None
    s = str(raw).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:19], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _first(item: dict, *keys):
    for k in keys:
        v = item.get(k)
        if v not in (None, "", []):
            return v
    return None


def normalize_posting(item: dict, query: str, geography: str) -> dict | None:
    title = _first(item, "title", "job_title", "name", "position")
    if not title:
        return None
    company = _first(item, "organization", "company", "company_name", "employer")
    location = _first(item, "locations_derived", "location", "job_location", "city")
    if isinstance(location, list):
        location = ", ".join(str(x) for x in location[:2])
    url = _first(item, "url", "job_url", "link", "apply_url", "absolute_url")
    posted = _parse_date(_first(item, "date_posted", "datePosted", "posted_at",
                                "published_at", "date", "listed_at"))

    def _num(v):
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None
    smin = _num(_first(item, "ai_salary_min_value", "salary_min"))
    smax = _num(_first(item, "ai_salary_max_value", "salary_max"))
    if smin is None and smax is None:
        smin = smax = _num(item.get("ai_salary_value"))
    # salaries are stored annualized — a $60/hour rate and a $350k/year salary
    # must never be averaged as if they shared a unit
    unit = str(item.get("ai_salary_unit_text") or "").upper()
    factor = {"HOUR": 2080, "DAY": 260, "WEEK": 52, "MONTH": 12}.get(unit, 1)
    smin = smin * factor if smin is not None else None
    smax = smax * factor if smax is not None else None
    cur = _first(item, "ai_salary_currency", "salary_currency")
    skills = _first(item, "ai_key_skills", "skills", "keySkills") or []
    if not isinstance(skills, list):
        skills = []
    desc = _first(item, "description_text", "description")
    remote = _first(item, "ai_remote_location_derived", "remote_derived")
    if isinstance(remote, list):
        remote = bool(remote)
    if remote is None and item.get("location_type"):
        remote = str(item["location_type"]).upper() == "TELECOMMUTE"
    content = f"{title}|{company}|{location}|{url}"
    return {
        "source_id": SOURCE_ID, "query": query[:200],
        "cluster_key": cluster_key(str(title)),
        "title": str(title)[:300], "title_norm": title_norm(str(title)),
        "company": str(company)[:200] if company else None,
        "location": str(location)[:200] if location else None,
        "geography": geography or "*",
        "remote": bool(remote) if remote is not None else None,
        "salary_min": smin, "salary_max": smax,
        "salary_currency": str(cur)[:10] if cur else None,
        "skills": [str(s)[:60] for s in skills[:15]],
        "description": str(desc).lower()[:4000] if desc else None,
        "url": str(url)[:600] if url else None,
        "posted_at": posted,
        "content_hash": hashlib.sha256(content.encode()).hexdigest(),
    }


def ensure_actor_config(db: Session) -> WIApifyActorConfig:
    cfg = (db.query(WIApifyActorConfig)
           .filter_by(source_id=SOURCE_ID, actor_id=settings.apify_jobs_actor).first())
    if not cfg:
        cfg = WIApifyActorConfig(
            source_id=SOURCE_ID, actor_id=settings.apify_jobs_actor,
            input_template={"limit": MAX_ITEMS_PER_QUERY, "descriptionType": "text"},
            refresh_strategy="on_demand", enabled=True)
        db.add(cfg)
        db.flush()
    return cfg


def live_available(db: Session) -> tuple[bool, str]:
    if settings.app_env == "test":
        return False, "live market never runs in tests"
    if not settings.live_market_enabled:
        return False, "live market disabled by configuration"
    if not apify_gateway.enabled():
        return False, "APIFY_TOKEN not configured"
    return True, "ok"


def _fresh_run(db: Session, query: str, geography: str) -> MarketQueryRun | None:
    cutoff = datetime.utcnow() - timedelta(hours=QUERY_TTL_HOURS)
    return (db.query(MarketQueryRun)
            .filter(MarketQueryRun.query == query[:200],
                    MarketQueryRun.geography == (geography or "*"),
                    MarketQueryRun.ran_at >= cutoff)
            .order_by(MarketQueryRun.ran_at.desc()).first())


def search(db: Session, query: str, geography: str | None = None,
           budget_seconds: int | None = None) -> dict:
    """Run one live query (respecting the freshness cache) and persist its
    postings. Returns run metadata only — statistics are computed separately
    from the stored rows."""
    geo = (geography or "*")
    ok, why = live_available(db)
    if not ok:
        return {"ok": False, "skipped": True, "why": why}
    fresh = _fresh_run(db, query, geo)
    if fresh:
        return {"ok": True, "cached": True, "ranAt": fresh.ran_at.isoformat() + "Z",
                "postings": fresh.postings_found}
    cfg = ensure_actor_config(db)
    overrides: dict = {"titleSearch": [query], "limit": MAX_ITEMS_PER_QUERY}
    if geo not in ("*", "", None, "remote"):
        overrides["locationSearch"] = [geo]
    res = apify_gateway.run_sync(db, cfg.id, overrides,
                                 budget_seconds=budget_seconds or apify_gateway.SYNC_BUDGET_SECONDS)
    if not res.get("ok") or not res.get("completed"):
        return {"ok": False, "skipped": False, "why": res.get("error") or "run not completed",
                "continuedAsync": res.get("continuedAsync", False)}
    stored = store_postings(db, res.get("items") or [], query, geo)
    db.add(MarketQueryRun(query=query[:200], geography=geo, source_id=SOURCE_ID,
                          postings_found=stored))
    db.flush()
    return {"ok": True, "cached": False, "postings": stored}


def store_postings(db: Session, items: list[dict], query: str, geography: str) -> int:
    stored = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        norm = normalize_posting(item, query, geography)
        if not norm:
            continue
        exists = (db.query(MarketPosting)
                  .filter_by(content_hash=norm["content_hash"]).first())
        if exists:
            continue
        db.add(MarketPosting(**norm))
        stored += 1
    db.flush()
    return stored


# ---------------- statistics over stored postings ----------------

def _count_between(db: Session, query: str | None, cluster: str | None,
                   geography: str, start: datetime, end: datetime) -> int:
    q = db.query(func.count(MarketPosting.id))
    if query:
        q = q.filter(MarketPosting.query == query[:200])
    if cluster:
        q = q.filter(MarketPosting.cluster_key == cluster)
    if geography and geography != "*":
        q = q.filter(MarketPosting.geography == geography)
    when = func.coalesce(MarketPosting.posted_at, MarketPosting.retrieved_at)
    return int(q.filter(when >= start, when < end).scalar() or 0)


def window_counts(db: Session, *, query: str | None = None, cluster: str | None = None,
                  geography: str = "*") -> dict:
    """Rolling windows: 30d vs previous 30d, 90d vs previous 90d, 12m vs
    previous 12m — computed from stored postings only."""
    now = datetime.utcnow()
    spans = {"30d": 30, "90d": 90, "12m": 365}
    out = {}
    for name, days in spans.items():
        cur_start = now - timedelta(days=days)
        prev_start = now - timedelta(days=2 * days)
        cur = _count_between(db, query, cluster, geography, cur_start, now)
        prev = _count_between(db, query, cluster, geography, prev_start, cur_start)
        out[name] = {"current": cur, "previous": prev if (prev or cur) else None}
    return out


def query_stats(db: Session, query: str, geography: str = "*") -> dict:
    rows = (db.query(MarketPosting)
            .filter(MarketPosting.query == query[:200]).limit(500).all())
    salaries = [(p.salary_min, p.salary_max, p.salary_currency)
                for p in rows if p.salary_min or p.salary_max]
    mids = [((s[0] or s[1]) + (s[1] or s[0])) / 2 for s in salaries]
    companies = {p.company for p in rows if p.company}
    skills: dict[str, int] = {}
    for p in rows:
        for s in p.skills or []:
            skills[s.lower()] = skills.get(s.lower(), 0) + 1
    last = max((p.retrieved_at for p in rows), default=None)
    return {
        "postings": len(rows),
        "companies": len(companies),
        "windows": window_counts(db, query=query, geography=geography),
        "salary": ({"median": round(sorted(mids)[len(mids) // 2]),
                    "samples": len(mids),
                    "currency": salaries[0][2] or "unknown"} if mids else None),
        "topSkills": sorted(skills.items(), key=lambda kv: -kv[1])[:8],
        "sampleUrls": [p.url for p in rows if p.url][:3],
        "lastRetrievedAt": last.isoformat() + "Z" if last else None,
    }


def candidate_postings(db: Session, title: str, search_terms: list[str],
                       geography: str = "*", days: int = 730,
                       scan_limit: int = 1000) -> list[MarketPosting]:
    """Stored postings relevant to one candidate: exact query matches for its
    search terms, plus title-token overlap against everything the sweep has
    pulled in. Live evidence must reach a candidate even when the posting came
    from a sibling query."""
    since = datetime.utcnow() - timedelta(days=days)
    q = (db.query(MarketPosting)
         .filter(MarketPosting.retrieved_at >= since))
    if geography and geography != "*":
        q = q.filter(MarketPosting.geography.in_([geography, "*"]))
    rows = q.order_by(MarketPosting.retrieved_at.desc()).limit(scan_limit).all()
    terms = {t.lower() for t in search_terms}
    want = set(cluster_key(title).split())
    for t in search_terms:
        want |= set(cluster_key(t).split())
    want -= {"ai"}                       # too generic to carry a match alone
    out = []
    for p in rows:
        if p.query.lower() in terms:
            out.append(p)
            continue
        have = set(p.cluster_key.split())
        if want and len(want & have) >= max(1, min(2, len(want) - 1)):
            out.append(p)
    return out


def postings_stats(db: Session, postings: list[MarketPosting]) -> dict:
    """The same statistics shape as query_stats, over an explicit posting set."""
    now = datetime.utcnow()
    spans = {"30d": 30, "90d": 90, "12m": 365}
    windows = {}
    for name, days in spans.items():
        cur_start = now - timedelta(days=days)
        prev_start = now - timedelta(days=2 * days)
        cur = prev = 0
        for p in postings:
            when = p.posted_at or p.retrieved_at
            if when >= cur_start:
                cur += 1
            elif when >= prev_start:
                prev += 1
        windows[name] = {"current": cur, "previous": prev if (prev or cur) else None}
    salaries = [((p.salary_min or p.salary_max) + (p.salary_max or p.salary_min)) / 2
                for p in postings if p.salary_min or p.salary_max]
    skills: dict[str, int] = {}
    for p in postings:
        for s in p.skills or []:
            skills[s.lower()] = skills.get(s.lower(), 0) + 1
    last = max((p.retrieved_at for p in postings), default=None)
    cur = next((p.salary_currency for p in postings if p.salary_currency), None)
    return {
        "postings": len(postings),
        "companies": len({p.company for p in postings if p.company}),
        "windows": windows,
        "salary": ({"median": round(sorted(salaries)[len(salaries) // 2]),
                    "samples": len(salaries), "currency": cur or "unknown"}
                   if salaries else None),
        "topSkills": sorted(skills.items(), key=lambda kv: -kv[1])[:8],
        "sampleUrls": [p.url for p in postings if p.url][:3],
        "lastRetrievedAt": last.isoformat() + "Z" if last else None,
    }


def _posting_text(p: MarketPosting) -> str:
    return " ".join(filter(None, [
        p.title_norm.lower() if p.title_norm else "",
        " ".join(s.lower() for s in (p.skills or [])),
        p.description or "",
    ]))


def mentions_capability(p: MarketPosting, terms: list[str]) -> bool:
    """A posting mentions a capability when ANY of its match terms appears in
    the title, extracted skills, or description text."""
    text = _posting_text(p)
    return any(t.lower().strip() in text for t in terms if t and len(t.strip()) > 1)


def recent_postings(db: Session, days: int = 730, limit: int = 2000) -> list[MarketPosting]:
    since = datetime.utcnow() - timedelta(days=days)
    return (db.query(MarketPosting)
            .filter(MarketPosting.retrieved_at >= since)
            .order_by(MarketPosting.retrieved_at.desc()).limit(limit).all())


def penetration_windows(postings: list[MarketPosting], terms: list[str]) -> dict:
    """Per rolling window: relevant postings, capability mentions, and share —
    the raw observations a penetration-growth claim is computed from."""
    now = datetime.utcnow()
    spans = {"30d": 30, "90d": 90, "12m": 365}
    out = {}
    for name, days in spans.items():
        cur_start = now - timedelta(days=days)
        prev_start = now - timedelta(days=2 * days)
        cur_total = cur_hits = prev_total = prev_hits = 0
        for p in postings:
            when = p.posted_at or p.retrieved_at
            hit = mentions_capability(p, terms)
            if when >= cur_start:
                cur_total += 1
                cur_hits += 1 if hit else 0
            elif when >= prev_start:
                prev_total += 1
                prev_hits += 1 if hit else 0
        out[name] = {"currentMentions": cur_hits, "currentTotal": cur_total,
                     "previousMentions": prev_hits, "previousTotal": prev_total}
    return out


def emerging_clusters(db: Session, days: int = 90, min_postings: int = 5,
                      min_companies: int = 3) -> list[dict]:
    """Clusters of normalized titles dense enough in the recent window to be a
    category of their own — discovered from live postings, not seeded."""
    since = datetime.utcnow() - timedelta(days=days)
    rows = (db.query(MarketPosting.cluster_key,
                     func.count(MarketPosting.id),
                     func.count(func.distinct(MarketPosting.company)))
            .filter(MarketPosting.retrieved_at >= since)
            .group_by(MarketPosting.cluster_key)
            .having(func.count(MarketPosting.id) >= min_postings).all())
    out = []
    for key, postings, companies in rows:
        if companies < min_companies or key == "unclassified":
            continue
        sample = (db.query(MarketPosting).filter_by(cluster_key=key)
                  .order_by(MarketPosting.retrieved_at.desc()).first())
        out.append({"cluster": key, "canonicalTitle": sample.title_norm if sample else key,
                    "postings": int(postings), "companies": int(companies),
                    "windows": window_counts(db, cluster=key)})
    return sorted(out, key=lambda c: -c["postings"])[:10]
