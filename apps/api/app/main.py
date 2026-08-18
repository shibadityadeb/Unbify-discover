"""UNBIFY Discover API — modular monolith. Serves /v1 + the experience layer."""
from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from .api.v1 import router as v1_router
from .config import settings
from .db import Base, engine, SessionLocal
from .llm.gateway import available as llm_available
from .opportunities import seed_opportunities

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("unbify")

settings.validate_production()

app = FastAPI(title="UNBIFY Discover", version="1.0.0", docs_url="/api/docs")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.app_url] if settings.is_production else ["*"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request.state.request_id = uuid.uuid4().hex[:12]
    response = await call_next(request)
    response.headers["X-Request-Id"] = request.state.request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.get("/health/live")
def live():
    return {"ok": True}


@app.get("/health/ready")
def ready():
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
    except Exception as e:  # pragma: no cover
        return {"ok": False, "db": str(e)}
    return {"ok": True, "db": True, "llm": llm_available(), "env": settings.app_env}


app.include_router(v1_router)

# dev convenience: schema + seeds (production uses Alembic migrations)
if not settings.is_production:
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        n = seed_opportunities(db)
        db.commit()
        if n:
            log.info("seeded %d opportunities", n)

# the experience layer
app.mount("/", StaticFiles(directory=str(settings.web_dir), html=True), name="web")
