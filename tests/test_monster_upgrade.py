from the_daddy.models import ArchitectureReview, PatchAction, SelfEvolutionAction
from the_daddy.memory.repository import DaddyMemoryState, MEMORY_SCHEMA_VERSION


def test_schema_version_present():
    assert DaddyMemoryState().schema_version == MEMORY_SCHEMA_VERSION


def test_self_evolution_action_shape():
    review = ArchitectureReview(
        diagnosis="ok",
        system_intent="bounded",
        self_evolution_actions=[
            SelfEvolutionAction(
                title="note",
                description="add architecture note",
                risk="safe",
                patches=[PatchAction(path="ARCHITECTURE.md", operation="replace_file", new_content="x", description="test")],
            )
        ],
    )
    assert review.self_evolution_actions[0].risk == "safe"
