from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import boto3

from ..config import Settings


class R2Store:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.prefix = "the-daddy"
        self.local_fallback_dir = settings.local_state_dir / "r2_fallback"
        self.local_fallback_dir.mkdir(parents=True, exist_ok=True)

    def _client(self):
        return boto3.client(
            "s3",
            endpoint_url=self.settings.r2_endpoint_url,
            aws_access_key_id=self.settings.r2_access_key_id,
            aws_secret_access_key=self.settings.r2_secret_access_key,
            region_name=self.settings.r2_region,
        )

    def _local_path(self, key: str) -> Path:
        return self.local_fallback_dir / key.replace("/", "__")

    def load_json(self, key: str) -> Optional[dict]:
        if self.settings.has_r2:
            try:
                obj = self._client().get_object(Bucket=self.settings.r2_bucket, Key=key)
                return json.loads(obj["Body"].read().decode("utf-8"))
            except Exception:
                pass
        path = self._local_path(key)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return None

    def save_json(self, key: str, payload: dict) -> None:
        data = json.dumps(payload, indent=2, ensure_ascii=False)
        if self.settings.has_r2:
            try:
                self._client().put_object(
                    Bucket=self.settings.r2_bucket,
                    Key=key,
                    Body=data.encode("utf-8"),
                    ContentType="application/json",
                )
            except Exception:
                pass
        self._local_path(key).write_text(data, encoding="utf-8")
