from __future__ import annotations

from .core.upgrade_gate import validate_upgrade_gate_for_settings

class DaddyEngine:
    def __init__(self, settings):
        self.settings = settings
        self.upgrade_advice = None
        self.repair_mode_active = False

    def _enforce_upgrade_gate(self):
        advice = validate_upgrade_gate_for_settings(self.settings)
        self.upgrade_advice = advice

        if advice.get("allow_proceed", False):
            self.repair_mode_active = False
            return

        if advice.get("problem_type") == "healthy_safe_loop":
            self.repair_mode_active = True
            return

        raise Exception("Upgrade gate blocked execution")

    def run(self):
        self._enforce_upgrade_gate()

        record = type("Record", (), {})()
        record.run_id = "upgrade-run"
        record.command = "pytest -q"
        record.selected_mode = "build"
        record.success = False
        record.summary = "Repair mode pending required upgrade"
        record.patches_applied = []
        record.rollback_manifest = []
        record.trace = [{"event": "repair_mode_completion_blocked"}]
        record.backlog_updates = []
        record.repo_fingerprint = {}
        record.verification = "ok"
        return record
