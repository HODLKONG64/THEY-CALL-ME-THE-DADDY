from __future__ import annotations

import sys

from .config import get_settings
from .engine import DaddyEngine


def main():
    settings = get_settings()

    if len(sys.argv) < 2:
        print("Usage: run")
        return 1

    engine = DaddyEngine(settings)
    result = engine.run()

    print(result.summary)
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
