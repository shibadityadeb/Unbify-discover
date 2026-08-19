"""PublicFigureKnowledgeBase — stored, verified, structured evidence about the
documented PROFESSIONAL patterns of accomplished people.

The LLM never invents public-figure facts at request time. Everything the
matching pipeline can retrieve went through this ingestion path:

    SOURCE -> EXTRACT -> NORMALIZE -> REVIEW -> MAP TO APPROVED CONSTRUCTS
           -> STORE EVIDENCE + SOURCE -> EMBED -> VERSION -> RETRIEVABLE

Runtime source of truth is the database; `figure_seeds.py` is development seed
data that flows through this same pipeline.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from .models import (PublicFigure, PublicFigureAlias, PublicFigureEmbedding,
                     PublicFigureEvidence, PublicFigurePattern, PublicFigureSource,
                     PublicFigureVersion)

# the approved professional-pattern taxonomy — matching happens ONLY here
CONSTRUCTS = [
    "builder_orientation", "technical_depth", "commercial_orientation",
    "systems_thinking", "product_obsession", "long_term_orientation",
    "operational_leadership", "experimentation", "domain_depth",
    "risk_behavior", "learning_behavior", "distribution_orientation", "other",
]

# credible source kinds only; anonymous quote sites / fan pages never enter
ALLOWED_SOURCE_KINDS = {
    "interview", "speech", "biography", "book", "talk", "company_material", "profile",
}


class IngestionError(Exception):
    pass


def _validate(record: dict) -> None:
    if not record.get("id") or not record.get("name"):
        raise IngestionError("figure requires id and name")
    if not record.get("sources"):
        raise IngestionError(f"{record['id']}: sources are mandatory")
    for s in record["sources"]:
        if s.get("kind") not in ALLOWED_SOURCE_KINDS:
            raise IngestionError(f"{record['id']}: source kind '{s.get('kind')}' not allowed")
        if not s.get("title"):
            raise IngestionError(f"{record['id']}: source without title")
    evidence_ids = {e["id"] for e in record.get("evidence", [])}
    source_ids = {s["id"] for s in record["sources"]}
    for e in record.get("evidence", []):
        if e.get("source") not in source_ids:
            raise IngestionError(f"{record['id']}: evidence {e['id']} lacks a stored source")
        if not e.get("claim"):
            raise IngestionError(f"{record['id']}: evidence {e['id']} has no claim")
    if not record.get("patterns"):
        raise IngestionError(f"{record['id']}: no professional patterns")
    for p in record["patterns"]:
        if p.get("construct") not in CONSTRUCTS:
            raise IngestionError(f"{record['id']}: pattern construct '{p.get('construct')}' outside taxonomy")
        refs = p.get("evidence_refs", [])
        if not refs or any(r not in evidence_ids for r in refs):
            raise IngestionError(f"{record['id']}: pattern {p.get('id')} without stored evidence — fail closed")


def construct_vector(patterns: list[dict]) -> list[float]:
    """Embed a figure in construct space: confidence mass per approved construct."""
    vec = [0.0] * len(CONSTRUCTS)
    for p in patterns:
        try:
            vec[CONSTRUCTS.index(p["construct"])] = max(
                vec[CONSTRUCTS.index(p["construct"])], float(p.get("confidence", 0.6)))
        except ValueError:
            continue
    return vec


def ingest_figure(db: Session, record: dict) -> PublicFigure:
    """Idempotent upsert of one reviewed figure record through the full pipeline."""
    _validate(record)
    fig = db.get(PublicFigure, record["id"])
    version = (fig.record_version + 1) if fig else 1
    quality = min(1.0, sum(s.get("credibility", 0.6) for s in record["sources"]) / max(1, len(record["sources"])))
    if not fig:
        fig = PublicFigure(id=record["id"])
        db.add(fig)
    fig.name = record["name"]
    fig.primary_domains = record.get("domains", [])
    fig.professional_roles = record.get("roles", [])
    fig.evidence_quality = round(quality, 3)
    fig.record_version = version
    fig.last_verified_at = datetime.utcnow()
    fig.status = record.get("status", "active")

    db.flush()  # figure row first — no ORM relationships, so stage the flushes

    for alias in record.get("aliases", []):
        if not db.query(PublicFigureAlias).filter_by(figure_id=fig.id, alias=alias).first():
            db.add(PublicFigureAlias(figure_id=fig.id, alias=alias))

    for s in record["sources"]:
        row = db.get(PublicFigureSource, s["id"])
        if not row:
            row = PublicFigureSource(id=s["id"], figure_id=fig.id)
            db.add(row)
        row.kind, row.title = s["kind"], s["title"]
        row.publisher = s.get("publisher", "")
        row.url = s.get("url")
        row.published_at = str(s.get("published_at", "")) or None
        row.credibility = float(s.get("credibility", 0.6))

    db.flush()  # sources before evidence

    for e in record.get("evidence", []):
        row = db.get(PublicFigureEvidence, e["id"])
        if not row:
            row = PublicFigureEvidence(id=e["id"], figure_id=fig.id, source_id=e["source"], claim=e["claim"])
            db.add(row)
        row.source_id, row.claim = e["source"], e["claim"]
        row.review_status = e.get("review_status", "approved")

    db.flush()  # evidence before patterns that reference it

    for p in record["patterns"]:
        row = db.get(PublicFigurePattern, p["id"])
        if not row:
            row = PublicFigurePattern(id=p["id"], figure_id=fig.id, construct=p["construct"], description=p["description"])
            db.add(row)
        row.construct = p["construct"]
        row.description = p["description"]
        row.evidence_refs = p["evidence_refs"]
        row.confidence = float(p.get("confidence", 0.6))
        row.status = p.get("status", "active")

    # embed + version
    existing_emb = db.query(PublicFigureEmbedding).filter_by(figure_id=fig.id, pattern_id=None).first()
    vec = construct_vector(record["patterns"])
    if existing_emb:
        existing_emb.vector = vec
    else:
        db.add(PublicFigureEmbedding(figure_id=fig.id, vector=vec))
    db.add(PublicFigureVersion(figure_id=fig.id, version=version, snapshot={
        "name": record["name"], "patterns": record["patterns"], "sources": [s["id"] for s in record["sources"]],
    }))
    db.flush()
    return fig


def seed_figures(db: Session) -> int:
    from .figure_seeds import FIGURES
    added = 0
    for record in FIGURES:
        if not db.get(PublicFigure, record["id"]):
            ingest_figure(db, record)
            added += 1
    return added


def pattern_bundle(db: Session, pattern: PublicFigurePattern) -> dict | None:
    """Resolve pattern -> approved evidence -> stored source. Fail closed:
    a pattern whose evidence chain is broken is never shown."""
    claims = []
    for ref in pattern.evidence_refs or []:
        ev = db.get(PublicFigureEvidence, ref)
        if not ev or ev.review_status != "approved":
            continue
        src = db.get(PublicFigureSource, ev.source_id)
        if not src:
            continue
        claims.append({"claim": ev.claim, "source": {"title": src.title, "kind": src.kind,
                                                     "publisher": src.publisher, "published_at": src.published_at}})
    if not claims:
        return None
    return {"patternId": pattern.id, "construct": pattern.construct,
            "description": pattern.description, "confidence": pattern.confidence, "evidence": claims}
