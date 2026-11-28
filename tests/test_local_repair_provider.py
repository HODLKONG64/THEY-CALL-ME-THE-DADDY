import json

import httpx
import pytest

from the_daddy.agents.local_repair import LocalRepairClient, URL
from the_daddy.config import Settings


@pytest.mark.parametrize("case", ["valid", "disabled", "oversized", "timeout", "bad_json",
                                  "approval", "truncated", "redirect"])
def test_local_provider_transport(monkeypatch, case):
    calls = []
    settings = Settings(doctor_local_ai=case != "disabled", doctor_local_prompt_bytes=1000)
    patch = {"verdict": "patch", "edits": [{"path": "src/a.py", "old": "1", "new": "2"}]}
    class Client:
        def __init__(self, **kwargs):
            assert kwargs["trust_env"] is False
            assert kwargs["follow_redirects"] is False
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def post(self, url, *, json):
            assert url == URL
            assert json["model"] == settings.doctor_local_model
            assert json["options"]["num_ctx"] == 4096
            assert json["stream"] is False
            calls.append(url)
            request = httpx.Request("POST", url)
            if case == "timeout":
                raise httpx.ReadTimeout("unavailable")
            if case == "redirect":
                return httpx.Response(302, request=request, headers={"Location": "https://example.com"})
            import json as codec
            output = "bad json" if case == "bad_json" else codec.dumps(
                {"verdict": "approved", "edits": []} if case == "approval" else patch)
            return httpx.Response(200, request=request, json={
                "done": True, "done_reason": "length" if case == "truncated" else "stop",
                "message": {"content": output}})
    monkeypatch.setattr("the_daddy.agents.local_repair.httpx.Client", Client)
    result = LocalRepairClient(settings).propose(system="system", prompt="x"*2000 if case == "oversized" else "fix",
                                                  schema={"type": "object"})
    assert result == (patch if case == "valid" else None)
    assert len(calls) == (0 if case in ("disabled", "oversized") else 1)
