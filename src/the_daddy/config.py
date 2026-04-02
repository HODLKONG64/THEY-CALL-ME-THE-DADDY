from __future__ import annotations

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- OpenAI ---
    openai_api_key: str = ""
    openai_model_light: str = "gpt-5.4-nano"

    # --- Commands ---
    command: str = "pytest -q"
    maintenance_command: str = "pytest -q"

    # --- Repo ---
    target_root: str = "."

    # --- Execution ---
    max_attempts: int = 4
    run_timeout_seconds: int = 1200

    # --- Self Evolution ---
    enable_self_evolution: bool = True
    self_evolution_max_actions: int = 3

    # --- Architecture Lane ---
    enable_architecture_lane: bool = True
    architecture_lane_mode: str = "branch"

    # --- File Safety ---
    allow_extensions: tuple[str, ...] = (
        ".py",
        ".md",
        ".yml",
        ".yaml",
        ".json",
        ".toml",
    )

    # --- R2 ---
    r2_endpoint_url: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = ""
    r2_region: str = "auto"

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()