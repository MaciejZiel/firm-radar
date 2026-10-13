"""Application settings, read from environment variables (prefix ``FIRM_RADAR_``)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FIRM_RADAR_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://firm_radar:firm_radar@localhost:55433/firm_radar"
    sql_echo: bool = False
    # Every pooled connection is a PostgreSQL backend process; small hosts want fewer.
    db_pool_size: int = Field(default=5, ge=1)
    db_max_overflow: int = Field(default=10, ge=0)

    # Upstream endpoints (official, public, no credentials).
    krs_base_url: str = "https://api-krs.ms.gov.pl/api/krs"
    whitelist_base_url: str = "https://wl-api.mf.gov.pl/api"
    bzp_base_url: str = "https://ezamowienia.gov.pl/mo-board/api/v1"

    http_timeout_s: float = 20.0
    http_retries: int = 3
    http_backoff_s: float = 0.5
    user_agent: str = "firm-radar/0.1 (+https://github.com/MaciejZiel/firm-radar)"

    # Cache TTLs in seconds.
    krs_cache_ttl_s: int = 12 * 3600
    whitelist_cache_ttl_s: int = 24 * 3600
    bzp_cache_ttl_s: int = 24 * 3600

    # The white list allows 100 "search" queries per day per client; stay below it.
    whitelist_daily_budget: int = Field(default=80, ge=0)

    # Background jobs.
    scheduler_enabled: bool = True
    refresh_interval_s: int = 6 * 3600
    snapshot_max_age_s: int = 24 * 3600
    refresh_batch_size: int = 20
    bzp_ingest_days: int = 3

    # Public read-only demo: seeded fictional data, no upstream calls, no background jobs.
    demo_mode: bool = False
    demo_rate_limit_per_minute: int = Field(default=60, ge=0)

    @field_validator("database_url")
    @classmethod
    def _force_asyncpg(cls, value: str) -> str:
        # Render and most PaaS hand out ``postgres://`` / ``postgresql://`` URLs.
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix):
                return "postgresql+asyncpg://" + value[len(prefix) :]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
