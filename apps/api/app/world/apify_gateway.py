"""The single Apify boundary — a DATA ACQUISITION layer, nothing more.

Apify never decides what a career means, what ranks first, or what a
profession requires. It fetches external evidence; UNBIFY normalizes it into
observations, aggregates signals, and does all the reasoning.

Every Apify interaction in the codebase goes through this module: actor runs,
task runs, synchronous runs with a strict budget, run polling, dataset
retrieval, webhook validation, and usage/cost recording.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime

import httpx
from sqlalchemy.orm import Session

from ..models import SourceHealth, WIApifyActorConfig, WISource
from .sources import ingestible

APIFY_BASE = "https://api.apify.com/v2"
SYNC_BUDGET_SECONDS = 25          # a request must never hang on scraping
POLL_TIMEOUT_SECONDS = 20

# input keys that must never leave UNBIFY, whatever a template contains
FORBIDDEN_INPUT_KEYS = {"name", "email", "userId", "sessionId", "answers", "profile",
                        "transcript", "hypotheses", "notes", "freeText"}


def token() -> str | None:
    return os.environ.get("APIFY_TOKEN") or None


def enabled() -> bool:
    return bool(token())


# ---------------- webhook ----------------

def verify_webhook(payload_body: bytes, signature: str | None) -> bool:
    """If a secret is configured it must match. No secret configured means we
    reject rather than trust — inbound payloads are never blindly believed."""
    secret = os.environ.get("APIFY_WEBHOOK_SECRET", "")
    if not secret:
        return False
    expected = hmac.new(secret.encode(), payload_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def validate_run_event(db: Session, payload: dict) -> dict:
    """Beyond the signature: the run must be one WE started, for a known
    actor config, in a state we expect."""
    resource = (payload or {}).get("resource") or {}
    run_id = resource.get("id") or (payload or {}).get("runId")
    actor_id = resource.get("actId")
    if not run_id:
        return {"ok": False, "error": "no run id in payload"}
    from . import jobs
    job = jobs.by_apify_run(db, run_id)
    if not job:
        return {"ok": False, "error": "unknown run — not started by us"}
    cfg_id = (job.scope or {}).get("actorConfigId")
    if cfg_id:
        cfg = db.get(WIApifyActorConfig, cfg_id)
        if cfg and actor_id and cfg.actor_id != actor_id:
            return {"ok": False, "error": "actor mismatch for this run"}
    return {"ok": True, "job": job, "runId": run_id,
            "datasetId": resource.get("defaultDatasetId"),
            "status": resource.get("status")}


# ---------------- health + cost ----------------

def _health(db: Session, source_id: str) -> SourceHealth:
    row = db.get(SourceHealth, source_id)
    if not row:
        row = SourceHealth(source_id=source_id)
        db.add(row)
        db.flush()
    return row


def record_run(db: Session, source_id: str, *, success: bool, records: int = 0,
               cost_usd: float = 0.0) -> None:
    h = _health(db, source_id)
    h.total_runs = (h.total_runs or 0) + 1
    h.total_cost_usd = round((h.total_cost_usd or 0.0) + cost_usd, 6)
    if success:
        h.last_success = datetime.utcnow()
        h.latest_record_count = records
        h.failure_count = 0
    else:
        h.last_failure = datetime.utcnow()
        h.failure_count = (h.failure_count or 0) + 1
    db.flush()


def note_usefulness(db: Session, source_id: str, useful_observations: int = 0,
                    recommendations_affected: int = 0) -> None:
    """§66/§99 — learn which sources actually change recommendations."""
    h = _health(db, source_id)
    h.useful_observations = (h.useful_observations or 0) + useful_observations
    h.recommendations_affected = (h.recommendations_affected or 0) + recommendations_affected
    db.flush()


# ---------------- runs ----------------

def _clean_input(template: dict, overrides: dict | None) -> dict:
    payload = {**(template or {}), **(overrides or {})}
    for key in list(payload):
        if key in FORBIDDEN_INPUT_KEYS:
            payload.pop(key)
    return payload


def _resolve(db: Session, actor_config_id: str) -> tuple[WIApifyActorConfig | None, WISource | None, str]:
    cfg = db.get(WIApifyActorConfig, actor_config_id)
    if not cfg or not cfg.enabled:
        return None, None, "actor config missing or disabled"
    source = db.get(WISource, cfg.source_id)
    if source is None:
        return None, None, "source missing"
    ok, why = ingestible(source)
    if not ok:
        return None, source, f"source not ingestible: {why}"
    if not enabled():
        return None, source, "APIFY_TOKEN not configured"
    return cfg, source, "ok"


def start_run(db: Session, actor_config_id: str, input_overrides: dict | None = None) -> dict:
    """Asynchronous run: create it, persist the run id, return immediately."""
    cfg, source, why = _resolve(db, actor_config_id)
    if not cfg:
        return {"ok": False, "error": why}
    actor_input = _clean_input(cfg.input_template, input_overrides)
    endpoint = ("actor-tasks" if (cfg.input_template or {}).get("_isTask") else "acts")
    try:
        with httpx.Client(timeout=30) as client:
            res = client.post(f"{APIFY_BASE}/{endpoint}/{cfg.actor_id}/runs",
                              params={"token": token()}, json=actor_input)
        if res.status_code not in (200, 201):
            record_run(db, source.id, success=False)
            return {"ok": False, "error": f"apify {res.status_code}"}
        data = res.json().get("data", {})
        return {"ok": True, "runId": data.get("id"), "status": data.get("status"),
                "datasetId": data.get("defaultDatasetId")}
    except Exception as e:                      # network/timeout — never fatal
        record_run(db, source.id, success=False)
        return {"ok": False, "error": str(e)[:200]}


def run_sync(db: Session, actor_config_id: str, input_overrides: dict | None = None,
             budget_seconds: int = SYNC_BUDGET_SECONDS) -> dict:
    """Fast targeted run inside the request budget. If it doesn't finish in
    time we hand back the run id and continue asynchronously — Discover never
    fails because scraping was slow."""
    cfg, source, why = _resolve(db, actor_config_id)
    if not cfg:
        return {"ok": False, "error": why}
    actor_input = _clean_input(cfg.input_template, input_overrides)
    try:
        with httpx.Client(timeout=budget_seconds) as client:
            res = client.post(
                f"{APIFY_BASE}/acts/{cfg.actor_id}/run-sync-get-dataset-items",
                params={"token": token(), "timeout": budget_seconds, "clean": "true"},
                json=actor_input)
        if res.status_code == 200:
            items = res.json()
            record_run(db, source.id, success=True, records=len(items) if isinstance(items, list) else 0)
            return {"ok": True, "completed": True, "items": items if isinstance(items, list) else []}
        record_run(db, source.id, success=False)
        return {"ok": False, "completed": False, "error": f"apify {res.status_code}"}
    except (httpx.TimeoutException, httpx.ReadTimeout):
        # over budget: fall back to async and let the webhook/worker finish it
        started = start_run(db, actor_config_id, input_overrides)
        return {"ok": True, "completed": False, "continuedAsync": True, **started}
    except Exception as e:
        record_run(db, source.id, success=False)
        return {"ok": False, "completed": False, "error": str(e)[:200]}


def get_run(run_id: str) -> dict | None:
    if not enabled():
        return None
    try:
        with httpx.Client(timeout=15) as client:
            res = client.get(f"{APIFY_BASE}/actor-runs/{run_id}", params={"token": token()})
        return res.json().get("data") if res.status_code == 200 else None
    except Exception:
        return None


def fetch_dataset(dataset_id: str, limit: int = 5000) -> list[dict]:
    if not enabled():
        return []
    try:
        with httpx.Client(timeout=60) as client:
            res = client.get(f"{APIFY_BASE}/datasets/{dataset_id}/items",
                             params={"token": token(), "clean": "true", "limit": limit})
        return res.json() if res.status_code == 200 else []
    except Exception:
        return []


def run_cost_usd(run: dict | None) -> float:
    if not run:
        return 0.0
    usage = run.get("usageTotalUsd")
    try:
        return float(usage or 0.0)
    except (TypeError, ValueError):
        return 0.0
