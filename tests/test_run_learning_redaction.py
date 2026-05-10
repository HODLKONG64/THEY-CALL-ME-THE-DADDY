from __future__ import annotations

import json

from the_daddy.core import request_upgrade_advice as advice_module
from the_daddy.models import CommandResult, RunRecord
from the_daddy.runtime.redaction import sanitize_text
from the_daddy.runtime.run_learning_ledger import build_run_learning_ledger_entry


def test_ledger_text_fields_redact_secret_like_strings():
    rec = RunRecord(run_id="r-secret", command="pytest -q")
    rec.selected_mode = "repair"
    rec.success = False
    rec.summary = "failure with token sk-abcdefghijklmnopQRSTUV1234567890 and GH github_token=ghp_abcdefghijklmnopqrstuvwxyz12345"
    rec.trace = [
        {
            "event": "no_patch_blocker_recorded",
            "reason": "Authorization: Bearer supersecrettokenvalue123456789012345",
        }
    ]
    rec.verification = CommandResult(returncode=0)

    entry = build_run_learning_ledger_entry(
        record=rec,
        upgrade_advice={"target_files": ["src/the_daddy/cli.py"]},
        policy_route="safe",
        proposed_patches=[],
    )

    text_blob = json.dumps(entry.model_dump(mode="json"))
    assert "sk-abcdefghijklmnopQRSTUV1234567890" not in text_blob
    assert "ghp_abcdefghijklmnopqrstuvwxyz12345" not in text_blob
    assert "Authorization: Bearer supersecrettokenvalue123456789012345" not in text_blob
    assert "[REDACTED" in text_blob


def test_learning_summary_payload_is_redacted(tmp_path, monkeypatch):
    monkeypatch.setenv("DADDY_LOCAL_STATE_DIR", "doctor_local")
    monkeypatch.setenv("DADDY_MEMORY_FILE", "sam-memory.json")
    memory_dir = tmp_path / "doctor_local"
    memory_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "3.0",
        "run_learning_ledger": [
            {
                "run_id": "r1",
                "outcome": "blocked_fake_noop",
                "subsystem": "engine",
                "blocked_reason": "OPENAI_API_KEY=sk-test-secret GITHUB_TOKEN=ghp_testsecret password=supersecret",
                "avoid_next_time": ["Authorization: Bearer sk-test-secret"],
            }
        ],
    }
    (memory_dir / "sam-memory.json").write_text(json.dumps(payload), encoding="utf-8")

    summary = advice_module.build_learning_summary(tmp_path)
    raw = json.dumps(summary)
    for fragment in [
        "sk-test-secret",
        "ghp_testsecret",
        "supersecret",
        "Authorization: Bearer sk-test-secret",
        "OPENAI_API_KEY=sk-test-secret",
        "GITHUB_TOKEN=ghp_testsecret",
        "password=supersecret",
    ]:
        assert fragment not in raw
    assert "Authorization: [REDACTED_AUTH_HEADER]" in raw
    assert "OPENAI_API_KEY=[REDACTED_SECRET]" in raw
    assert "GITHUB_TOKEN=[REDACTED_TOKEN]" in raw
    assert "password=[REDACTED_SECRET]" in raw


def test_sanitize_text_redacts_exact_secret_examples():
    text = (
        "Authorization: Bearer sk-test-secret "
        "OPENAI_API_KEY=sk-test-secret "
        "GITHUB_TOKEN=ghp_testsecret "
        "password=supersecret"
    )
    cleaned = sanitize_text(text)
    for fragment in [
        "sk-test-secret",
        "ghp_testsecret",
        "supersecret",
        "Authorization: Bearer sk-test-secret",
        "OPENAI_API_KEY=sk-test-secret",
        "GITHUB_TOKEN=ghp_testsecret",
        "password=supersecret",
    ]:
        assert fragment not in cleaned
    assert "Authorization: [REDACTED_AUTH_HEADER]" in cleaned
    assert "OPENAI_API_KEY=[REDACTED_SECRET]" in cleaned
    assert "GITHUB_TOKEN=[REDACTED_TOKEN]" in cleaned
    assert "password=[REDACTED_SECRET]" in cleaned
