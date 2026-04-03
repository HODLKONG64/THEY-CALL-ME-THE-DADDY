from __future__ import annotations

import json
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from ..config import Settings


class R2Store:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.bucket = settings.r2_bucket
        self.key = settings.memory_file_name
        self.local_path = settings.local_state_dir / self.key
        self.enabled = settings.has_r2

        self.client = None
        if self.enabled:
            self.client = boto3.client(
                "s3",
                endpoint_url=settings.r2_endpoint_url,
                aws_access_key_id=settings.r2_access_key_id,
                aws_secret_access_key=settings.r2_secret_access_key,
                region_name=settings.r2_region,
            )

    def _read_local(self) -> dict[str, Any]:
        try:
            if self.local_path.exists():
                data = json.loads(self.local_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
        return {}

    def _write_local(self, data: dict[str, Any]) -> None:
        self.local_path.parent.mkdir(parents=True, exist_ok=True)
        self.local_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def load(self) -> dict[str, Any]:
        if not self.enabled or self.client is None:
            return self._read_local()

        try:
            response = self.client.get_object(Bucket=self.bucket, Key=self.key)
            raw = response["Body"].read().decode("utf-8")
            data = json.loads(raw)
            if isinstance(data, dict):
                self._write_local(data)
                return data
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in {"NoSuchKey", "404", "NoSuchBucket"}:
                return self._read_local()

            # keep an error breadcrumb locally instead of failing blind
            try:
                fallback = {
                    "_r2_error": {
                        "stage": "load",
                        "code": code,
                        "message": str(exc),
                    }
                }
                error_path = self.local_path.with_name("r2-load-error.json")
                error_path.write_text(json.dumps(fallback, indent=2), encoding="utf-8")
            except Exception:
                pass
            return self._read_local()
        except (BotoCoreError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            try:
                fallback = {
                    "_r2_error": {
                        "stage": "load",
                        "code": type(exc).__name__,
                        "message": str(exc),
                    }
                }
                error_path = self.local_path.with_name("r2-load-error.json")
                error_path.write_text(json.dumps(fallback, indent=2), encoding="utf-8")
            except Exception:
                pass
            return self._read_local()
        except Exception as exc:
            try:
                fallback = {
                    "_r2_error": {
                        "stage": "load",
                        "code": type(exc).__name__,
                        "message": str(exc),
                    }
                }
                error_path = self.local_path.with_name("r2-load-error.json")
                error_path.write_text(json.dumps(fallback, indent=2), encoding="utf-8")
            except Exception:
                pass
            return self._read_local()

        return self._read_local()

    def save(self, data: dict[str, Any]) -> None:
        if not isinstance(data, dict):
            raise TypeError("R2Store.save expects a dict")

        # always keep local copy first
        self._write_local(data)

        if not self.enabled or self.client is None:
            return

        body = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=self.key,
                Body=body,
                ContentType="application/json",
            )
        except Exception as exc:
            # do not fail the run, but leave a local breadcrumb so failure is visible
            try:
                fallback = {
                    "_r2_error": {
                        "stage": "save",
                        "code": type(exc).__name__,
                        "message": str(exc),
                        "bucket": self.bucket,
                        "key": self.key,
                    }
                }
                error_path = self.local_path.with_name("r2-save-error.json")
                error_path.write_text(json.dumps(fallback, indent=2), encoding="utf-8")
            except Exception:
                pass
            return
