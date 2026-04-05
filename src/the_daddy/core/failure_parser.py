from __future__ import annotations

import re
from typing import Any


TRACEBACK_FILE_RE = re.compile(r'File "([^"]+)", line (\d+), in ([A-Za-z_][A-Za-z0-9_]*)')
FAILED_NODE_RE = re.compile(r'FAILED\s+([^\s]+)')
ERROR_TYPE_RE = re.compile(r'([A-Za-z_][A-Za-z0-9_]*Error|AssertionError|Exception):\s*(.*)')


def _normalize_repo_path(path: str) -> str:
    text = str(path or "").replace("\\", "/").strip()
    marker = "/src/the_daddy/"
    if marker in text:
        return "src/the_daddy/" + text.split(marker, 1)[1]
    marker_tests = "/tests/"
    if marker_tests in text:
        return "tests/" + text.split(marker_tests, 1)[1]
    if text.startswith("src/the_daddy/") or text.startswith("tests/"):
        return text
    return text


def parse_pytest_failure(output: str) -> dict[str, Any]:
    text = str(output or "")
    failed_node = ""
    file_path = ""
    line_number = 0
    function_name = ""
    error_type = ""
    error_message = ""

    node_match = FAILED_NODE_RE.search(text)
    if node_match:
        failed_node = node_match.group(1).strip()

    traceback_match = None
    for match in TRACEBACK_FILE_RE.finditer(text):
        path = _normalize_repo_path(match.group(1))
        if path.startswith("src/the_daddy/"):
            traceback_match = match

    if traceback_match:
        file_path = _normalize_repo_path(traceback_match.group(1))
        line_number = int(traceback_match.group(2))
        function_name = traceback_match.group(3).strip()

    error_match = None
    for match in ERROR_TYPE_RE.finditer(text):
        error_match = match
    if error_match:
        error_type = error_match.group(1).strip()
        error_message = error_match.group(2).strip()

    candidate_paths: list[str] = []
    if file_path:
        candidate_paths.append(file_path)
    if failed_node.startswith("tests/"):
        test_path = failed_node.split("::", 1)[0]
        if test_path not in candidate_paths:
            candidate_paths.append(test_path)

    return {
        "failed_node": failed_node,
        "file_path": file_path,
        "line_number": line_number,
        "function_name": function_name,
        "error_type": error_type,
        "error_message": error_message,
        "candidate_paths": candidate_paths,
        "has_signal": bool(failed_node or file_path or error_type),
    }


def summarize_failure_signal(run_payload: dict[str, Any]) -> dict[str, Any]:
    verification = run_payload.get("verification", {}) or {}
    combined = str(verification.get("combined", "") or verification.get("stderr", "") or verification.get("stdout", ""))
    parsed = parse_pytest_failure(combined)
    parsed["run_id"] = str(run_payload.get("run_id", "")).strip()
    parsed["success"] = bool(run_payload.get("success", False))
    return parsed
