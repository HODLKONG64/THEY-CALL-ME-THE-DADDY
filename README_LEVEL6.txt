Level 6 agent spawning system
- Built from the Level 5 base.
- Keeps all critical safety locks.
- Adds level-6 agent-spawning decision surfaces to reviewer + improvement_planner.
- Adds bounded starter agents: strategy_agent.py, refactor_agent.py, experiment_agent.py
- Designed to break false-completion by creating the next safe capability instead of waiting for one.
