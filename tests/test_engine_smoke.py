from the_daddy.config import Settings
from the_daddy.engine import DaddyEngine


def test_engine_runs(tmp_path):
    settings = Settings(
        target_root=tmp_path,
        openai_api_key="",
        github_token="",
        github_repo="",
        enable_self_evolution=False,
        enable_architecture_lane=False,
        command='python -c "print(\'ok\')"',
    )
    engine = DaddyEngine(settings)
    result = engine.run()

    assert result is not None
    assert result.success is True
    assert result.verification is not None
    assert result.verification.returncode == 0

    trace = getattr(result, "trace", []) or []
    assert any(
        event.get("event") == "pr_skipped" and event.get("reason") in {"no_patches_applied", "github_not_configured", "target_root_not_git_repo"}
        for event in trace
    )
