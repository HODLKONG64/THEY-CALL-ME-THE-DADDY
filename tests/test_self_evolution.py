from the_daddy.agents.improvement_planner import ImprovementPlanner
from the_daddy.models import ArchitectureReview, SelfEvolutionAction


def test_self_evolution_capping():
    planner = ImprovementPlanner()

    review = ArchitectureReview(
        diagnosis="x",
        system_intent="x",
        self_evolution_actions=[
            SelfEvolutionAction(title="a", description="b", risk="safe", patches=[]),
            SelfEvolutionAction(title="c", description="d", risk="safe", patches=[]),
        ],
    )

    result = planner.plan_self_evolution(review, True, 1)
    assert len(result.actions) <= 1
