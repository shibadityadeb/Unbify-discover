"""Append-friendly event stream — the learning foundation."""
from __future__ import annotations

from sqlalchemy.orm import Session

from .models import Event


def emit(db: Session, session_id: str | None, type_: str, payload: dict | None = None) -> None:
    db.add(Event(session_id=session_id, type=type_, payload=payload or {}))
