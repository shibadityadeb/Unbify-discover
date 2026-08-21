"""Accounts exist for one reason: the audit belongs to someone. The journey is
free and anonymous; only when the audit materializes does a person attach a
name to it — signup, login, or Google — and every session they finish is
reachable again through that identity.

Passwords are scrypt-hashed with a per-user salt (stdlib only). Google sign-in
is verified server-side against Google's tokeninfo endpoint, never trusted
from the client. Tokens are opaque random strings stored server-side so
revocation is a row delete."""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import AnonymousIdentity, AuthToken, DiscoverSession, User

_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}

# states in which a session has produced an audit worth returning to
AUDITED_STATES = ("MATERIALIZATION", "DISCOVER_WORKSPACE")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored or not stored.startswith("scrypt$"):
        return False
    try:
        _, salt_hex, digest_hex = stored.split("$")
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), **_SCRYPT)
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def issue_token(db: Session, user: User) -> str:
    token = secrets.token_hex(32)
    db.add(AuthToken(token=token, user_id=user.id))
    user.last_login_at = datetime.utcnow()
    return token


def user_for_token(db: Session, token: str | None) -> User | None:
    if not token:
        return None
    row = db.get(AuthToken, token)
    return db.get(User, row.user_id) if row else None


def user_by_email(db: Session, email: str) -> User | None:
    return db.execute(select(User).where(User.email == email.strip().lower())).scalar_one_or_none()


def verify_google_credential(credential: str) -> dict | None:
    """Ask Google who this ID token belongs to. Returns the claims when the
    token is valid AND issued for our client id, else None."""
    if not settings.google_client_id:
        return None
    try:
        resp = httpx.get("https://oauth2.googleapis.com/tokeninfo",
                         params={"id_token": credential}, timeout=8)
        if resp.status_code != 200:
            return None
        claims = resp.json()
    except httpx.HTTPError:
        return None
    if claims.get("aud") != settings.google_client_id:
        return None
    if claims.get("email_verified") not in ("true", True):
        return None
    return claims


def claim_session(db: Session, session: DiscoverSession, user: User) -> None:
    """Attach a finished (or in-flight) journey to its owner via the session's
    anonymous identity, which is the linkage the schema already models."""
    anon = db.get(AnonymousIdentity, session.anon_id)
    if anon and anon.user_id != user.id:
        anon.user_id = user.id


def latest_audit_session(db: Session, user: User) -> DiscoverSession | None:
    """The most recent session this user finished far enough to have an audit."""
    rows = db.execute(
        select(DiscoverSession)
        .join(AnonymousIdentity, DiscoverSession.anon_id == AnonymousIdentity.id)
        .where(AnonymousIdentity.user_id == user.id,
               DiscoverSession.journey_status.in_(AUDITED_STATES))
        .order_by(DiscoverSession.updated_at.desc())
    ).scalars().first()
    return rows


def public_user(user: User) -> dict:
    return {"id": user.id, "name": user.name, "email": user.email}
