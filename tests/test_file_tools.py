from pathlib import Path

from the_daddy.models import PatchAction
from the_daddy.runtime.file_tools import apply_patch_action


def test_apply_patch_action_replace_file(tmp_path):
    root = tmp_path
    target = root / "a.py"
    target.write_text("x = 1\n", encoding="utf-8")
    result = apply_patch_action(
        root,
        PatchAction(
            path="a.py",
            operation="replace_file",
            description="replace",
            new_content="x = 2\n",
        ),
        [".py"],
    )
    assert "x = 2" in target.read_text(encoding="utf-8")
    assert result["path"] == "a.py"
