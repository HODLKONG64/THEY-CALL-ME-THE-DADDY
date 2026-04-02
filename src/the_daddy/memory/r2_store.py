from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError

from ..config import Settings


class R2Store:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.bucket = settings.r2_bucket
        self.key = "sam-memory.json"
        self.local_path = settings.local_state_dir / "sam-memory.json"

        self.s3 = boto3.client(
            "s3",
            endpoint_url=settings.r2_endpoint_url,
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            region_name=settings.r2_region,
        )

    def _read_local(self) -> dict[str, Any]:
        try:
            if self.local_path.exists():
                return json.loads(self.local_path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _write_local(self, data: dict[str, Any]) -> None:
        self.local_path.parent.mkdir(parents=True, exist_ok=True)
        self.local_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load(self) -> dict[str, Any]:
        try:
            response = self.s3.get_object(Bucket=self.bucket, Key=self.key)
            body = response["Body"].read().decode("utf-8")
            data = json.loads(body)
            self._write_local(data)
            return data
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                return self._read_local()
            return self._read_local()
        except Exception:
            return self._read_local()

    def save(self, data: dict[str, Any]) -> None:
        self._write_local(data)
        body = json.dumps(data, indent=2)
        self.s3.put_object(
            Bucket=self.bucket,
            Key=self.key,
            Body=body.encode("utf-8"),
            ContentType="application/json",
        )
