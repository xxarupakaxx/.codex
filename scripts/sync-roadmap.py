#!/usr/bin/env python3
"""Synchronize a task Roadmap from its recorded workflow route."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


try:
    from roadmap_plan_contract import PlanContractError, parse_plan_contract, parse_plan_files
except ModuleNotFoundError:
    _PLAN_CONTRACT_PATH = Path(__file__).with_name("roadmap_plan_contract.py")
    _PLAN_CONTRACT_SPEC = importlib.util.spec_from_file_location(
        "roadmap_plan_contract", _PLAN_CONTRACT_PATH
    )
    if _PLAN_CONTRACT_SPEC is None or _PLAN_CONTRACT_SPEC.loader is None:
        raise
    _PLAN_CONTRACT_MODULE = importlib.util.module_from_spec(_PLAN_CONTRACT_SPEC)
    _PLAN_CONTRACT_SPEC.loader.exec_module(_PLAN_CONTRACT_MODULE)
    PlanContractError = _PLAN_CONTRACT_MODULE.PlanContractError
    parse_plan_contract = _PLAN_CONTRACT_MODULE.parse_plan_contract
    parse_plan_files = _PLAN_CONTRACT_MODULE.parse_plan_files


ELIGIBLE_ROUTES = {"explicit-roadmap", "roadmap"}
ROUTE_PATTERN = re.compile(
    r"roadmap_route:\s*(explicit-roadmap|roadmap|log-only)(?=[：:\s`]|$)"
)
UI_CHANGE_MARKER_PATTERN = re.compile(
    r"(?mi)^\s*(?:[-*]\s*)?UI変更\s*[:：]\s*(?:yes|true|あり|対象)\s*$"
)
UI_PREVIEW_BLOCK_PATTERN = re.compile(
    r"```[ \t]*ui-preview-json[ \t]*\r?\n([\s\S]*?)\r?\n```",
    re.IGNORECASE,
)
EMBEDDED_SNAPSHOT_PATTERN = re.compile(
    r'<script\b(?=[^>]*\bid=["\']embedded-snapshot["\'])[^>]*>'
    r'(.*?)</script\s*>',
    re.IGNORECASE | re.DOTALL,
)
PHASE_STATES = {
    "2": "active",
    "3": "active",
    "4": "verifying",
    "5": "completed",
}
DELEGATION_DECISION_FIELDS = (
    "decision", "role", "gate", "decision_unit",
    "passed_conditions", "failed_conditions", "local_first_evidence", "reason",
    "write_scope", "acceptance", "supersedes", "lead_retains",
)
DELEGATION_DECISION_ENUMS = {
    "decision": {"worker", "lead", "N/A (read-only)"},
    "role": {"worker", "implementer", "N/A"},
    "gate": {"PASS", "FAIL", "N/A"},
}
DELEGATION_DECISION_PATTERN = re.compile(r"(?ms)^## .+ - Delegation Decision[^\n]*\n(.*?)(?=^## |\Z)")
DECISION_FIELD_PATTERN = re.compile(r"^\s*-\s*([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$")


def valid_task_dir(path: Path, memory_root: Path) -> bool:
    try:
        relative = path.resolve().relative_to(memory_root.resolve())
    except ValueError:
        return False
    return bool(relative.parts) and relative.parts[0] not in {".", ".."}


def validate_task_metadata(task_dir: Path, workspace_root: Path) -> str | None:
    metadata_path = task_dir / "task-meta.json"
    if not metadata_path.is_file():
        return None
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "task_metadata_invalid"
    expected = str(workspace_root.resolve())
    for field in ("project_path", "worktree_path"):
        value = metadata.get(field)
        if value is not None and str(Path(str(value)).resolve()) != expected:
            return f"task_metadata_{field}_mismatch"
    return None


def file_fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def source_fingerprints(task_dir: Path, route: str) -> dict[str, str]:
    names = ["05_log.md"]
    if route in ELIGIBLE_ROUTES:
        names.append("30_plan.md")
    if (task_dir / "task-meta.json").is_file():
        names.append("task-meta.json")
    return {
        name: file_fingerprint(task_dir / name)
        for name in names
        if (task_dir / name).is_file()
    }


def detect_route(log_text: str) -> str | None:
    matches = ROUTE_PATTERN.findall(log_text)
    return matches[-1] if matches else None


def validate_delegation_decision(log_text: str) -> tuple[list[str] | None, list[str]]:
    matches = list(DELEGATION_DECISION_PATTERN.finditer(log_text))
    if not matches:
        return None, []
    fields: dict[str, str] = {}
    for line in matches[-1].group(1).splitlines():
        match = DECISION_FIELD_PATTERN.match(line)
        if match:
            fields[match.group(1)] = match.group(2).strip()
    missing = [field for field in DELEGATION_DECISION_FIELDS if not fields.get(field)]
    invalid = [
        field for field, choices in DELEGATION_DECISION_ENUMS.items()
        if fields.get(field) and fields[field] not in choices
    ]
    return missing, invalid


def validate_ui_preview_authoring(
    plan_model: dict[str, Any] | str,
) -> tuple[list[str], list[str]]:
    """Require one minimally valid preview block for each LLM-declared UI task."""
    if isinstance(plan_model, str):
        plan_model = parse_plan_contract(plan_model)
    missing: list[str] = []
    invalid: list[str] = []
    for task in plan_model.get("tasks", []):
        task_number = str(task.get("number", ""))
        body = str(task.get("body", ""))
        if not UI_CHANGE_MARKER_PATTERN.search(body):
            continue
        blocks = list(UI_PREVIEW_BLOCK_PATTERN.finditer(body))
        if not blocks:
            missing.append(task_number)
            continue
        if len(blocks) != 1:
            invalid.append(task_number)
            continue
        try:
            payload = json.loads(blocks[0].group(1))
        except json.JSONDecodeError:
            invalid.append(task_number)
            continue
        previews = payload.get("previews") if isinstance(payload, dict) else None
        if (
            not isinstance(payload, dict)
            or payload.get("version") != 1
            or str(payload.get("taskNumber")) != task_number
            or not isinstance(previews, list)
            or not previews
        ):
            invalid.append(task_number)
    return missing, invalid


def _read_json_snapshot(path: Path) -> dict[str, Any] | None:
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return snapshot if isinstance(snapshot, dict) else None


def _read_embedded_snapshot(path: Path) -> dict[str, Any] | None:
    try:
        html = path.read_text(encoding="utf-8")
    except OSError:
        return None
    matches = list(EMBEDDED_SNAPSHOT_PATTERN.finditer(html))
    if len(matches) != 1:
        return None
    try:
        snapshot = json.loads(matches[0].group(1))
    except json.JSONDecodeError:
        return None
    return snapshot if isinstance(snapshot, dict) else None


def validate_generated_snapshot(
    snapshot_path: Path,
    task_dir: Path,
    expected_plan: dict[str, Any] | list[str],
) -> str | None:
    snapshot = _read_json_snapshot(snapshot_path)
    if snapshot is None:
        return "roadmap_snapshot_invalid"
    return _validate_snapshot_payload(snapshot, task_dir, expected_plan)


def _validate_snapshot_payload(
    snapshot: dict[str, Any],
    task_dir: Path,
    expected_plan: dict[str, Any] | list[str],
) -> str | None:
    """Validate a generated Roadmap snapshot against the parsed source plan.

    Snapshots generated before Plan v2 remain readable as a deliberately narrow
    compatibility path. Once a ``plan`` member is present, however, it is a v2
    contract and every identity, hash, node, and edge check is mandatory.
    """
    if snapshot.get("version") != 1:
        return "roadmap_snapshot_invalid"
    if snapshot.get("taskDir") != str(task_dir):
        return "roadmap_snapshot_invalid"
    files = snapshot.get("files")
    if not isinstance(files, dict):
        return "roadmap_snapshot_invalid"
    generated_plan = files.get("30_plan.md")
    if not isinstance(generated_plan, str):
        return "roadmap_snapshot_invalid"
    generated_progress = files.get("40_progress.md", "")
    if not isinstance(generated_progress, str):
        return "roadmap_snapshot_invalid"

    # Keep the old snapshot shape readable while the v2 generator is rolled
    # out. It still uses the same parser, so legacy and canonical headings do
    # not diverge at this boundary.
    if "plan" not in snapshot:
        try:
            generated_model = parse_plan_contract(generated_plan, generated_progress)
        except (PlanContractError, TypeError, ValueError):
            return "roadmap_snapshot_invalid"
        expected_task_ids = _task_ids(expected_plan)
        if _task_ids(generated_model) != expected_task_ids:
            return "roadmap_snapshot_task_mismatch"
        generated_edges = _edge_keys(generated_model.get("edges"))
        expected_edges = _edge_keys(_expected_edges(expected_plan))
        if generated_edges is None or expected_edges is None or generated_edges != expected_edges:
            return "roadmap_snapshot_edge_mismatch"
        return None

    plan = snapshot.get("plan")
    if not isinstance(plan, dict):
        return "roadmap_snapshot_plan_invalid"
    if plan.get("schemaVersion") != 2:
        return "roadmap_snapshot_plan_invalid"
    if not isinstance(plan.get("tasks"), list) or not isinstance(plan.get("edges"), list):
        return "roadmap_snapshot_plan_invalid"
    if not _tasks_have_contract_shape(plan["tasks"]):
        return "roadmap_snapshot_plan_invalid"
    if not isinstance(plan.get("parserVersion"), str) or not plan["parserVersion"].strip():
        return "roadmap_snapshot_plan_invalid"
    expected_progress = (
        expected_plan.get("progress")
        if isinstance(expected_plan, dict)
        else None
    )
    if not isinstance(plan.get("progress"), dict) or plan["progress"] != expected_progress:
        return "roadmap_snapshot_progress_mismatch"
    expected_source_hash = _expected_source_hash(expected_plan)
    if not _is_sha256(plan.get("sourceHash")) or plan.get("sourceHash") != expected_source_hash:
        return "roadmap_snapshot_source_mismatch"
    top_level_hash = snapshot.get("planSourceHash")
    if top_level_hash is not None and top_level_hash != expected_source_hash:
        return "roadmap_snapshot_source_mismatch"
    generation_id = snapshot.get("generationId")
    if not isinstance(generation_id, str) or not re.fullmatch(
        r"[A-Za-z0-9._:-]{1,128}", generation_id
    ):
        return "roadmap_snapshot_identity_invalid"
    fingerprint = snapshot.get("fingerprint")
    if fingerprint is not None:
        if not _is_sha256(fingerprint):
            return "roadmap_snapshot_identity_invalid"
        expected_generation_id = "roadmap-" + hashlib.sha256(
            ("v2\0" + fingerprint).encode("utf-8")
        ).hexdigest()[:20]
        if generation_id != expected_generation_id:
            return "roadmap_snapshot_identity_invalid"

    generated_model: dict[str, Any]
    try:
        generated_model = parse_plan_contract(generated_plan, generated_progress)
    except (PlanContractError, TypeError, ValueError):
        return "roadmap_snapshot_plan_invalid"
    expected_task_ids = _task_ids(expected_plan)
    generated_task_ids = _task_ids(generated_model)
    snapshot_task_ids = _task_ids(plan)
    if generated_task_ids != expected_task_ids or snapshot_task_ids != expected_task_ids:
        return "roadmap_snapshot_task_mismatch"
    expected_tasks = (
        expected_plan.get("tasks")
        if isinstance(expected_plan, dict)
        else None
    )
    if plan.get("tasks") != expected_tasks:
        return "roadmap_snapshot_task_mismatch"
    expected_edges = _expected_edges(expected_plan)
    generated_edges = _edge_keys(generated_model.get("edges"))
    expected_edge_keys = _edge_keys(expected_edges)
    snapshot_edges = _edge_keys(plan.get("edges"))
    if (
        generated_edges is None
        or expected_edge_keys is None
        or generated_edges != expected_edge_keys
    ):
        return "roadmap_snapshot_edge_mismatch"
    if snapshot_edges is None or snapshot_edges != expected_edge_keys:
        return "roadmap_snapshot_edge_mismatch"
    if generated_model.get("sourceHash") != expected_source_hash:
        return "roadmap_snapshot_source_mismatch"
    source_hashes = plan.get("sourceHashes")
    expected_source_hashes = _expected_source_hashes(expected_plan)
    if source_hashes is not None and source_hashes != expected_source_hashes:
        return "roadmap_snapshot_source_mismatch"
    generated_plan_hash = _sha256(generated_plan)
    if expected_source_hashes and generated_plan_hash != expected_source_hashes.get("30_plan.md"):
        return "roadmap_snapshot_source_mismatch"
    return None


def validate_snapshot_pair(
    html_path: Path,
    json_path: Path,
    task_dir: Path,
    expected_plan: dict[str, Any] | list[str],
) -> str | None:
    """Require HTML and JSON artifacts to publish one identical snapshot."""
    html_snapshot = _read_embedded_snapshot(html_path)
    json_snapshot = _read_json_snapshot(json_path)
    if html_snapshot is None or json_snapshot is None:
        return "roadmap_snapshot_pair_invalid"
    html_error = _validate_snapshot_payload(html_snapshot, task_dir, expected_plan)
    if html_error:
        return "roadmap_snapshot_html_invalid"
    json_error = _validate_snapshot_payload(json_snapshot, task_dir, expected_plan)
    if json_error:
        return "roadmap_snapshot_pair_invalid"
    if _snapshot_identity(html_snapshot) != _snapshot_identity(json_snapshot):
        return "roadmap_snapshot_pair_mismatch"
    if _snapshot_plan_signature(html_snapshot) != _snapshot_plan_signature(json_snapshot):
        return "roadmap_snapshot_pair_mismatch"
    return None


def _snapshot_identity(snapshot: dict[str, Any]) -> tuple[object, object, object]:
    plan_source_hash = snapshot.get("planSourceHash")
    plan = snapshot.get("plan")
    if plan_source_hash is None and isinstance(plan, dict):
        plan_source_hash = plan.get("sourceHash")
    return (
        snapshot.get("fingerprint"),
        snapshot.get("generationId"),
        plan_source_hash,
    )


def _snapshot_plan_signature(snapshot: dict[str, Any]) -> str:
    plan = snapshot.get("plan")
    if not isinstance(plan, dict):
        files = snapshot.get("files")
        legacy_plan = files.get("30_plan.md") if isinstance(files, dict) else None
        return json.dumps(
            {"legacyPlan": legacy_plan},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    return json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _task_ids(plan: dict[str, Any] | list[str]) -> list[str]:
    if isinstance(plan, list):
        return [str(value) for value in plan]
    tasks = plan.get("tasks")
    if not isinstance(tasks, list):
        return []
    ids: list[str] = []
    for task in tasks:
        if not isinstance(task, dict) or not isinstance(task.get("number"), str):
            return []
        ids.append(task["number"])
    return ids


def _tasks_have_contract_shape(tasks: object) -> bool:
    if not isinstance(tasks, list):
        return False
    required_string_fields = {"number", "title", "purpose", "blockedBy", "status", "body"}
    required_list_fields = {
        "targets",
        "implementation",
        "outputs",
        "verification",
        "steps",
    }
    for task in tasks:
        if not isinstance(task, dict):
            return False
        if any(not isinstance(task.get(field), str) for field in required_string_fields):
            return False
        if any(not task[field].strip() for field in ("number", "title", "status", "body")):
            return False
        if any(not isinstance(task.get(field), list) for field in required_list_fields):
            return False
        if not isinstance(task.get("done"), int) or not isinstance(task.get("total"), int):
            return False
        if task["done"] < 0 or task["total"] < 0:
            return False
        source = task.get("source")
        if not isinstance(source, dict):
            return False
        if not isinstance(source.get("file"), str) or not source["file"].strip():
            return False
        if not isinstance(source.get("lineStart"), int) or not isinstance(
            source.get("lineEnd"), int
        ):
            return False
    return True


def _expected_source_hash(plan: dict[str, Any] | list[str]) -> str | None:
    if isinstance(plan, dict):
        value = plan.get("sourceHash")
        return value if isinstance(value, str) else None
    return None


def _expected_source_hashes(plan: dict[str, Any] | list[str]) -> dict[str, str]:
    if isinstance(plan, dict) and isinstance(plan.get("sourceHashes"), dict):
        return {
            str(key): str(value)
            for key, value in plan["sourceHashes"].items()
            if isinstance(value, str)
        }
    return {}


def _expected_edges(plan: dict[str, Any] | list[str]) -> list[dict[str, str]]:
    if isinstance(plan, dict) and isinstance(plan.get("edges"), list):
        return [edge for edge in plan["edges"] if isinstance(edge, dict)]
    return []


def _edge_keys(edges: object) -> list[tuple[str, str, str]] | None:
    if not isinstance(edges, list):
        return None
    values: list[tuple[str, str, str]] = []
    for edge in edges:
        if not isinstance(edge, dict):
            return None
        source = edge.get("from")
        target = edge.get("to")
        kind = edge.get("kind")
        if not all(isinstance(value, str) and value for value in (source, target, kind)):
            return None
        values.append((source, target, kind))
    return sorted(values)


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))


def roadmap_command(
    task_dir: Path,
    generator: Path,
    phase: str,
    open_requested: bool,
    headless: bool,
) -> list[str]:
    command = [
        sys.executable,
        str(generator),
        str(task_dir),
        "--json",
        "--task-state",
        PHASE_STATES[phase],
    ]
    if open_requested and not headless:
        command.append("--open")
    return command


def synchronize(
    task_dir: Path,
    generator: Path,
    phase: str,
    workspace_root: Path,
    run_id: str,
    memory_root: Path | None = None,
    open_requested: bool = False,
    headless: bool = False,
    dry_run: bool = False,
) -> tuple[int, dict[str, object]]:
    task_dir = task_dir.resolve()
    workspace_root = workspace_root.resolve()
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", run_id):
        return 2, {"status": "failed", "reason": "run_id_invalid"}
    selected_memory_root = (memory_root or workspace_root / ".local" / "memory").resolve()
    if not valid_task_dir(task_dir, selected_memory_root):
        return 2, {
            "status": "failed",
            "reason": "task_dir_outside_memory",
            "path": str(task_dir),
            "memory_root": str(selected_memory_root),
        }
    metadata_error = validate_task_metadata(task_dir, workspace_root)
    if metadata_error:
        return 2, {"status": "failed", "reason": metadata_error}
    log_path = task_dir / "05_log.md"
    if not log_path.is_file():
        return 2, {"status": "failed", "reason": "log_missing", "path": str(log_path)}
    log_text = log_path.read_text(encoding="utf-8")
    route = detect_route(log_text)
    if route is None:
        return 2, {"status": "failed", "reason": "route_missing"}
    if phase == "2":
        missing_fields, invalid_fields = validate_delegation_decision(log_text)
        if missing_fields is None:
            return 2, {"status": "failed", "route": route, "reason": "delegation_decision_missing"}
        if missing_fields or invalid_fields:
            return 2, {
                "status": "failed",
                "route": route,
                "reason": "delegation_decision_invalid",
                **({"missing_fields": missing_fields} if missing_fields else {}),
                **({"invalid_fields": invalid_fields} if invalid_fields else {}),
            }
    if route == "log-only":
        return 0, {
            "status": "skipped",
            "route": route,
            "phase": phase,
            "task_dir": str(task_dir),
            "workspace_root": str(workspace_root),
            "run_id": run_id,
            "generated_at_unix": time.time(),
            "source_fingerprints": source_fingerprints(task_dir, route),
            "reason": "log_only",
        }
    plan_path = task_dir / "30_plan.md"
    if not plan_path.is_file():
        return 2, {
            "status": "failed",
            "route": route,
            "reason": "plan_missing",
            "path": str(plan_path),
        }
    progress_path = task_dir / "40_progress.md"
    try:
        plan_model = parse_plan_files(plan_path, progress_path)
    except (OSError, UnicodeError, PlanContractError, TypeError, ValueError) as exc:
        return 2, {
            "status": "failed",
            "route": route,
            "reason": "plan_contract_invalid",
            "path": str(plan_path),
            "error": str(exc),
        }
    if not plan_model.get("tasks"):
        return 2, {
            "status": "failed",
            "route": route,
            "reason": "plan_tasks_missing",
            "path": str(plan_path),
        }
    if phase == "2":
        missing_ui, invalid_ui = validate_ui_preview_authoring(
            plan_model
        )
        if missing_ui or invalid_ui:
            return 2, {
                "status": "failed",
                "route": route,
                "reason": "ui_preview_authoring_incomplete",
                **({"missing_task_numbers": missing_ui} if missing_ui else {}),
                **({"invalid_task_numbers": invalid_ui} if invalid_ui else {}),
            }
        diagnostics = plan_model.get("diagnostics")
        if isinstance(diagnostics, list) and diagnostics:
            return 2, {
                "status": "failed",
                "route": route,
                "reason": "plan_diagnostics_present",
                "diagnostics": diagnostics,
            }
    if not generator.is_file():
        return 2, {
            "status": "failed",
            "route": route,
            "reason": "generator_missing",
            "path": str(generator),
        }

    command = roadmap_command(
        task_dir, generator.resolve(), phase, open_requested, headless
    )
    open_status = "requested" if open_requested and not headless else "not_requested"
    if open_requested and headless:
        open_status = "suppressed_headless"
    if dry_run:
        return 0, {
            "status": "dry_run",
            "route": route,
            "phase": phase,
            "task_dir": str(task_dir),
            "workspace_root": str(workspace_root),
            "run_id": run_id,
            "open_status": open_status,
            "command": command,
            "plan_source_hash": plan_model.get("sourceHash"),
            "plan_task_ids": _task_ids(plan_model),
            "plan_edges": plan_model.get("edges", []),
        }
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        return completed.returncode, {
            "status": "failed",
            "route": route,
            "reason": "generator_failed",
            "stderr": completed.stderr.strip(),
        }
    artifacts = (task_dir / "roadmap.html", task_dir / "roadmap-snapshot.json")
    missing = [str(path) for path in artifacts if not path.is_file()]
    if missing:
        return 2, {
            "status": "failed",
            "route": route,
            "reason": "roadmap_artifact_missing",
            "missing": missing,
        }
    snapshot_error = validate_generated_snapshot(
        task_dir / "roadmap-snapshot.json",
        task_dir,
        plan_model,
    )
    if snapshot_error:
        return 2, {
            "status": "failed",
            "route": route,
            "reason": snapshot_error,
            "path": str(task_dir / "roadmap-snapshot.json"),
        }
    pair_error = validate_snapshot_pair(
        task_dir / "roadmap.html",
        task_dir / "roadmap-snapshot.json",
        task_dir,
        plan_model,
    )
    if pair_error:
        return 2, {
            "status": "failed",
            "route": route,
            "reason": pair_error,
            "paths": [
                str(task_dir / "roadmap.html"),
                str(task_dir / "roadmap-snapshot.json"),
            ],
        }
    metadata_error = validate_task_metadata(task_dir, workspace_root)
    if metadata_error:
        return 2, {"status": "failed", "reason": metadata_error}
    return 0, {
        "status": "synchronized",
        "route": route,
        "phase": phase,
        "task_dir": str(task_dir),
        "open_status": open_status,
        "roadmap": str(task_dir / "roadmap.html"),
        "workspace_root": str(workspace_root),
        "run_id": run_id,
        "generated_at_unix": time.time(),
        "plan_source_hash": plan_model.get("sourceHash"),
        "plan_task_ids": _task_ids(plan_model),
        "plan_edges": plan_model.get("edges", []),
        "source_fingerprints": source_fingerprints(task_dir, route),
        "artifact_fingerprints": {
            path.name: file_fingerprint(path) for path in artifacts
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_dir", type=Path)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--memory-root", type=Path)
    parser.add_argument("--phase", choices=sorted(PHASE_STATES), required=True)
    parser.add_argument("--open", action="store_true", dest="open_requested")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--generator",
        type=Path,
        default=Path(__file__).with_name("generate-roadmap-view.py"),
    )
    args = parser.parse_args()
    code, result = synchronize(
        args.task_dir,
        args.generator,
        args.phase,
        args.workspace_root,
        args.run_id,
        memory_root=args.memory_root,
        open_requested=args.open_requested,
        headless=args.headless,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
