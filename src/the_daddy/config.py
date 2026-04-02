from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True, extra="ignore")

    # OpenAI
    openai_api_key: str = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    openai_model_main: str = Field(default_factory=lambda: os.getenv("OPENAI_MODEL_MAIN", "gpt-5.4"))
    openai_model_review: str = Field(default_factory=lambda: os.getenv("OPENAI_MODEL_REVIEW", "gpt-5.4"))
    openai_model_vet: str = Field(default_factory=lambda: os.getenv("OPENAI_MODEL_VET", "gpt-5.4-mini"))
    openai_model_light: str = Field(default_factory=lambda: os.getenv("OPENAI_MODEL_LIGHT", "gpt-5.4-nano"))

    # GitHub / PR lane
    github_token: str = Field(default_factory=lambda: os.getenv("GITHUB_TOKEN", ""))
    github_repo: str = Field(default_factory=lambda: os.getenv("GITHUB_REPO", ""))  # owner/repo

    # Runtime
    command: str = Field(default_factory=lambda: os.getenv("DADDY_COMMAND", "pytest -q"))
    maintenance_command: str = Field(default_factory=lambda: os.getenv("DADDY_MAINTENANCE_COMMAND", "pytest -q"))
    target_root: Path = Field(default_factory=lambda: Path(os.getenv("DADDY_TARGET_ROOT", ".")).resolve())
    max_attempts: int = Field(default_factory=lambda: int(os.getenv("DADDY_MAX_ATTEMPTS", "4")))
    run_timeout_seconds: int = Field(default_factory=lambda: int(os.getenv("DADDY_RUN_TIMEOUT_SECONDS", "1200")))
    max_file_bytes: int = Field(default_factory=lambda: int(os.getenv("DADDY_MAX_FILE_BYTES", "120000")))
    allow_extensions: list[str] = Field(
        default_factory=lambda: [".py", ".md", ".txt", ".yml", ".yaml", ".json", ".toml"]
    )

    # Safe self-evolution lane
    enable_self_evolution: bool = Field(
        default_factory=lambda: os.getenv("DADDY_ENABLE_SELF_EVOLUTION", "true").lower() == "true"
    )
    self_evolution_max_actions: int = Field(
        default_factory=lambda: int(os.getenv("DADDY_SELF_EVOLUTION_MAX_ACTIONS", "3"))
    )
    enable_patching: bool = Field(default_factory=lambda: os.getenv("DADDY_ENABLE_PATCHING", "true").lower() == "true")

    # Architecture lane
    enable_architecture_lane: bool = Field(
        default_factory=lambda: os.getenv("DADDY_ENABLE_ARCHITECTURE_LANE", "true").lower() == "true"
    )
    architecture_lane_mode: Literal["branch", "recommend"] = Field(
        default_factory=lambda: os.getenv("DADDY_ARCHITECTURE_LANE_MODE", "branch")
    )
    architecture_max_actions: int = Field(
        default_factory=lambda: int(os.getenv("DADDY_ARCHITECTURE_MAX_ACTIONS", "2"))
    )
    architecture_max_files_per_action: int = Field(
        default_factory=lambda: int(os.getenv("DADDY_ARCHITECTURE_MAX_FILES_PER_ACTION", "5"))
    )
    architecture_allow_apply_on_main: bool = Field(
        default_factory=lambda: os.getenv("DADDY_ARCHITECTURE_ALLOW_APPLY_ON_MAIN", "false").lower() == "true"
    )

    # Memory / local state
    local_state_dir: Path = Field(default_factory=lambda: Path("doctor_local"))
    memory_file_name: str = Field(default_factory=lambda: os.getenv("DADDY_MEMORY_FILE", "sam-memory.json"))

    # R2
    r2_endpoint_url: str = Field(default_factory=lambda: os.getenv("R2_ENDPOINT_URL", ""))
    r2_access_key_id: str = Field(default_factory=lambda: os.getenv("R2_ACCESS_KEY_ID", ""))
    r2_secret_access_key: str = Field(default_factory=lambda: os.getenv("R2_SECRET_ACCESS_KEY", ""))
    r2_bucket: str = Field(default_factory=lambda: os.getenv("R2_BUCKET", ""))
    r2_region: str = Field(default_factory=lambda: os.getenv("R2_REGION", "auto"))

    @property
    def has_openai(self) -> bool:
        return bool(self.openai_api_key.strip())

    @property
    def has_github(self) -> bool:
        return bool(self.github_token.strip() and self.github_repo.strip())

    @property
    def has_r2(self) -> bool:
        return bool(
            self.r2_endpoint_url.strip()
            and self.r2_access_key_id.strip()
            and self.r2_secret_access_key.strip()
            and self.r2_bucket.strip()
        )


def get_settings() -> Settings:
    settings = Settings()
    settings.local_state_dir.mkdir(parents=True, exist_ok=True)
    return settings
