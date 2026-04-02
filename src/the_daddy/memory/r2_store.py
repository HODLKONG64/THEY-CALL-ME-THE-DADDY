from __future__ import annotations

import json
from typing import Any

import boto3
from botocore.exceptions import ClientError

from ..config import Settings


class R2Store:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

        self.s3 = boto3.client(
            "s3",
            endpoint_url=settings.r2_endpoint_url,
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            region_name=settings.r2_region,
        )

        self.bucket = settings.r2_bucket
        self.key = "sam-memory.json"

    def load(self) -> dict[str, Any]:
        try:
            response = self.s3.get_object(Bucket=self.bucket, Key=self.key)
            body = response["Body"].read().decode("utf-8")
            return json.loads(body)
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                return {}
            raise
        except Exception:
            return {}

    def save(self, data: dict[str, Any]) -> None:
        body = json.dumps(data, indent=2)

        self.s3.put_object(
            Bucket=self.bucket,
            Key=self.key,
            Body=body.encode("utf-8"),
            ContentType="application/json",
        )
