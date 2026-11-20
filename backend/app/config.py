from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    # Database (Supabase / Neon / local Postgres connection string)
    database_url: str = "postgresql://postgres:postgres@localhost:5432/pakgovjobs"

    # Gemini
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    gemini_min_interval_seconds: float = 1.0  # raise to ~4.5 on the free tier (15 req/min)

    # Admin
    admin_password: str = "change-me"
    admin_token_secret: str = "change-me-too"
    admin_token_ttl_hours: int = 12

    # API
    cors_origins: str = "http://localhost:3000"

    # Scheduler
    run_scheduler: bool = True
    crawl_interval_hours: int = 6
    crawl_on_startup: bool = False

    # Crawler
    sources_file: Path = BASE_DIR / "sources.json"
    max_concurrent_sources: int = 4
    # Effectively unlimited (the AI is only called for links/pages not seen before). Lower these if you
    # need to cap Gemini spend on the very first run.
    max_new_per_source: int = 100000
    max_candidates_per_page: int = 100000
    max_html_per_run: int = 100000
    render_listings: bool = True          # render every listing page with Playwright before extracting links
    request_timeout_seconds: float = 25.0
    source_time_budget_seconds: int = 4 * 3600
    max_media_bytes: int = 12 * 1024 * 1024  # Gemini inline requests cap at ~20MB after base64
    playwright_timeout_ms: int = 35000
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    # Used automatically when the primary model is unavailable (404 / repeated 5xx / quota).
    gemini_fallback_model: str = "gemini-2.0-flash"
    # When Gemini is missing / invalid / down, extract jobs with the non-AI link+table parser instead.
    fallback_parser: bool = True

    # Lifecycle
    # Ads that never state a deadline are treated as closed this many days after publish_date.
    no_deadline_expire_days: int = 45

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
