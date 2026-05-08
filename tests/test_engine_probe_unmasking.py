from __future__ import annotations

from the_daddy.engine import CLI_PROBE_TARGET, DaddyEngine, make_run_id
from the_daddy.models import PatchAction


def _make_settings_with_root(tmp_path):
    from the_daddy.config import Settings

    s = Settings()
    s.target_root = tmp_path
    s.github_repo = ""
    s.github_token = ""
    return s


def _create_cli_under_root(tmp_path):
    """Create a real cli.py under the tmp target_root so the probe's existence check passes."""
    cli_path = tmp_path / "src" / "the_daddy" / "cli.py"
    cli_path.parent.mkdir(parents=True, exist_ok=True)
    cli_path.write_text("# cli\n", encoding="utf-8")
    return cli_path


def test_masked_advice_target_generates_real_patch_path(tmp_path):
    """Masked advice target src/the_***/cli.py must generate patch path src/the_daddy/cli.py."""
    _create_cli_under_root(tmp_path)

    settings = _make_settings_with_root(tmp_path)
    engine = DaddyEngine(settings)
    engine.upgrade_advice = {"target_files": ["src/the_***/cli.py"], "repair_mode": True}
    run_id = make_run_id()

    patches = engine._build_minimal_execution_probe_patch(run_id)

    assert len(patches) == 1
    p = patches[0]
    assert isinstance(p, PatchAction)
    assert p.path == CLI_PROBE_TARGET


def test_generated_patch_path_never_contains_masked_segment(tmp_path):
    """Generated patch path must never contain the string 'the_***'."""
    _create_cli_under_root(tmp_path)

    settings = _make_settings_with_root(tmp_path)
    engine = DaddyEngine(settings)
    engine.upgrade_advice = {"target_files": ["src/the_***/cli.py"], "repair_mode": True}
    run_id = make_run_id()

    patches = engine._build_minimal_execution_probe_patch(run_id)

    for patch in patches:
        assert "the_***" not in (patch.path or "")


def test_engine_only_target_returns_empty(tmp_path):
    """Engine-only target (engine.py, not cli.py) still returns []."""
    settings = _make_settings_with_root(tmp_path)
    engine = DaddyEngine(settings)
    engine.upgrade_advice = {"target_files": ["src/the_daddy/engine.py"], "repair_mode": True}
    run_id = make_run_id()

    patches = engine._build_minimal_execution_probe_patch(run_id)

    assert patches == []
