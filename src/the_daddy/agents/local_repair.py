"""Local proposal provider. It has no tools, credentials or approval authority."""
from __future__ import annotations

import json
import logging
import time

import httpx

from ..config import Settings

LOGGER = logging.getLogger(__name__)
URL = "http://127.0.0.1:11434/api/chat"
CONTEXT_TOKENS = 4096
OUTPUT_TOKENS = 768
TEMPLATE_RESERVE = 512
SUPPORTED_MODEL = "qwen3:4b-instruct"


class LocalRepairClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def propose(self, *, system: str, prompt: str, schema: dict) -> dict | None:
        if not self.settings.doctor_local_ai:
            return None
        # Qwen3 uses byte-level BPE: conservatively count every UTF-8 byte
        # as one token, including the schema, and reserve chat-template and
        # generation space. Unknown model templates/tokenizers are not trusted.
        if self.settings.doctor_local_model != SUPPORTED_MODEL:
            LOGGER.info("doctor_local_ai skipped: unsupported context accounting")
            return None
        input_bound = sum(len(value.encode("utf-8")) for value in (system, prompt, json.dumps(schema, ensure_ascii=True)))
        safe_budget = min(self.settings.doctor_local_prompt_bytes,
                          CONTEXT_TOKENS - OUTPUT_TOKENS - TEMPLATE_RESERVE)
        if input_bound > safe_budget:
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
                    "options": {"num_ctx": CONTEXT_TOKENS, "num_predict": OUTPUT_TOKENS, "temperature": 0},
                })
                response.raise_for_status()
                data = response.json()
                if data.get("done") is not True or data.get("done_reason") != "stop":
                    raise ValueError("incomplete local output")
                result = json.loads(data["message"]["content"])
                if not isinstance(result, dict):
                    raise ValueError("expected object")
                # The local provider never grants approval.
                if result.get("verdict") != "patch" or not result.get("edits"):
                    LOGGER.info("doctor_local_ai escalated: no patch")
                    return None
                LOGGER.info("doctor_local_ai proposal received in %.1fs", time.monotonic() - started)
                return result
        except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError):
            LOGGER.info("doctor_local_ai escalated: unavailable or invalid response")
            return None
