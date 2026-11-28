import json
from pathlib import Path
import subprocess

import pytest

from the_daddy.agents.codex_repair import propose_codex_edits


@pytest.mark.parametrize("case", ["valid", "other_head", "outside_file", "empty_anchor", "malformed", "timeout"])
def test_cli_requires_an_exact_head_and_existing_scoped_edits(monkeypatch, case):
    head, path = "a" * 40, "src/example.py"
    monkeypatch.setenv("OPENAI_API_KEY", "test-provider-secret")
    monkeypatch.setenv("GITHUB_TOKEN", "test-github-secret")

    def run(command, **kwargs):
        assert kwargs["cwd"] == Path(command[command.index("--output-schema") + 1]).parent
        assert not (kwargs["cwd"] / ".git").exists()
        assert "OPENAI_API_KEY" not in kwargs["env"] and "GITHUB_TOKEN" not in kwargs["env"]
        assert "--ignore-user-config" in command and "read-only" in command and "never" in command
        assert {value for flag, value in zip(command, command[1:]) if flag == "--disable"} >= {"shell_tool", "unified_exec"}
        assert json.loads(kwargs["input"])["head_sha"] == head
        if case == "timeout":
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        output = Path(command[command.index("--output-last-message") + 1])
        edit = {"path": "outside.py" if case == "outside_file" else path,
                "old": "" if case == "empty_anchor" else "0", "new": "1"}
        payload = {"head_sha": "b" * 40 if case == "other_head" else head, "edits": [edit]}
        output.write_text("not JSON" if case == "malformed" else json.dumps(payload))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("the_daddy.agents.codex_repair.subprocess.run", run)
    edits = propose_codex_edits(head, {"files": {path: "0"}})
    assert [item.path for item in edits] == ([path] if case == "valid" else [])
