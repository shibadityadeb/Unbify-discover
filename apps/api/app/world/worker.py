"""Background worker. Runs from cron or a long-lived process — never inside a
web request. Claims jobs from PostgreSQL (FOR UPDATE SKIP LOCKED), executes
them, and updates world intelligence.

    python -m app.world.worker weekly     # broad scheduled refresh (Mode A)
    python -m app.world.worker drain      # process pending jobs (Mode B)
"""
from __future__ import annotations

import sys
from datetime import datetime

from sqlalchemy.orm import Session

from ..models import (DomainEnrichmentRequest, IntelligenceJob, WIApifyActorConfig,
                      WISource)
from . import apify_gateway, ingestion, jobs, refresh, signals
from .sources import ingestible

MAX_JOBS_PER_DRAIN = 25


# ---------------- MODE A: broad scheduled refresh ----------------

def weekly_refresh(db: Session) -> dict:
    """Keep World Intelligence reasonably fresh regardless of current users."""
    refreshed, skipped = [], []
    for source in db.query(WISource).all():
        ok, why = ingestible(source)
        if not ok:
            skipped.append({"source": source.id, "why": why})
            continue
        if source.id == "src_seed_taxonomy":
            ingestion.seed_ontology(db)
        elif source.id == "src_seed_labor_stats":
            ingestion.seed_baseline_signals(db)
        else:
            cfg = (db.query(WIApifyActorConfig)
                   .filter_by(source_id=source.id, enabled=True).first())
            if cfg:
                jobs.enqueue(db, "deep_refresh",
                             scope={"actorConfigId": cfg.id, "sourceId": source.id,
                                    "depth": "deep"},
                             scope_hash=f"broad:{source.id}", priority=150)
        refreshed.append(source.id)
    version = signals.recompute_signals(db)
    # standing domain demand shapes what gets enriched next
    for req in (db.query(DomainEnrichmentRequest)
                .order_by(DomainEnrichmentRequest.priority.asc()).limit(5).all()):
        jobs.enqueue(db, "domain_enrichment",
                     scope={"domain": req.domain, "geography": req.geography},
                     scope_hash=f"domain:{req.domain}:{req.geography}", priority=req.priority)
    return {"refreshed": refreshed, "skipped": skipped,
            "marketSnapshotVersion": version, "at": datetime.utcnow().isoformat()}


# ---------------- MODE B: job execution ----------------

def _select_sources(db: Session, scope: dict) -> list[WIApifyActorConfig]:
    """§67 — don't query every enabled source for every request. Pick by
    intent, coverage need and source health."""
    configs = db.query(WIApifyActorConfig).filter_by(enabled=True).all()
    usable = []
    for cfg in configs:
        source = db.get(WISource, cfg.source_id)
        if not source:
            continue
        ok, _ = ingestible(source)
        if ok:
            usable.append((source.trust_score, cfg))
    usable.sort(key=lambda p: -p[0])
    limit = 4 if scope.get("depth") == "deep" else 2
    return [cfg for _, cfg in usable[:limit]]


def run_targeted_refresh(db: Session, job: IntelligenceJob) -> dict:
    """Fetch only the slice this scope needs, normalize, recompute signals."""
    scope = job.scope or {}
    configs = _select_sources(db, scope)
    total_records = 0
    if not configs or not apify_gateway.enabled():
        # no permitted/configured live source — recompute from what we hold and
        # mark the scope honestly rather than inventing anything
        version = signals.recompute_signals(
            db, [scope["occupationId"]] if scope.get("occupationId") else None)
        coverage = refresh.coverage_score(db, scope.get("occupationId"),
                                          scope.get("geography", "*"))
        refresh.mark_refreshed(db, job.scope_hash, version, coverage)
        return {"sources": 0, "records": 0, "snapshotVersion": version,
                "note": "no live source available; existing intelligence retained"}
    for cfg in configs:
        overrides = {"queries": scope.get("queryTerms", []),
                     "geography": scope.get("geography", "*"),
                     "maxItems": 100 if scope.get("depth") != "deep" else 1000}
        if scope.get("depth") == "fast":
            result = apify_gateway.run_sync(db, cfg.id, overrides)
            if result.get("completed") and result.get("items"):
                records = normalize_items(db, cfg.source_id, result["items"], scope)
                total_records += records
            elif result.get("runId"):
                job.apify_run_id = result["runId"]     # webhook finishes it
                db.flush()
        else:
            started = apify_gateway.start_run(db, cfg.id, overrides)
            if started.get("runId"):
                job.apify_run_id = started["runId"]
                db.flush()
    version = signals.recompute_signals(
        db, [scope["occupationId"]] if scope.get("occupationId") else None)
    coverage = refresh.coverage_score(db, scope.get("occupationId"), scope.get("geography", "*"))
    refresh.mark_refreshed(db, job.scope_hash, version, coverage)
    return {"sources": len(configs), "records": total_records, "snapshotVersion": version}


