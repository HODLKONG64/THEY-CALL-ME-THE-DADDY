from __future__ import annotations

import math
import re
from typing import Any

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"), "[REDACTED_SECRET]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "[REDACTED_TOKEN]"),
    (re.compile(r"(?i)Authorization\s*:\s*Bearer\s+\S+"), "Authorization: [REDACTED_AUTH_HEADER]"),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-+/=]{16,}\b"), "Bearer [REDACTED_TOKEN]"),
    (re.compile(r"(?im)^\s*Authorization\s*:\s*.+$"), "Authorization: [REDACTED_AUTH_HEADER]"),
    (re.compile(r"(?i)\bOPENAI_API_KEY\s*[:=]\s*[^\s,;\"']+"), "[REDACTED_SECRET]"),
    (re.compile(r"(?i)\bGITHUB_TOKEN\s*[:=]\s*[^\s,;\"']+"), "[REDACTED_TOKEN]"),
    (re.compile(r"(?i)\bpassword\s*[:=]\s*[^\s,;\"']+"), "[REDACTED_SECRET]"),
    (
        re.compile(r"(?i)\b([A-Z0-9_]*(?:API_KEY|SECRET|TOKEN|PASSWORD)[A-Z0-9_]*)\s*[:=]\s*([^\s,;\"']{4,})"),
        "[REDACTED_SECRET]",
    ),
    (
        re.compile(r"(?im)^\s*([A-Za-z_][A-Za-z0-9_]*(?:API_KEY|SECRET|TOKEN|PASSWORD))\s*=\s*(.+)$"),
        "[REDACTED_SECRET]",
    ),
]


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
    for pattern, replacement in _PATTERNS:
        out = pattern.sub(replacement, out)

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
