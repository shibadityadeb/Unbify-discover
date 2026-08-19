"""PostgreSQL job queue. No Redis, no Celery, no external broker.

Workers claim work with `SELECT ... FOR UPDATE SKIP LOCKED`, which gives us
exactly-one-worker-per-job semantics inside the database we already run.
SQLite (dev only) degrades to a plain ordered claim — correctness in
production comes from Postgres row locking.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db import is_postgres
from ..models import IntelligenceJob

MAX_ATTEMPTS = 3
STUCK_AFTER_MINUTES = 20


def enqueue(db: Session, job_type: str, scope: dict, scope_hash: str = "",
            priority: int = 100, dedupe: bool = True) -> IntelligenceJob:
    """Create a job. With dedupe, an identical pending/running scope is reused
    rather than duplicated — 50 users asking the same thing cause one run."""
    if dedupe and scope_hash:
        existing = (db.query(IntelligenceJob)
                    .filter(IntelligenceJob.scope_hash == scope_hash,
                            IntelligenceJob.job_type == job_type,
                            IntelligenceJob.status.in_(("pending", "running")))
                    .order_by(IntelligenceJob.created_at.asc()).first())
        if existing:
            return existing
    job = IntelligenceJob(job_type=job_type, scope=scope, scope_hash=scope_hash,
                          priority=priority)
    db.add(job)
    db.flush()
    return job


def claim(db: Session, job_types: list[str] | None = None) -> IntelligenceJob | None:
    """Atomically claim one pending job. Postgres uses FOR UPDATE SKIP LOCKED."""
    types = job_types or []
    if is_postgres():
        sql = """
            SELECT id FROM intelligence_jobs
             WHERE status = 'pending'
               AND attempt_count < :max_attempts
               {type_filter}
             ORDER BY priority ASC, created_at ASC
             FOR UPDATE SKIP LOCKED
             LIMIT 1
        """.format(type_filter="AND job_type = ANY(:types)" if types else "")
        params = {"max_attempts": MAX_ATTEMPTS}
        if types:
            params["types"] = types
        row = db.execute(text(sql), params).first()
        job = db.get(IntelligenceJob, row[0]) if row else None
    else:  # pragma: no cover - dev fallback
        q = db.query(IntelligenceJob).filter(
            IntelligenceJob.status == "pending",
            IntelligenceJob.attempt_count < MAX_ATTEMPTS)
        if types:
            q = q.filter(IntelligenceJob.job_type.in_(types))
        job = q.order_by(IntelligenceJob.priority.asc(),
                         IntelligenceJob.created_at.asc()).first()
    if not job:
        return None
    job.status = "running"
    job.started_at = datetime.utcnow()
    job.attempt_count = (job.attempt_count or 0) + 1
    db.flush()
    return job


def complete(db: Session, job: IntelligenceJob, metadata: dict | None = None) -> None:
    job.status = "completed"
    job.completed_at = datetime.utcnow()
    job.result_metadata = metadata or {}
    db.flush()


def fail(db: Session, job: IntelligenceJob, error: str) -> None:
    """Failed jobs retry until MAX_ATTEMPTS, then stay failed — a broken
    source never wipes existing intelligence, it just stops contributing."""
    job.last_error = str(error)[:500]
    job.status = "pending" if job.attempt_count < MAX_ATTEMPTS else "failed"
    if job.status == "failed":
        job.completed_at = datetime.utcnow()
    db.flush()


def requeue_stuck(db: Session) -> int:
    """A worker that died mid-job must not park work forever."""
    cutoff = datetime.utcnow() - timedelta(minutes=STUCK_AFTER_MINUTES)
    stuck = (db.query(IntelligenceJob)
             .filter(IntelligenceJob.status == "running",
                     IntelligenceJob.started_at < cutoff).all())
    for job in stuck:
        job.status = "pending" if job.attempt_count < MAX_ATTEMPTS else "failed"
        job.last_error = "worker timeout — requeued"
    db.flush()
    return len(stuck)


def by_apify_run(db: Session, apify_run_id: str) -> IntelligenceJob | None:
    return (db.query(IntelligenceJob)
            .filter(IntelligenceJob.apify_run_id == apify_run_id).first())


def status(db: Session, job_id: str) -> dict | None:
    job = db.get(IntelligenceJob, job_id)
    if not job:
        return None
    return {"id": job.id, "type": job.job_type, "status": job.status,
            "scope": job.scope, "attempts": job.attempt_count,
            "error": job.last_error, "result": job.result_metadata,
            "createdAt": job.created_at.isoformat(),
            "completedAt": job.completed_at.isoformat() if job.completed_at else None}
