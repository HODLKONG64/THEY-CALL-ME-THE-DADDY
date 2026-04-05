from __future__ import annotations

import os
import json

def validate_upgrade_gate_for_settings(settings):
    path = os.environ.get("DADDY_UPGRADE_ADVICE_PATH")

    if not path:
        raise Exception("Upgrade gate blocked execution")

    with open(path) as f:
        advice = json.load(f)

    return advice
