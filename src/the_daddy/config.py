from __future__ import annotations

import os
from pathlib import Path
from typing import List

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()


class Settings(BaseModel):
    openai_api_key: str = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    openai_model_main: str = Field(default_factory=lambda: os.getenv("OPENAI_MODEL_MAIN", "gpt-5.4"))
    openai_model_review: str = Field(default_factory=lambda: os.getenv("OPENAI_MODEL_REVIEW", "gpt-5.4"))
    openai_model_vet: str = Field(default_factory=lambda: os.getenv("OPENAI_MODEL_VET", "gpt-5.4-mini"))
    openai_model_light: str = Field(default_factory=lambda: os.getenv("OPENAI_MODEL_LIGHT", "gpt-5.4-nano"))
    openai_timeout_seconds: int = Field(default_factory=lambda: int(os.getenv("OPENAI_TIMEOUT_SECONDS", "90")))

    target_root: Path = Field(default_factory=lambda: Path(os.getenv("DADDY_TARGET_ROOT", ".")).resolve())
    command: str = Field(default_factory=lambda: os.getenv("DADDY_COMMAND", "pytest -q"))
    max_attempts: int = Field(default_factory=lambda: int(os.getenv("DADDY_MAX_ATTEMPTS", "4")))
    max_file_bytes: int = Field(default_factory=lambda: int(os.getenv("DADDY_MAX_FILE_BYTES", "120000")))
    run_timeout_seconds: int = Field(default_factory=lambda: int(os.getenv("DADDY_RUN_TIMEOUT_SECONDS", "1200")))
    heartbeat_seconds: int = Field(default_factory=lambda: int(os.getenv("DADDY_HEARTBEAT_SECONDS", "5")))
    enable_patching: bool = Field(default_factory=lambda: os.getenv("DADDY_ENABLE_PATCHING", "true").lower() == "true")
    enable_test_generation: bool = Field(default_factory=lambda: os.getenv("DADDY_ENABLE_TEST_GENERATION", "true").lower() == "true")
    allow_extensions: List[str] = Field(default_factory=lambda: [
        ext.strip() for ext in os.getenv(
            "DADDY_ALLOW_EXTENSIONS",
            ".py,.js,.ts,.tsx,.jsx,.json,.yml,.yaml,.toml,.md"
        ).split(",") if ext.strip()
    ])

    r2_endpoint_url: str = Field(default_factory=lambda: os.getenv("R2_ENDPOINT_URL", ""))
    r2_access_key_id: str = Field(default_factory=lambda: os.getenv("R2_ACCESS_KEY_ID", ""))
    r2_secret_access_key: str = Field(default_factory=lambda: os.getenv("R2_SECRET_ACCESS_KEY", ""))
    r2_bucket: str = Field(default_factory=lambda: os.getenv("R2_BUCKET", ""))
    r2_region: str = Field(default_factory=lambda: os.getenv("R2_REGION", "auto"))

    telegram_bot_token: str = Field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = Field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))
    telegram_thread_id: str = Field(default_factory=lambda: os.getenv("TELEGRAM_THREAD_ID", ""))

    local_state_dir: Path = Field(default_factory=lambda: Path("doctor_local").resolve())

    @property
    def has_openai(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def has_r2(self) -> bool:
        return all([self.r2_endpoint_url, self.r2_access_key_id, self.r2_secret_access_key, self.r2_bucket])


def get_settings() -> Settings:
    settings = Settings()
    settings.local_state_dir.mkdir(parents=True, exist_ok=True)
    return settings
