#!/usr/bin/env python3
"""Validate max-load evidence for durable workflows and batch processing."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


TERMINAL_STATES = ("completed", "failed", "canceled", "terminated")


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_evidence(value: object) -> list[str]:
    if not isinstance(value, dict):
        return ["evidence root must be an object"]

    errors: list[str] = []
    if value.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if not _positive_int(value.get("max_cardinality")):
        errors.append("max_cardinality must be a positive integer")

    boundaries = value.get("boundaries")
    if not isinstance(boundaries, list) or not boundaries:
        errors.append("boundaries must be a non-empty array")
    else:
        for index, boundary in enumerate(boundaries):
            prefix = f"boundaries[{index}]"
            if not isinstance(boundary, dict):
                errors.append(f"{prefix} must be an object")
                continue
            for key in ("name", "source"):
                if not _nonempty_string(boundary.get(key)):
                    errors.append(f"{prefix}.{key} must be a non-empty string")
            serialized = boundary.get("serialized_bytes")
            limit = boundary.get("limit_bytes")
            if not _positive_int(serialized):
                errors.append(f"{prefix}.serialized_bytes must be a positive integer")
            if not _positive_int(limit):
                errors.append(f"{prefix}.limit_bytes must be a positive integer")
            if _positive_int(serialized) and _positive_int(limit) and serialized >= limit:
                errors.append(
                    f"{prefix} exceeds limit: serialized_bytes={serialized}, limit_bytes={limit}"
                )

    history = value.get("history")
    if not isinstance(history, dict):
        errors.append("history must be an object")
    else:
        maximum = history.get("max_events")
        limit = history.get("limit_events")
        if not _positive_int(maximum):
            errors.append("history.max_events must be a positive integer")
        if not _positive_int(limit):
            errors.append("history.limit_events must be a positive integer")
        if _positive_int(maximum) and _positive_int(limit) and maximum >= limit:
            errors.append(
                f"history exceeds limit: max_events={maximum}, limit_events={limit}"
            )
        if not _nonempty_string(history.get("source")):
            errors.append("history.source must be a non-empty string")

    rate_limits = value.get("rate_limits")
    if not isinstance(rate_limits, list):
        errors.append("rate_limits must be an array")
    else:
        for index, rate_limit in enumerate(rate_limits):
            prefix = f"rate_limits[{index}]"
            if not isinstance(rate_limit, dict):
                errors.append(f"{prefix} must be an object")
                continue
            for key in (
                "name",
                "rate_limit_scope",
                "max_requests",
                "request_interval_ms",
                "retry_policy",
                "source",
            ):
                field = rate_limit.get(key)
                valid = (
                    _positive_int(field)
                    if key in {"max_requests", "request_interval_ms"}
                    else _nonempty_string(field)
                )
                if not valid:
                    expected = (
                        "a positive integer"
                        if key in {"max_requests", "request_interval_ms"}
                        else "a non-empty string"
                    )
                    errors.append(f"{prefix}.{key} must be {expected}")

    terminal_states = value.get("terminal_states")
    if not isinstance(terminal_states, dict):
        errors.append("terminal_states must be an object")
    else:
        for state in TERMINAL_STATES:
            if not _nonempty_string(terminal_states.get(state)):
                errors.append(
                    f"terminal_states.{state} must reference convergence evidence"
                )

    polling = value.get("polling")
    if not isinstance(polling, dict) or not isinstance(polling.get("applicable"), bool):
        errors.append("polling.applicable must be a boolean")
    elif polling["applicable"]:
        stop_states = polling.get("stop_states")
        if not isinstance(stop_states, list):
            errors.append("polling.stop_states must be an array")
        else:
            missing = [state for state in TERMINAL_STATES if state not in stop_states]
            if missing:
                errors.append(
                    "polling.stop_states missing terminal states: " + ", ".join(missing)
                )
        if not _nonempty_string(polling.get("source")):
            errors.append("polling.source must be a non-empty string")
    elif not _nonempty_string(polling.get("reason")):
        errors.append("polling.reason must explain why polling is not applicable")

    replay = value.get("replay")
    if not isinstance(replay, dict):
        errors.append("replay must be an object")
    else:
        if replay.get("status") != "pass":
            errors.append("replay.status must be pass")
        for key in ("command", "source"):
            if not _nonempty_string(replay.get(key)):
                errors.append(f"replay.{key} must be a non-empty string")

    return errors


def load_evidence(path: Path) -> tuple[object | None, list[str]]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), []
    except (OSError, json.JSONDecodeError) as error:
        return None, [f"{path}: invalid JSON: {error}"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()

    value, errors = load_evidence(args.evidence)
    if value is not None:
        errors.extend(validate_evidence(value))
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print("PASS: durable workflow evidence is valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
