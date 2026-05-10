from __future__ import annotations

"""Secret redaction contract for persisted diagnostics and prompt context.

Contract:
- Preserve useful diagnostic structure while redacting secret values.
- ``*_TOKEN`` keys keep the key name; values become ``[REDACTED_TOKEN]``.
- ``*_SECRET``, ``*_API_KEY``, and ``password``/``*_PASSWORD`` keys keep the
  key name; values become ``[REDACTED_SECRET]``.
- Authorization bearer headers become ``Authorization: [REDACTED_AUTH_HEADER]``.
- Raw secret values must never survive in persisted traces, ledgers, summaries,
  or prompt context.
"""

import math
import re
from typing import Any

_SIMPLE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"), "[REDACTED_SECRET]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "[REDACTED_TOKEN]"),
    (re.compile(r"(?i)Authorization\s*:\s*Bearer\s+\S+"), "Authorization: [REDACTED_AUTH_HEADER]"),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-+/=]{16,}\b"), "Bearer [REDACTED_TOKEN]"),
]
_KEY_VALUE_PATTERN = re.compile(
    r"(?i)\b([A-Za-z_][A-Za-z0-9_]*?(?:API_KEY|SECRET|TOKEN|PASSWORD))\s*[:=]\s*([^\s,;\"']{1,})"
)
_QUOTED_KEY_VALUE_PATTERN = re.compile(
    r"(?i)(['\"])((?:[A-Za-z_][A-Za-z0-9_]*?(?:API_KEY|SECRET|TOKEN|PASSWORD))|password)\1\s*:\s*(['\"])(.*?)\3"
)


def _shannon_entropy(text: str) -> float:
    if not text:
        return 0.0
    freq: dict[str, int] = {}
    for ch in text:
        freq[ch] = freq.get(ch, 0) + 1
    n = len(text)
    return -sum((count / n) * math.log2(count / n) for count in freq.values())


def _looks_high_entropy_secret(token: str) -> bool:
    candidate = token.strip()
    if len(candidate) < 28:
        return False
    if not re.fullmatch(r"[A-Za-z0-9._\-+/=]+", candidate):
        return False
    return _shannon_entropy(candidate) >= 3.6


def sanitize_text(value: str) -> str:
    out = str(value or "")
    for pattern, replacement in _SIMPLE_PATTERNS:
        out = pattern.sub(replacement, out)

    out = re.sub(r"(?i)\b(OPENAI_API_KEY)\s*[:=]\s*[^\s,;\"']+", r"\1=[REDACTED_SECRET]", out)
    out = re.sub(r"(?i)\b(GITHUB_TOKEN)\s*[:=]\s*[^\s,;\"']+", r"\1=[REDACTED_TOKEN]", out)
    out = re.sub(r"(?i)\b(password)\s*[:=]\s*[^\s,;\"']+", r"\1=[REDACTED_SECRET]", out)

    # Preserve the original key name and redact only the value.
    # TOKEN-like keys are labeled as token redactions; other secret-bearing
    # keys are labeled as secret redactions.
    def _replace_key_value(match: re.Match[str]) -> str:
        key = str(match.group(1) or "")
        key_upper = key.upper()
        if "TOKEN" in key_upper and "PASSWORD" not in key_upper:
            return f"{key}=[REDACTED_TOKEN]"
        return f"{key}=[REDACTED_SECRET]"

    out = _KEY_VALUE_PATTERN.sub(_replace_key_value, out)

    def _replace_quoted_key_value(match: re.Match[str]) -> str:
        key_quote = str(match.group(1) or '"')
        key = str(match.group(2) or "")
        value_quote = str(match.group(3) or '"')
        key_upper = key.upper()
        redacted = "[REDACTED_TOKEN]" if "TOKEN" in key_upper and "PASSWORD" not in key_upper else "[REDACTED_SECRET]"
        return f"{key_quote}{key}{key_quote}: {value_quote}{redacted}{value_quote}"

    out = _QUOTED_KEY_VALUE_PATTERN.sub(_replace_quoted_key_value, out)

    def _entropy_replacer(match: re.Match[str]) -> str:
        token = match.group(0)
        if _looks_high_entropy_secret(token):
            return "[REDACTED_TOKEN]"
        return token

    out = re.sub(r"[A-Za-z0-9._\-+/=]{28,}", _entropy_replacer, out)
    return out


def sanitize_list(values: list[str]) -> list[str]:
    return [sanitize_text(v) for v in values]


def sanitize_mapping(payload: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, str):
            out[key] = sanitize_text(value)
        elif isinstance(value, list):
            cleaned: list[Any] = []
            for item in value:
                if isinstance(item, str):
                    cleaned.append(sanitize_text(item))
                elif isinstance(item, dict):
                    cleaned.append(sanitize_mapping(item))
                else:
                    cleaned.append(item)
            out[key] = cleaned
        elif isinstance(value, dict):
            out[key] = sanitize_mapping(value)
        else:
            out[key] = value
    return out
