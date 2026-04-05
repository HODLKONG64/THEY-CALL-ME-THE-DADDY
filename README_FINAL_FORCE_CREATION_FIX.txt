FULL BUILD FILES WITH FIX

Main fix applied:
- Upgraded the branch that previously injected the default build action when reviewer returned none.
- Under extreme sustained pressure it now forces creation first.

Forced creation order:
1. goal_agent.py
2. self_rewrite_agent.py
3. level-6 agent spawning path

This pack includes full build files under src/the_daddy/agents and src/the_daddy/runtime.
