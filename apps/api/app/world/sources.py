"""Source registry + compliance. Ingestion may only touch sources whose
compliance record is complete — a scraper being technically able to fetch
something is never authorization to fetch it."""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import WISource

# class-level evidence weights: source classes stay separate (PART 17)
SOURCE_CLASS_WEIGHT = {
    "official_taxonomy": 1.0, "government": 0.95, "professional_body": 0.85,
    "industry_body": 0.8, "education": 0.75, "research": 0.8,
    "job_board": 0.65, "company_careers": 0.6, "marketplace": 0.55,
    "news": 0.45, "community": 0.35, "other": 0.3,
}

REQUIRED_COMPLIANCE_KEYS = ("terms_reviewed", "license_known", "storage_permitted", "usage_known")


def compliant(source: WISource) -> tuple[bool, str]:
    c = source.compliance or {}
    missing = [k for k in REQUIRED_COMPLIANCE_KEYS if not c.get(k)]
    if missing:
        return False, f"compliance incomplete: {', '.join(missing)}"
    if source.access_method == "permitted_crawl" and not c.get("crawl_policy_reviewed"):
        return False, "crawl policy not reviewed"
    return True, "ok"


def ingestible(source: WISource) -> tuple[bool, str]:
    if not source.enabled:
        return False, "source disabled"
    return compliant(source)


SEED_SOURCES = [
    {"id": "src_seed_taxonomy", "name": "UNBIFY curated occupation taxonomy (O*NET/ESCO-informed)",
     "type": "official_taxonomy", "country_coverage": ["*"], "access_method": "dataset",
     "refresh_policy": "on_upstream_version", "ttl_hours": 24 * 90,
     "allowed_uses": ["occupation_ontology"], "trust_score": 0.95, "enabled": True,
     "compliance": {"terms_reviewed": True, "license_known": True, "storage_permitted": True,
                    "usage_known": True, "retention_rules": "indefinite"}},
    {"id": "src_seed_labor_stats", "name": "Aggregated public labor statistics (baseline)",
     "type": "government", "country_coverage": ["*"], "access_method": "dataset",
     "refresh_policy": "monthly", "ttl_hours": 24 * 45,
     "allowed_uses": ["market_signals"], "trust_score": 0.9, "enabled": True,
     "compliance": {"terms_reviewed": True, "license_known": True, "storage_permitted": True,
                    "usage_known": True, "retention_rules": "indefinite"}},
    {"id": "src_bls_projections", "name": "U.S. BLS Employment Projections 2023–33",
     "type": "government", "country_coverage": ["us"], "access_method": "dataset",
     "refresh_policy": "on_upstream_version", "ttl_hours": 24 * 365,
     "allowed_uses": ["market_signals"], "trust_score": 0.95, "enabled": True,
     "compliance": {"terms_reviewed": True, "license_known": True, "storage_permitted": True,
                    "usage_known": True, "retention_rules": "public domain (US federal data)"}},
    {"id": "src_industry_outlook", "name": "WEF Future of Jobs Report 2025 (curated readings)",
     "type": "research", "country_coverage": ["*"], "access_method": "dataset",
     "refresh_policy": "on_upstream_version", "ttl_hours": 24 * 365,
     "allowed_uses": ["market_signals"], "trust_score": 0.8, "enabled": True,
     "compliance": {"terms_reviewed": True, "license_known": True, "storage_permitted": True,
                    "usage_known": True, "retention_rules": "curated summary readings only"}},
    {"id": "src_apify_job_postings", "name": "Live job postings (company career sites via Apify)",
     "type": "job_board", "country_coverage": ["*"], "access_method": "api",
     "refresh_policy": "daily", "ttl_hours": 72,
     "allowed_uses": ["market_signals"], "trust_score": 0.6, "enabled": True,
     # postings come from the fantastic-jobs career-site API actor: employers'
     # own public career pages / ATS feeds, retrieved through Apify's paid API.
     # No LinkedIn or other prohibited scraping is involved.
     "compliance": {"terms_reviewed": True, "license_known": True, "storage_permitted": True,
                    "usage_known": True, "retention_rules": "postings retained for trend windows"}},
    {"id": "src_community_signals", "name": "Community discussion aggregate (official API access)",
     "type": "community", "country_coverage": ["*"], "access_method": "api",
     "refresh_policy": "weekly", "ttl_hours": 24 * 14,
     "allowed_uses": ["qualitative_signals"], "trust_score": 0.35, "enabled": False,
     "compliance": {"terms_reviewed": False, "license_known": False, "storage_permitted": False,
                    "usage_known": False}},
    # LinkedInAuthorizedAdapter boundary: exists, DISABLED, requires an official
    # partnership + explicit authorization. Scraped LinkedIn data — direct or
    # via third parties — never enters production intelligence.
    {"id": "src_linkedin_authorized", "name": "LinkedIn (official API — requires partnership)",
     "type": "professional_body", "country_coverage": ["*"], "access_method": "licensed_feed",
     "refresh_policy": "manual", "ttl_hours": 24 * 30,
     "allowed_uses": [], "trust_score": 0.0, "enabled": False,
     "compliance": {"terms_reviewed": False, "license_known": False, "storage_permitted": False,
                    "usage_known": False}},
]


def seed_sources(db: Session) -> int:
    added = 0
    for s in SEED_SOURCES:
        row = db.get(WISource, s["id"])
        if not row:
            db.add(WISource(**s))
            added += 1
        else:
            # seed-managed rows follow the seed's compliance verdict — a DB
            # created before a source was cleared must not stay stuck disabled
            row.enabled = s["enabled"]
            row.compliance = s["compliance"]
            row.name = s["name"]
    db.flush()
    return added
