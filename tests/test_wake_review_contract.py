from the_daddy.models import ArchitectureReview, PatchAction, SelfEvolutionAction


def test_architecture_review_accepts_valid_self_evolution_action() -> None:
    action = SelfEvolutionAction(
        title="Add bounded note",
        description="Small safe patch",
        risk="safe",
        patches=[
            PatchAction(
                path="README.md",
                operation="replace_file",
                new_content="# Updated\n",
                description="Update docs",
            )
        ],
    )

    review = ArchitectureReview(
        diagnosis="Example diagnosis",
        system_intent="Keep the repo stable and patch-capable.",
        self_evolution_actions=[action],
        risk_level="low",
    )

    assert review.diagnosis == "Example diagnosis"
    assert review.system_intent == "Keep the repo stable and patch-capable."
    assert len(review.self_evolution_actions) == 1
    assert review.self_evolution_actions[0].title == "Add bounded note"
    assert review.self_evolution_actions[0].patches[0].path == "README.md"


def test_architecture_review_drops_malformed_self_evolution_action() -> None:
    malformed_action = {
        "title": "Bad patch",
        "description": "Missing required patch payload",
        "risk": "safe",
        "patches": [
            {
                "path": "README.md",
                "operation": "replace_file",
                "description": "Missing new_content",
            }
        ],
    }

    review = ArchitectureReview(
        diagnosis="Example diagnosis",
        system_intent="Keep the repo stable and patch-capable.",
        self_evolution_actions=[malformed_action],
        risk_level="low",
    )

    assert review.self_evolution_actions == []
