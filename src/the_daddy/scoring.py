# PATCH YOUR EXISTING FILE — ADD THIS LOGIC

LOW_VALUE_PATTERNS = [
    "trace",
    "logging",
    "observability",
]

DIVERSITY_TARGETS = [
    "engine",
    "memory",
    "planner",
    "merge",
    "policy",
]


def _value_score_bonus(path: str) -> float:
    score = 0.0

    # 🚨 penalise boring loops
    if any(p in path.lower() for p in LOW_VALUE_PATTERNS):
        score -= 2.5

    # 🚀 reward expansion
    if any(t in path.lower() for t in DIVERSITY_TARGETS):
        score += 3.0

    return score