def normalize_items(db: Session, source_id: str, items: list[dict], scope: dict) -> int:
    """Raw Apify rows become SourceObservations first — never recommendation
    rows directly. LLM assists messy-text normalization inside ingestion."""
    records = []
    for item in items[:1000]:
        if not isinstance(item, dict):
            continue
        records.append({
            "signal_type": item.get("signalType") or "demand_direction",
            "value": {"level": float(item.get("level", 0.5))} if isinstance(
                item.get("level", 0.5), (int, float)) else {"level": 0.5},
            "occupation_refs": ([scope["occupationId"]] if scope.get("occupationId") else []),
            "geography": scope.get("geography", "*"),
            "skills": item.get("skills") or [],
            "external_id": str(item.get("id") or "")[:200] or None,
            "raw_reference": str(item.get("url") or "")[:400] or None,
        })
    run = ingestion.ingest_source(db, source_id, records)
    apify_gateway.note_usefulness(db, source_id, useful_observations=run.record_count)
    return run.record_count


def run_normalize_dataset(db: Session, job: IntelligenceJob) -> dict:
    scope = job.scope or {}
    dataset_id = scope.get("datasetId")
    source_id = scope.get("sourceId")
    if not dataset_id or not source_id:
        return {"records": 0, "note": "missing dataset or source"}
    items = apify_gateway.fetch_dataset(dataset_id)
    records = normalize_items(db, source_id, items, scope)
    version = signals.recompute_signals(
        db, [scope["occupationId"]] if scope.get("occupationId") else None)
    if job.scope_hash:
        coverage = refresh.coverage_score(db, scope.get("occupationId"),
                                          scope.get("geography", "*"))
        refresh.mark_refreshed(db, job.scope_hash, version, coverage)
    return {"records": records, "snapshotVersion": version}


def run_domain_enrichment(db: Session, job: IntelligenceJob) -> dict:
    scope = job.scope or {}
    result = run_targeted_refresh(db, job)
    row = (db.query(DomainEnrichmentRequest)
           .filter_by(domain=scope.get("domain", ""), geography=scope.get("geography", "*"))
           .first())
    if row:
        row.last_enriched_at = datetime.utcnow()
        row.current_coverage = refresh.coverage_score(db, scope.get("occupationId"),
                                                      scope.get("geography", "*"))
        db.flush()
    return result


HANDLERS = {
    "targeted_refresh": run_targeted_refresh,
    "deep_refresh": run_targeted_refresh,
    "normalize_dataset": run_normalize_dataset,
    "domain_enrichment": run_domain_enrichment,
}


def reconcile_apify_runs(db: Session) -> dict:
    """Complete async Apify runs WITHOUT a webhook.

    APIFY_WEBHOOK_SECRET is optional; when it is unset we refuse inbound
    webhooks (unsigned callers are never trusted), so runs are reconciled by
    polling instead. With a secret configured this is simply a safety net for
    dropped deliveries.
    """
    from ..models import IntelligenceJob
    waiting = (db.query(IntelligenceJob)
               .filter(IntelligenceJob.apify_run_id.isnot(None),
                       IntelligenceJob.status.in_(("running", "pending"))).all())
    finished, still_running, failed = 0, 0, 0
    for job in waiting:
        run = apify_gateway.get_run(job.apify_run_id)
        if not run:
            still_running += 1
            continue
        state = run.get("status")
        if state == "SUCCEEDED":
            jobs.enqueue(db, "normalize_dataset",
                         scope={**(job.scope or {}),
                                "datasetId": run.get("defaultDatasetId")},
                         scope_hash=job.scope_hash, priority=40, dedupe=False)
            source_id = (job.scope or {}).get("sourceId")
            if source_id:
                apify_gateway.record_run(db, source_id, success=True,
                                         cost_usd=apify_gateway.run_cost_usd(run))
            job.apify_run_id = None       # handed over to the normalize job
            finished += 1
        elif state in ("FAILED", "ABORTED", "TIMED-OUT"):
            source_id = (job.scope or {}).get("sourceId")
            if source_id:
                apify_gateway.record_run(db, source_id, success=False)
            jobs.fail(db, job, f"apify run {state}")
            failed += 1
        else:
            still_running += 1
    db.flush()
    return {"finished": finished, "running": still_running, "failed": failed}


def drain(db: Session, limit: int = MAX_JOBS_PER_DRAIN) -> dict:
    """Claim and execute pending jobs. One source failing never stops the rest."""
    jobs.requeue_stuck(db)
    reconciled = reconcile_apify_runs(db)
    done, failed = 0, 0
    for _ in range(limit):
        job = jobs.claim(db, list(HANDLERS))
        if not job:
            break
        handler = HANDLERS.get(job.job_type)
        try:
            metadata = handler(db, job) if handler else {"note": "no handler"}
            jobs.complete(db, job, metadata)
            done += 1
        except Exception as e:            # a bad source must not poison the queue
            jobs.fail(db, job, str(e))
            failed += 1
        db.commit()
    return {"completed": done, "failed": failed, "apifyReconciled": reconciled}


if __name__ == "__main__":   # pragma: no cover
    from ..db import SessionLocal
    command = sys.argv[1] if len(sys.argv) > 1 else "drain"
    with SessionLocal() as session_db:
        if command == "weekly":
            print(weekly_refresh(session_db))
        elif command == "drain":
            print(drain(session_db))
        elif command == "reconcile":
            print(reconcile_apify_runs(session_db))
        session_db.commit()
