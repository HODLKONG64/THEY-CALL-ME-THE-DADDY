from __future__ import annotations

import json
import sys

def main(path: str):
    with open(path) as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise Exception("Invalid advice format")

    if "allow_proceed" not in data:
        raise Exception("Missing allow_proceed")

    print("OpenAI upgrade advice accepted.")


if __name__ == "__main__":
    main(sys.argv[1])
