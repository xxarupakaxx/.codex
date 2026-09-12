#!/usr/bin/env python3
"""Check task-local decision evidence without writing or approving anything."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Sequence

sys.dont_write_bytecode = True

from decision_evidence import ID_RE, MAX_BYTES, evaluate_decision_evidence
from roadmap_plan_contract import PlanContractError, resolve_plan_source


def _task_inputs(task_value: str) -> tuple[Path, list[str], str]:
    if "\x00" in task_value:
        raise ValueError("NUL is not allowed in task path")
    task_input = Path(task_value).expanduser()
    if task_input.is_symlink() or not task_input.is_dir():
        raise ValueError("task path must be an existing non-symlink directory")
    task = task_input.resolve(strict=True)
    model = resolve_plan_source(task)
    if model.get("diagnostics"):
        raise ValueError("plan has structural diagnostics")
    tasks = model.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("plan has no tasks")
    acceptance = [item for entry in tasks if isinstance(entry, dict) for item in entry.get("acceptanceIds", [])]
    if not acceptance or any(not isinstance(item, str) or not ID_RE.fullmatch(item) for item in acceptance) or len(acceptance) != len(set(acceptance)):
        raise ValueError("plan acceptance IDs are missing, invalid, or duplicated")
    request_path = task / "00_request.md"
    if request_path.is_symlink() or not request_path.is_file() or request_path.stat().st_size > MAX_BYTES:
        raise ValueError("00_request.md is missing, unsafe, or oversized")
    raw = request_path.read_bytes()
    if not raw or len(raw) > MAX_BYTES or b"\x00" in raw:
        raise ValueError("00_request.md is empty, oversized, or contains NUL")
    try:
        if not raw.decode("utf-8").strip():
            raise ValueError("00_request.md is empty")
    except UnicodeDecodeError as exc:
        raise ValueError("00_request.md is not UTF-8") from exc
    return task, acceptance, hashlib.sha256(raw).hexdigest()


def _template(acceptance: list[str], request_sha256: str) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "requestSha256": request_sha256,
        "claims": [{
            "id": "H1", "statement": "TODO", "why": "TODO", "acceptanceIds": acceptance,
            "critical": True, "status": "unknown", "evidenceIds": [], "falsification": "TODO",
            "counterevidence": {"status": "not-checked", "evidenceIds": [], "rationale": "TODO"},
        }],
        "evidence": [],
        "market": {"applicability": "not-applicable", "rationale": "TODO", "claimIds": [], "alternatives": []},
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", help="existing task directory containing the plan and request")
    parser.add_argument("--template", action="store_true", help="print an incomplete record for the user to fill")
    args = parser.parse_args(argv)
    try:
        task, acceptance, request_sha256 = _task_inputs(args.task)
        result = _template(acceptance, request_sha256) if args.template else evaluate_decision_evidence(task, acceptance, request_sha256)
    except (OSError, RuntimeError, TypeError, ValueError, PlanContractError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if args.template or result["readyForReview"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
