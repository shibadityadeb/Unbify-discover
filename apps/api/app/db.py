from __future__ import annotations

from urllib.parse import (parse_qsl, quote, unquote, urlencode, urlsplit,
                          urlunsplit)

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

# Query params that connection poolers (Supabase/PgBouncer, Neon, …) put in the
# URL for other clients but libpq does not understand. They signal HOW to pool,
# not how to connect, so they are consumed here rather than passed through.
_POOLER_PARAMS = {"pgbouncer", "connection_limit", "pool_timeout", "schema"}


def _encode_userinfo(raw: str) -> str:
    """Percent-encode the password so special characters (@ : / ? #) in real
    credentials don't get parsed as URL structure. Splits on the LAST '@' in
    the authority, which is the only unambiguous separator."""
    if "://" not in raw:
        return raw
    scheme, _, rest = raw.partition("://")
    authority, sep, tail = rest.partition("/")
    if "@" not in authority:
        return raw
    userinfo, _, host = authority.rpartition("@")
    user, colon, password = userinfo.partition(":")
    safe_user = quote(unquote(user), safe="")
    safe_password = quote(unquote(password), safe="") if colon else ""
    creds = f"{safe_user}:{safe_password}" if colon else safe_user
    return f"{scheme}://{creds}@{host}{sep}{tail}"


def _prepare_url(raw: str) -> tuple[str, bool]:
    """→ (libpq-safe url, behind_transaction_pooler)."""
    if not raw.startswith("postgres"):
        return raw, False
    raw = _encode_userinfo(raw)
    parts = urlsplit(raw)
    kept, pooled = [], False
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() in _POOLER_PARAMS:
            if key.lower() == "pgbouncer" and value.lower() in ("true", "1"):
                pooled = True
            continue
        kept.append((key, value))
    # Supabase's transaction-mode pooler listens on 6543; it cannot hold
    # server-side prepared statements or long-lived sessions.
    if parts.port == 6543:
        pooled = True
    # normalize the driver so SQLAlchemy always picks psycopg2 explicitly
    scheme = parts.scheme
    if scheme in ("postgres", "postgresql"):
        scheme = "postgresql+psycopg2"
    return urlunsplit((scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment)), pooled


_raw_url = settings.effective_database_url()
_url, _behind_pooler = _prepare_url(_raw_url)
_is_sqlite = _url.startswith("sqlite")

if _is_sqlite:
    engine = create_engine(_url, connect_args={"check_same_thread": False})
elif _behind_pooler:
    # Reuse client connections: a remote pooler is often a continent away and a
    # fresh TLS handshake per request dominates latency. psycopg2 does not use
    # server-side prepared statements, so this is safe in transaction mode.
    engine = create_engine(
        _url, pool_size=10, max_overflow=10, pool_pre_ping=True, pool_recycle=280,
        connect_args={"sslmode": "require", "application_name": "unbify-discover",
                      "connect_timeout": 10},
    )
else:
    engine = create_engine(_url, pool_pre_ping=True, pool_size=5, max_overflow=5)

if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_connection, _record):  # pragma: no cover
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def is_postgres() -> bool:
    return engine.dialect.name == "postgresql"
