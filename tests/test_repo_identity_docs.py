from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_readme_describes_daddy_as_doctor_engine_not_swarmsy_app():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert "Doctor/self-repair engine repo" in readme
    assert "It is **not** the SWARMSY app or product runtime." in readme
    assert "This repo is the app layer." not in readme
    assert "SWARMSY is a test app and open-source build system" not in readme


def test_swarmsy_bridge_doc_replaces_old_app_direction_doc():
    assert not (REPO_ROOT / "docs" / "SWARMSY_APP_DIRECTION.md").exists()

    bridge_doc = (REPO_ROOT / "docs" / "SWARMSY_DOCTOR_BRIDGE.md").read_text(encoding="utf-8")

    assert "SWARMSY is expected to have its own app repo" in bridge_doc
    assert "No automatic SWARMSY writes or merges are allowed unless they are explicitly enabled." in bridge_doc


def test_target_repo_safety_contract_documents_explicit_external_mode():
    contract = (REPO_ROOT / "docs" / "TARGET_REPO_SAFETY_CONTRACT.md").read_text(encoding="utf-8")

    assert "GITHUB_REPO=HODLKONG64/SWARMSY" in contract
    assert "DADDY_ALLOWED_TARGET_REPOS=HODLKONG64/THEY-CALL-ME-THE-DADDY,HODLKONG64/SWARMSY" in contract
    assert "no cross-repo writes unless the target repo is allowlisted" in contract
