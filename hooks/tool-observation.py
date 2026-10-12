#!/usr/bin/env python3
"""Codex native PostToolUse adapter; current payload outcomes remain unknown."""

import json
import os
import sys
from pathlib import Path


def main() -> int:
    helper = Path(
        os.environ.get(
            "HOOK_OBSERVATIONS_SCRIPT",
            str(Path.home() / ".claude/scripts/hook_observations.py"),
        )
    )
    if not helper.is_file():
        print(
            json.dumps({"hook": "failure-observation", "status": "unsupported", "reason": "helper_missing"}),
            file=sys.stderr,
        )
        return 0
    os.execv(sys.executable, [sys.executable, str(helper), "observe", "--runtime", "codex"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
