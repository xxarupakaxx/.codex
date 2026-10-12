#!/usr/bin/env python3
"""Codex native adapter for the shared session handover core."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys


def _core_path() -> Path:
    override = os.environ.get("SESSION_HANDOVER_CORE")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[1] / "scripts" / "session_handover.py"


def main() -> int:
    try:
        path = _core_path()
        if not path.is_file():
            print("session-handover: core_not_found", file=sys.stderr)
            return 0
        spec = importlib.util.spec_from_file_location("session_handover_core", path)
        if spec is None or spec.loader is None:
            print("session-handover: core_unavailable", file=sys.stderr)
            return 0
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        stream = getattr(sys.stdin, "buffer", sys.stdin)
        raw = stream.read(module.MAX_JSON_BYTES + 1)
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        if len(raw) > module.MAX_JSON_BYTES:
            raise ValueError("hook payload is too large")
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("hook payload must be an object")
        event = payload.get("hook_event_name") or payload.get("event")
        stdout, stderr = module.run_hook("codex", event, payload)
        sys.stdout.write(stdout)
        sys.stderr.write(stderr)
    except (json.JSONDecodeError, UnicodeError, ValueError):
        print("session-handover: invalid_hook_json", file=sys.stderr)
    except Exception:
        print("session-handover: internal_error", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
