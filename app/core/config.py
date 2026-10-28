from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Jyotish API"
    environment: Literal["development", "staging", "production"] = "development"
    api_v1_prefix: str = "/v1"
    ephe_path: Path = Path("ephe")
    cors_origins: str = "*"

    geocoding_provider: Literal["auto", "google", "nominatim", "photon"] = "auto"
    google_maps_api_key: str | None = None
    geocoding_user_agent: str = "JyotishApp/0.1 (support@example.com)"
    nominatim_base_url: str = "https://nominatim.openstreetmap.org"
    photon_base_url: str = "https://photon.komoot.io"
    http_timeout_seconds: float = 10.0

    # AI reading. Leave the key empty to use the built-in chart-based answers.
    gemini_api_key: str | None = None
    gemini_api_keys: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_fallback_models: str = "gemini-3.1-flash-lite"
    gemini_enable_search: bool = True
    gemini_live_model: str = "gemini-3.8-live"
    gemini_live_fallback_models: str = "gemini-3.1-flash-live-preview"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    ai_timeout_seconds: float = 45.0
    ai_cache_ttl_seconds: int = 43200
    ai_cache_max_entries: int = 500

    # Cost controls. The daily message quota is enforced per install ID.
    ai_free_daily_messages: int = 5
    ai_plus_daily_messages: int = 50
    ai_global_daily_budget: int = 2000
    ai_history_turns: int = 8
    ai_max_output_tokens: int = 400
    # Search grounding is billed per request and dwarfs the token cost, so free
    # installs only ground their first messages of the day. Plus is never capped.
    ai_free_grounded_messages: int = 1

    # Optional second text provider. Groq is OpenAI-compatible and is tried only
    # after every Gemini model/key pair has failed. Leave empty to disable.
    groq_api_key: str | None = None
    groq_api_keys: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_timeout_seconds: float = 30.0
    # Cloud Run has no durable disk and many instances, so it uses Firestore.
    usage_store: Literal["sqlite", "firestore"] = "sqlite"
    ai_usage_db_path: Path = Path("data/ai_usage.db")
    firestore_project: str | None = None
    firestore_database: str = "(default)"
    # Serves GET /v1/events/summary for the owner's usage dashboard. Leave empty
    # to keep the dashboard disabled.
    analytics_token: str | None = None

    # Per-IP burst limits on the compute and AI endpoints. Counted per instance,
    # so they stop runaway clients rather than enforcing an exact quota.
    rate_limit_enabled: bool = True

    # Voice ("AI Panditji talk") uses the Gemini Live models. One turn is one
    # push-to-talk question plus its spoken answer, metered separately from chat.
    live_max_seconds: int = 180
    live_free_daily_turns: int = 4
    live_plus_daily_turns: int = 40
    live_session_token_ttl_seconds: int = 90
    live_voice_name: str = "Charon"

    # Google Play subscription. Leave the service account empty to disable billing.
    google_play_package_name: str = "in.aikundli.app"
    google_play_service_account_json: str | None = None
    plus_product_id: str = "ai_kundli_plus_monthly"
    plus_refresh_hours: int = 12

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def gemini_models(self) -> list[str]:
        models = [self.gemini_model]
        for model in self.gemini_fallback_models.split(","):
            cleaned = model.strip()
            if cleaned and cleaned not in models:
                models.append(cleaned)
        return models

    @property
    def gemini_keys(self) -> list[str]:
        keys: list[str] = []
        if self.gemini_api_key:
            keys.append(self.gemini_api_key.strip())
        for key in self.gemini_api_keys.split(","):
            cleaned = key.strip()
            if cleaned and cleaned not in keys:
                keys.append(cleaned)
        return keys

    @property
    def gemini_live_models(self) -> list[str]:
        models = [self.gemini_live_model]
        for model in self.gemini_live_fallback_models.split(","):
            cleaned = model.strip()
            if cleaned and cleaned not in models:
                models.append(cleaned)
        return models

    @property
    def groq_keys(self) -> list[str]:
        keys: list[str] = []
        if self.groq_api_key:
            keys.append(self.groq_api_key.strip())
        for key in self.groq_api_keys.split(","):
            cleaned = key.strip()
            if cleaned and cleaned not in keys:
                keys.append(cleaned)
        return keys

    @property
    def text_provider_configured(self) -> bool:
        """True when any text provider could answer, not just Gemini."""
        return bool(self.gemini_keys or self.groq_keys)


@lru_cache
def get_settings() -> Settings:
    return Settings()
