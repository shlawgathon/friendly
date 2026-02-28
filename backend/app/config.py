from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── Neo4j ──
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "friendly_dev_password"

    # ── Sponsor API Keys ──
    modulate_api_key: str = ""
    reka_api_key: str = ""
    pioneer_api_key: str = ""
    yutori_api_key: str = ""


    # ── Backend ──
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    webhook_base_url: str = "http://localhost:8000"

    # ── Hard Caps ──
    max_posts_per_ingest: int = 10
    max_posts_hard_limit: int = 25
    top_interests_for_yutori: int = 3
    max_parallel_reka_calls: int = 2

    # ── Retry / Timeouts ──
    api_timeout_seconds: float = 20.0
    max_retries: int = 3
    retry_backoff_multiplier: float = 1.0
    retry_backoff_max: float = 30.0

    # ── Scraper Standalone ──
    scraper_url: str = "http://localhost:8090"
    scraper_api_key: str = ""

    # ── Enrichment Services ──
    browsing_service_url: str = "http://localhost:8001"
    n1_service_url: str = "http://localhost:8002"

    # ── Cooldowns ──
    ingest_cooldown_minutes: int = 5


settings = Settings()
