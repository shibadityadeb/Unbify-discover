"""WorldIntelligenceIngestionService.

SOURCE ADAPTERS → RAW → VALIDATE → NORMALIZE → ENTITY RESOLUTION → DEDUPE →
SIGNAL EXTRACTION → QUALITY → FRESHNESS → CANONICAL GRAPH.

Failures never wipe intelligence: the previous valid snapshot stays served,
marked by freshness. The LLM never replaces a missing source.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime

from sqlalchemy.orm import Session

from ..models import (WICapability, WIIndustry, WIIngestionRun, WILicenseRequirement,
                      WIOccupation, WIOccupationAlias, WIOccupationCapability,
                      WIOccupationExternalMapping, WIOccupationTransition, WIProblem,
                      WISource, WISourceObservation)
from .sources import SOURCE_CLASS_WEIGHT, ingestible, seed_sources

NORMALIZATION_VERSION = "norm_v1"
EXTRACTOR_VERSION = "ext_v1"


def _hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:32]


def start_run(db: Session, source_id: str) -> WIIngestionRun:
    run = WIIngestionRun(source_id=source_id,
                         normalization_version=NORMALIZATION_VERSION,
                         extractor_version=EXTRACTOR_VERSION)
    db.add(run)
    db.flush()
    return run


def finish_run(db: Session, run: WIIngestionRun, status: str, counts: dict,
               error: str | None = None) -> None:
    run.status = status
    run.record_count = counts.get("records", 0)
    run.deduplicated_count = counts.get("deduplicated", 0)
    run.validation_failures = counts.get("invalid", 0)
    total = max(1, run.record_count)
    run.quality = {
        "valid_pct": round(1 - counts.get("invalid", 0) / total, 3),
        "duplicate_pct": round(counts.get("deduplicated", 0) / total, 3),
        "unknown_occupation_rate": round(counts.get("unknown_occupation", 0) / total, 3),
        "missing_geography_rate": round(counts.get("missing_geo", 0) / total, 3),
    }
    run.completed_at = datetime.utcnow()
    run.error = error


def record_observation(db: Session, run: WIIngestionRun, source: WISource, *,
                       signal_type: str, value: dict, occupation_refs: list[str],
                       geography: str = "*", geography_level: str = "country",
                       skills: list[str] | None = None, external_id: str | None = None,
                       raw_reference: str | None = None) -> WISourceObservation | None:
    payload = {"s": source.id, "t": signal_type, "v": value, "o": occupation_refs, "g": geography}
    content_hash = _hash(payload)
    existing = (db.query(WISourceObservation)
                .filter_by(source_id=source.id, content_hash=content_hash).first())
    if existing:
        return None   # change detection: identical observation, no recompute needed
    obs = WISourceObservation(
        source_id=source.id, ingestion_run_id=run.id, external_id=external_id,
        content_hash=content_hash, geography=geography, geography_level=geography_level,
        occupation_refs=occupation_refs, skills=skills or [], signal_type=signal_type,
        value=value, source_quality=SOURCE_CLASS_WEIGHT.get(source.type, 0.3) * source.trust_score,
        raw_reference=raw_reference)
    db.add(obs)
    db.flush()
    return obs


def ingest_source(db: Session, source_id: str, records: list[dict]) -> WIIngestionRun:
    """Generic entry: pre-normalized records from any adapter. Rejects
    non-compliant sources; dedupes; tracks quality."""
    source = db.get(WISource, source_id)
    run = start_run(db, source_id)
    if source is None:
        finish_run(db, run, "failed", {}, error="unknown source")
        return run
    ok, why = ingestible(source)
    if not ok:
        finish_run(db, run, "failed", {}, error=why)
        return run
    counts = {"records": len(records), "deduplicated": 0, "invalid": 0,
              "unknown_occupation": 0, "missing_geo": 0}
    for rec in records:
        if not rec.get("signal_type") or not isinstance(rec.get("value"), dict):
            counts["invalid"] += 1
            continue
        refs = rec.get("occupation_refs") or []
        if not refs:
            counts["unknown_occupation"] += 1
        if not rec.get("geography"):
            counts["missing_geo"] += 1
        obs = record_observation(db, run, source,
                                 signal_type=rec["signal_type"], value=rec["value"],
                                 occupation_refs=refs, geography=rec.get("geography", "*"),
                                 geography_level=rec.get("geography_level", "country"),
                                 skills=rec.get("skills"), external_id=rec.get("external_id"),
                                 raw_reference=rec.get("raw_reference"))
        if obs is None:
            counts["deduplicated"] += 1
    finish_run(db, run, "completed", counts)
    return run


# ---------------- seed adapters (flow through the same pipeline) ----------------

def seed_ontology(db: Session) -> int:
    """Taxonomy seed source → canonical ontology. Idempotent."""
    from . import ontology_seed as seed
    seed_sources(db)
    if db.query(WIOccupation).count() >= len(seed.OCCUPATIONS):
        return 0
    run = start_run(db, "src_seed_taxonomy")
    for cid, label in seed.CAPABILITIES:
        if not db.get(WICapability, cid):
            db.add(WICapability(id=cid, label=label))
    for iid, label in seed.INDUSTRIES:
        if not db.get(WIIndustry, iid):
            db.add(WIIndustry(id=iid, label=label))
    db.flush()
    added = 0
    for (oid, label, work_class, pathways, regulated, self_emp, ai_exp, ai_aug,
         aliases, onet, caps, envs) in seed.OCCUPATIONS:
        if db.get(WIOccupation, oid):
            continue
        db.add(WIOccupation(id=oid, preferred_label=label, work_class=work_class,
                            pathway_potentials=pathways, regulated=regulated,
                            self_employment_prevalence=self_emp,
                            ai_automation_exposure=ai_exp, ai_augmentation_potential=ai_aug,
                            physical_environment=envs))
        db.flush()
        db.add(WIOccupationAlias(occupation_id=oid, alias=label.lower()))
        for alias in aliases:
            db.add(WIOccupationAlias(occupation_id=oid, alias=alias.lower()))
        if onet:
            db.add(WIOccupationExternalMapping(occupation_id=oid, scheme="onet", external_id=onet))
        for cap, weight in caps:
            db.add(WIOccupationCapability(occupation_id=oid, capability_id=cap, weight=weight))
        added += 1
    for frm, to, kind, note, strength in seed.TRANSITIONS:
        db.add(WIOccupationTransition(from_occupation_id=frm, to_occupation_id=to,
                                      kind=kind, evidence_note=note, strength=strength))
    for pid, label, industries, caps, note in seed.PROBLEMS:
        if not db.get(WIProblem, pid):
            db.add(WIProblem(id=pid, label=label, industries=industries,
                             solved_by_capabilities=caps, evidence_note=note))
    for occ, jur, req, restricted in seed.LICENSES:
        db.add(WILicenseRequirement(occupation_id=occ, jurisdiction=jur,
                                    requirement=req, restricted_activities=restricted))
    db.flush()
    finish_run(db, run, "completed", {"records": added})
    return added


def seed_baseline_signals(db: Session) -> WIIngestionRun | None:
    """Baseline labor-statistics observations → the normal ingestion path."""
    from . import ontology_seed as seed
    from ..models import WISourceObservation as Obs
    if db.query(Obs).filter_by(source_id="src_seed_labor_stats").count() > 0:
        return None
    records = [{"signal_type": sig, "value": {"level": val},
                "occupation_refs": [occ], "geography": geo, "geography_level": "country"}
               for occ, sig, val, geo in seed.BASELINE_OBSERVATIONS]
    return ingest_source(db, "src_seed_labor_stats", records)
