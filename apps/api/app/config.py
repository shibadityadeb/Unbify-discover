"""Environment configuration. Secrets come only from the environment / .env.
Production fails fast when required configuration is missing."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_dotenv() -> None:
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        # values may be quoted in .env files — the quotes are syntax, not data
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("\"", "'"):
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


_load_dotenv()


@dataclass(frozen=True)
class Settings:
    app_env: str = field(default_factory=lambda: os.environ.get("APP_ENV", "development"))
    database_url: str = field(default_factory=lambda: os.environ.get("DATABASE_URL", ""))
    litellm_key: str = field(default_factory=lambda: os.environ.get("LITELLM_KEY", ""))
    litellm_base_url: str = "https://litellm.gtor.app/v1"
    litellm_model: str = "gpt-5.6-luna"
    session_secret: str = field(default_factory=lambda: os.environ.get("SESSION_SECRET", "dev-only-secret"))
    google_client_id: str = field(default_factory=lambda: os.environ.get("GOOGLE_CLIENT_ID", ""))
    app_url: str = field(default_factory=lambda: os.environ.get("APP_URL", "http://localhost:8000"))
    apify_token: str = field(default_factory=lambda: os.environ.get("APIFY_TOKEN", ""))
    apify_webhook_secret: str = field(default_factory=lambda: os.environ.get("APIFY_WEBHOOK_SECRET", ""))
    # world-intelligence feature flags
    world_intelligence_enabled: bool = field(default_factory=lambda: os.environ.get("WORLD_INTELLIGENCE_ENABLED", "1") == "1")
    apify_ingestion_enabled: bool = field(default_factory=lambda: os.environ.get("APIFY_INGESTION_ENABLED", "0") == "1")
    community_signals_enabled: bool = field(default_factory=lambda: os.environ.get("COMMUNITY_SIGNALS_ENABLED", "0") == "1")
    targeted_market_refresh_enabled: bool = field(default_factory=lambda: os.environ.get("TARGETED_MARKET_REFRESH_ENABLED", "1") == "1")
    market_based_ranking_enabled: bool = field(default_factory=lambda: os.environ.get("MARKET_BASED_RANKING_ENABLED", "1") == "1")
    web_dir: Path = field(default_factory=lambda: REPO_ROOT / "apps" / "web")

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    def effective_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        if self.is_production:
            print("FATAL: DATABASE_URL is required in production.", file=sys.stderr)
            raise SystemExit(1)
        (REPO_ROOT / "data").mkdir(exist_ok=True)
        return f"sqlite:///{REPO_ROOT / 'data' / 'discover-dev.db'}"

    def validate_production(self) -> None:
        if not self.is_production:
            return
        missing = [name for name, value in [
            ("DATABASE_URL", self.database_url),
            ("SESSION_SECRET", os.environ.get("SESSION_SECRET", "")),
        ] if not value]
        if missing:
            print(f"FATAL: missing required production env: {', '.join(missing)}", file=sys.stderr)
            raise SystemExit(1)


settings = Settings()
