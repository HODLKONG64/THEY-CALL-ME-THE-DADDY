"""Local proposal provider. It has no tools, credentials or approval authority."""
from __future__ import annotations

import json
import logging
import time

import httpx

from ..config import Settings

LOGGER = logging.getLogger(__name__)
URL = "http://127.0.0.1:11434/api/chat"


class LocalRepairClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def propose(self, *, system: str, prompt: str, schema: dict) -> dict | None:
        if not self.settings.doctor_local_ai:
            return None
        # Never silently truncate code or evidence to fit the small shared model.
        if len((system + prompt + json.dumps(schema)).encode()) > self.settings.doctor_local_prompt_bytes:
            LOGGER.info("doctor_local_ai skipped: context budget")
            return None
        started = time.monotonic()
        try:
            # Explicit loopback, no proxy, no redirects, no cloud credentials.
            with httpx.Client(trust_env=False, follow_redirects=False,
                              timeout=httpx.Timeout(self.settings.doctor_local_timeout, connect=3)) as client:
                response = client.post(URL, json={
                    "model": self.settings.doctor_local_model,
                    "messages": [{"role": "system", "content": system},
                                 {"role": "user", "content": prompt}],
                    "format": schema, "stream": False, "think": False,
                    "options": {"num_ctx": 4096, "num_predict": 768, "temperature": 0},
                })
                response.raise_for_status()
                data = response.json()
                if data.get("done") is not True or data.get("done_reason") != "stop":
                    raise ValueError("incomplete local output")
                result = json.loads(data["message"]["content"])
                if not isinstance(result, dict):
                    raise ValueError("expected object")
                # Approval is exclusively the existing OpenAI review path.
                if result.get("verdict") != "patch" or not result.get("edits"):
                    LOGGER.info("doctor_local_ai escalated: no patch")
                    return None
                LOGGER.info("doctor_local_ai proposal received in %.1fs", time.monotonic() - started)
                return result
        except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError):
            LOGGER.info("doctor_local_ai escalated: unavailable or invalid response")
            return None
