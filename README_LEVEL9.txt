Level 9 multi-path evolution package
- Built from the full build files with fix base.
- Keeps safety locks and forced-creation fallback upgrade.
- Adds multi_path_agent.py.
- Upgrades reviewer + planner so the system can create a new capability OR extend an existing one when all spawn targets already exist.
- This is meant to break the 'no remaining spawn targets' deadlock.
