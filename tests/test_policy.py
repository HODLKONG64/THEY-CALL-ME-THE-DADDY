from the_daddy.models import PatchAction
from the_daddy.policy import classify_patch_risk


def test_policy_rejects_forbidden_construct():
    result = classify_patch_risk([
        PatchAction(
            path="src/app.py",
            operation="replace_file",
            description="bad",
            new_content="import os\nos.system('rm -rf /')",
        )
    ])
    assert not result.passed
    assert result.route == "reject"


def test_policy_flags_workflow_as_branch():
    result = classify_patch_risk([
        PatchAction(
            path=".github/workflows/test.yml",
            operation="replace_file",
            description="workflow",
            new_content="name: test",
        )
    ])
    assert result.passed
    assert result.route == "branch"
