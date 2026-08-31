#!/usr/bin/env python3
"""Synchronize a task Roadmap from its recorded workflow route."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True


try:
    from roadmap_plan_contract import (
        PlanContractError, parse_plan_contract, parse_plan_files, resolve_plan_source,
        parse_html_plan_contract, strict_json_loads, is_safe_html_href, HTML_VISIBLE_TAGS,
        is_safe_svg_paint_value,
        HTML_COMMON_ATTRS, HTML_TAG_ATTRS,
    )
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
    resolve_plan_source = _PLAN_CONTRACT_MODULE.resolve_plan_source
    parse_html_plan_contract = _PLAN_CONTRACT_MODULE.parse_html_plan_contract
    strict_json_loads = _PLAN_CONTRACT_MODULE.strict_json_loads
    is_safe_html_href = _PLAN_CONTRACT_MODULE.is_safe_html_href
    HTML_VISIBLE_TAGS = _PLAN_CONTRACT_MODULE.HTML_VISIBLE_TAGS
    HTML_COMMON_ATTRS = _PLAN_CONTRACT_MODULE.HTML_COMMON_ATTRS
    HTML_TAG_ATTRS = _PLAN_CONTRACT_MODULE.HTML_TAG_ATTRS
    is_safe_svg_paint_value = _PLAN_CONTRACT_MODULE.is_safe_svg_paint_value


try:
    from task_completion import CompletionValidationError, validate_phase5_completion
except ModuleNotFoundError:
    _TASK_COMPLETION_PATH = Path(__file__).with_name("task_completion.py")
    _TASK_COMPLETION_SPEC = importlib.util.spec_from_file_location(
        "task_completion", _TASK_COMPLETION_PATH
    )
    if _TASK_COMPLETION_SPEC is None or _TASK_COMPLETION_SPEC.loader is None:
        raise
    _TASK_COMPLETION_MODULE = importlib.util.module_from_spec(_TASK_COMPLETION_SPEC)
    sys.modules[_TASK_COMPLETION_SPEC.name] = _TASK_COMPLETION_MODULE
    _TASK_COMPLETION_SPEC.loader.exec_module(_TASK_COMPLETION_MODULE)
    CompletionValidationError = _TASK_COMPLETION_MODULE.CompletionValidationError
    validate_phase5_completion = _TASK_COMPLETION_MODULE.validate_phase5_completion


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
PUBLISHED_OUTPUTS = ("roadmap.html", "roadmap-snapshot.json", "task-meta.json")
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
    except (OSError, UnicodeError, json.JSONDecodeError):
        return "task_metadata_invalid"
    if not isinstance(metadata, dict):
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
        html = task_dir / "30_plan.html"
        names.append("30_plan.html" if html.exists() or html.is_symlink() else "30_plan.md")
    if (task_dir / "task-meta.json").is_file():
        names.append("task-meta.json")
    return {
        name: file_fingerprint(task_dir / name)
        for name in names
        if (task_dir / name).is_file()
    }


def _backup_published_outputs(
    task_dir: Path,
) -> tuple[dict[str, bytes | None], list[str]]:
    backups: dict[str, bytes | None] = {}
    invalid: list[str] = []
    for name in PUBLISHED_OUTPUTS:
        path = task_dir / name
        if path.is_symlink() or (path.exists() and not path.is_file()):
            backups[name] = None
            invalid.append(name)
        elif path.is_file():
            backups[name] = path.read_bytes()
        else:
            backups[name] = None
    return backups, invalid


def _restore_published_outputs(
    task_dir: Path, backups: dict[str, bytes | None]
) -> list[str]:
    errors: list[str] = []
    for name, previous in backups.items():
        path = task_dir / name
        try:
            if previous is None:
                if path.is_symlink() or path.is_file():
                    path.unlink()
                elif path.exists():
                    raise OSError(f"cannot remove non-file output {path}")
                continue
            stage = path.with_name(
                f".{path.name}.{os.getpid()}.{time.time_ns()}.restore.tmp"
            )
            try:
                stage.write_bytes(previous)
                os.replace(stage, path)
            finally:
                try:
                    stage.unlink()
                except FileNotFoundError:
                    pass
        except OSError as exc:
            errors.append(f"{name}: {exc}")
    return errors


def _failed_after_generation(
    task_dir: Path,
    backups: dict[str, bytes | None],
    code: int,
    result: dict[str, object],
) -> tuple[int, dict[str, object]]:
    restore_errors = _restore_published_outputs(task_dir, backups)
    if restore_errors:
        result["restore_errors"] = restore_errors
    return code, result


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
    if plan_model.get("sourceKind") == "html":
        missing: list[str] = []
        invalid: list[str] = []
        for task in plan_model.get("tasks", []):
            if not isinstance(task, dict) or task.get("uiChange") is not True:
                continue
            number = str(task.get("number", ""))
            blocks = task.get("uiPreviewBlocks")
            if not isinstance(blocks, list) or not blocks:
                missing.append(number)
                continue
            if len(blocks) != 1 or any(
                not isinstance(block, dict)
                or block.get("version") != 1
                or str(block.get("taskNumber")) != number
                or not isinstance(block.get("previews"), list)
                or not block.get("previews")
                for block in blocks
            ):
                invalid.append(number)
        return missing, invalid
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
        snapshot = strict_json_loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, PlanContractError):
        return None
    return snapshot if isinstance(snapshot, dict) else None


def _read_embedded_snapshot(path: Path) -> dict[str, Any] | None:
    try:
        html = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    matches = list(EMBEDDED_SNAPSHOT_PATTERN.finditer(html))
    if len(matches) != 1:
        return None
    try:
        snapshot = strict_json_loads(matches[0].group(1))
    except (json.JSONDecodeError, PlanContractError):
        return None
    return snapshot if isinstance(snapshot, dict) else None


_ROADMAP_GENERATOR_MODULE: object | None = None


def _load_roadmap_generator() -> object:
    global _ROADMAP_GENERATOR_MODULE
    if _ROADMAP_GENERATOR_MODULE is not None:
        return _ROADMAP_GENERATOR_MODULE
    generator_path = Path(__file__).with_name("generate-roadmap-view.py")
    spec = importlib.util.spec_from_file_location("sync_roadmap_generator", generator_path)
    if spec is None or spec.loader is None:
        raise PlanContractError(f"cannot load Roadmap generator: {generator_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    _ROADMAP_GENERATOR_MODULE = module
    return module


def _derived_projection(
    task_dir: Path,
    expected_plan: dict[str, Any] | list[str],
    *,
    source_root: Path | None,
    base_ref: str | None,
) -> tuple[dict[str, object] | None, str | None]:
    if not isinstance(expected_plan, dict) or expected_plan.get("sourceKind") != "html":
        return None, None
    root = source_root
    if root is None:
        resolved_task = task_dir.resolve()
        if resolved_task.parent.name == "memory" and resolved_task.parent.parent.name == ".local":
            root = resolved_task.parent.parent.parent
        else:
            root = resolved_task.parent
    try:
        generator = _load_roadmap_generator()
        snapshot = generator.build_snapshot(task_dir, source_root=root, base_ref=base_ref)
    except (OSError, UnicodeError, PlanContractError, TypeError, ValueError, RuntimeError) as exc:
        return None, str(exc)
    return {
        field: snapshot.get(field)
        for field in ("sourcePreviews", "uiPreviews", "timeline")
    }, None


def _validate_derived_projection(
    snapshot: dict[str, Any],
    task_dir: Path,
    expected_plan: dict[str, Any] | list[str],
    *,
    source_root: Path | None,
    base_ref: str | None,
    expected_derived: dict[str, object] | None = None,
) -> str | None:
    if not isinstance(expected_plan, dict) or expected_plan.get("sourceKind") != "html":
        return None
    if expected_derived is None:
        expected_derived, error = _derived_projection(
            task_dir,
            expected_plan,
            source_root=source_root,
            base_ref=base_ref,
        )
        if error:
            return "roadmap_snapshot_derived_invalid"
    if expected_derived is None:
        return "roadmap_snapshot_derived_invalid"
    for field in ("sourcePreviews", "uiPreviews", "timeline"):
        if field not in snapshot or snapshot.get(field) != expected_derived.get(field):
            return f"roadmap_snapshot_{field}_mismatch"
    return None


def validate_generated_snapshot(
    snapshot_path: Path,
    task_dir: Path,
    expected_plan: dict[str, Any] | list[str],
    *,
    source_root: Path | None = None,
    base_ref: str | None = None,
) -> str | None:
    snapshot = _read_json_snapshot(snapshot_path)
    if snapshot is None:
        return "roadmap_snapshot_invalid"
    derived, derived_error = _derived_projection(
        task_dir,
        expected_plan,
        source_root=source_root,
        base_ref=base_ref,
    )
    if derived_error:
        return "roadmap_snapshot_derived_invalid"
    return _validate_snapshot_payload(
        snapshot,
        task_dir,
        expected_plan,
        source_root=source_root,
        base_ref=base_ref,
        expected_derived=derived,
    )


def _validate_snapshot_payload(
    snapshot: dict[str, Any],
    task_dir: Path,
    expected_plan: dict[str, Any] | list[str],
    *,
    source_root: Path | None = None,
    base_ref: str | None = None,
    expected_derived: dict[str, object] | None = None,
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
    snapshot_plan_source = snapshot.get("planSource")
    snapshot_plan = snapshot.get("plan")
    html_source = snapshot_plan_source == "30_plan.html" or (
        isinstance(snapshot_plan, dict) and snapshot_plan.get("sourceKind") == "html"
    )
    generated_plan_name = "30_plan.html" if html_source else "30_plan.md"
    generated_plan = files.get(generated_plan_name)
    if not isinstance(generated_plan, str):
        return "roadmap_snapshot_invalid"
    generated_progress = files.get("40_progress.md", "")
    if not isinstance(generated_progress, str):
        return "roadmap_snapshot_invalid"

    # Keep the old snapshot shape readable while the v2 generator is rolled
    # out. It still uses the same parser, so legacy and canonical headings do
    # not diverge at this boundary.
    if "plan" not in snapshot:
        if html_source:
            return "roadmap_snapshot_plan_invalid"
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
    expected_raw_sha256 = _expected_plan_raw_sha256(expected_plan)
    snapshot_raw_sha256 = snapshot.get("planSourceRawSha256")
    plan_raw_sha256 = plan.get("planSourceRawSha256")
    if (
        (snapshot_raw_sha256 is not None and not _is_sha256(snapshot_raw_sha256))
        or (plan_raw_sha256 is not None and not _is_sha256(plan_raw_sha256))
    ):
        return "roadmap_snapshot_source_mismatch"
    if expected_raw_sha256 and (
        (snapshot_raw_sha256 is not None and snapshot_raw_sha256 != expected_raw_sha256)
        or (plan_raw_sha256 is not None and plan_raw_sha256 != expected_raw_sha256)
    ):
        return "roadmap_snapshot_source_mismatch"
    expected_source_kind = expected_plan.get("sourceKind") if isinstance(expected_plan, dict) else None
    if expected_source_kind == "html":
        if snapshot_raw_sha256 != expected_raw_sha256 or plan_raw_sha256 != expected_raw_sha256:
            return "roadmap_snapshot_source_mismatch"
        if snapshot_plan_source != "30_plan.html":
            return "roadmap_snapshot_source_mismatch"
        if plan.get("sourceKind") != "html" or plan.get("planSource") != "30_plan.html":
            return "roadmap_snapshot_source_mismatch"
        if "30_plan.md" in files:
            return "roadmap_snapshot_source_mismatch"
        if snapshot.get("requiredSources") != expected_plan.get("requiredSources"):
            return "roadmap_snapshot_plan_invalid"
        if "planDocument" not in snapshot:
            return "roadmap_snapshot_plan_invalid"
        plan_document = snapshot.get("planDocument")
        expected_document = expected_plan.get("planDocument")
        if (
            plan_document != plan.get("planDocument")
            or plan_document != expected_document
            or not _plan_document_valid(plan_document)
        ):
            return "roadmap_snapshot_plan_invalid"
    elif snapshot_plan_source not in {None, "30_plan.md"}:
        return "roadmap_snapshot_source_mismatch"
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
    if html_source and top_level_hash != expected_source_hash:
        return "roadmap_snapshot_source_mismatch"
    if top_level_hash is not None and top_level_hash != expected_source_hash:
        return "roadmap_snapshot_source_mismatch"
    generation_id = snapshot.get("generationId")
    if not isinstance(generation_id, str) or not re.fullmatch(
        r"[A-Za-z0-9._:-]{1,128}", generation_id
    ):
        return "roadmap_snapshot_identity_invalid"
    fingerprint = snapshot.get("fingerprint")
    if html_source and not _is_sha256(fingerprint):
        return "roadmap_snapshot_identity_invalid"
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
        if html_source:
            generated_model = parse_html_plan_contract(
                generated_plan.encode("utf-8"),
                plan_source="30_plan.html",
                progress_source="40_progress.md",
            )
        else:
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
    if html_source and expected_raw_sha256 and generated_model.get("planSourceRawSha256") != expected_raw_sha256:
        return "roadmap_snapshot_source_mismatch"
    source_hashes = plan.get("sourceHashes")
    expected_source_hashes = _expected_source_hashes(expected_plan)
    if html_source and (not isinstance(source_hashes, dict) or source_hashes != expected_source_hashes):
        return "roadmap_snapshot_source_mismatch"
    if source_hashes is not None and source_hashes != expected_source_hashes:
        return "roadmap_snapshot_source_mismatch"
    generated_plan_hash = _sha256(generated_plan) if not html_source else hashlib.sha256(generated_plan.encode("utf-8")).hexdigest()
    expected_hash_name = "30_plan.html" if html_source else "30_plan.md"
    if expected_source_hashes and generated_plan_hash != expected_source_hashes.get(expected_hash_name):
        return "roadmap_snapshot_source_mismatch"
    derived_error = _validate_derived_projection(
        snapshot,
        task_dir,
        expected_plan,
        source_root=source_root,
        base_ref=base_ref,
        expected_derived=expected_derived,
    )
    if derived_error:
        return derived_error
    return None


def validate_snapshot_pair(
    html_path: Path,
    json_path: Path,
    task_dir: Path,
    expected_plan: dict[str, Any] | list[str],
    *,
    source_root: Path | None = None,
    base_ref: str | None = None,
) -> str | None:
    """Require HTML and JSON artifacts to publish one identical snapshot."""
    html_snapshot = _read_embedded_snapshot(html_path)
    json_snapshot = _read_json_snapshot(json_path)
    if html_snapshot is None or json_snapshot is None:
        return "roadmap_snapshot_pair_invalid"
    derived, derived_error = _derived_projection(
        task_dir,
        expected_plan,
        source_root=source_root,
        base_ref=base_ref,
    )
    if derived_error:
        return "roadmap_snapshot_derived_invalid"
    html_error = _validate_snapshot_payload(
        html_snapshot,
        task_dir,
        expected_plan,
        source_root=source_root,
        base_ref=base_ref,
        expected_derived=derived,
    )
    if html_error:
        return "roadmap_snapshot_html_invalid"
    json_error = _validate_snapshot_payload(
        json_snapshot,
        task_dir,
        expected_plan,
        source_root=source_root,
        base_ref=base_ref,
        expected_derived=derived,
    )
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


def _plan_document_valid(value: object) -> bool:
    """Validate the sanitized HTML semantic tree before publishing it."""
    if not isinstance(value, dict) or value.get("format") != "html":
        return False
    if not isinstance(value.get("title"), str) or not value["title"].strip():
        return False
    nodes = value.get("nodes")
    if not isinstance(nodes, list):
        return False
    seen_ids: set[str] = set()
    def node_valid(node: object) -> bool:
        if not isinstance(node, dict):
            return False
        if "text" in node:
            return set(node) == {"text"} and isinstance(node["text"], str)
        if set(node) - {"tag", "attrs", "children"}:
            return False
        tag, attrs, children = node.get("tag"), node.get("attrs"), node.get("children")
        if not isinstance(tag, str) or tag.casefold() not in HTML_VISIBLE_TAGS:
            return False
        allowed_attrs = HTML_COMMON_ATTRS | HTML_TAG_ATTRS.get(tag.casefold(), frozenset())
        if not isinstance(attrs, dict) or any(
            not isinstance(key, str) or not isinstance(item, str)
            or key.casefold().startswith("on") or key.casefold() == "style"
            or (key.casefold() not in allowed_attrs and not key.casefold().startswith("aria-"))
            for key, item in attrs.items()
        ):
            return False
        schema = attrs.get("data-plan-schema")
        if schema is not None and schema != "2":
            return False
        if attrs.get("aria-hidden", "").casefold() == "true":
            return False
        href = attrs.get("href")
        if href is not None and not is_safe_html_href(href, tag=tag.casefold(), attrs=attrs):
            return False
        target = attrs.get("target")
        if target is not None and target not in {"_self", "_blank"}:
            return False
        xmlns = attrs.get("xmlns")
        if xmlns is not None and (tag.casefold() != "svg" or xmlns != "http://www.w3.org/2000/svg"):
            return False
        identifier = attrs.get("id")
        if identifier is not None and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", identifier):
            return False
        if identifier is not None:
            if identifier in seen_ids:
                return False
            seen_ids.add(identifier)
        for paint_name in ("fill", "stroke", "marker-end", "marker-start"):
            paint = attrs.get(paint_name)
            if isinstance(paint, str) and not is_safe_svg_paint_value(paint):
                return False
        return isinstance(children, list) and all(node_valid(child) for child in children)

    return all(node_valid(node) for node in nodes)


def _expected_source_hash(plan: dict[str, Any] | list[str]) -> str | None:
    if isinstance(plan, dict):
        value = plan.get("sourceHash")
        return value if isinstance(value, str) else None
    return None


def _expected_plan_raw_sha256(plan: dict[str, Any] | list[str]) -> str | None:
    if isinstance(plan, dict):
        value = plan.get("planSourceRawSha256")
        return value if isinstance(value, str) and _is_sha256(value) else None
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
    try:
        log_text = log_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return 2, {
            "status": "failed",
            "reason": "log_invalid",
            "path": str(log_path),
            "error": str(exc),
        }
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
    html_path = task_dir / "30_plan.html"
    md_path = task_dir / "30_plan.md"
    source_path = html_path if html_path.exists() or html_path.is_symlink() else md_path
    if not source_path.is_file() or source_path.is_symlink():
        return 2, {
            "status": "failed",
            "route": route,
            "reason": "plan_missing",
            "path": str(source_path),
        }
    progress_path = task_dir / "40_progress.md"
    try:
        plan_model = resolve_plan_source(task_dir)
    except (OSError, UnicodeError, PlanContractError, TypeError, ValueError) as exc:
        return 2, {
            "status": "failed",
            "route": route,
            "reason": "plan_contract_invalid",
            "path": str(source_path),
            "error": str(exc),
        }
    if not plan_model.get("tasks"):
        return 2, {
            "status": "failed",
            "route": route,
            "reason": "plan_tasks_missing",
            "path": str(source_path),
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
    completion_gate: dict[str, object] | None = None
    if phase == "5":
        try:
            completion_gate = validate_phase5_completion(
                task_dir,
                workspace_root,
                plan_model,
            )
        except CompletionValidationError as exc:
            return 2, {
                "status": "failed",
                "route": route,
                "phase": phase,
                "reason": exc.reason,
                **exc.details,
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
            **({"completion_gate": completion_gate} if completion_gate else {}),
        }
    try:
        output_backups, invalid_outputs = _backup_published_outputs(task_dir)
    except OSError as exc:
        return 2, {
            "status": "failed",
            "route": route,
            "reason": "roadmap_artifact_backup_failed",
            "error": str(exc),
        }
    if invalid_outputs:
        return 2, {
            "status": "failed",
            "route": route,
            "reason": "roadmap_artifact_backup_invalid",
            "paths": [str(task_dir / name) for name in invalid_outputs],
        }
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    except (OSError, UnicodeError) as exc:
        return _failed_after_generation(
            task_dir,
            output_backups,
            2,
            {
                "status": "failed",
                "route": route,
                "reason": "generator_failed",
                "error": str(exc),
            },
        )
    if completed.returncode != 0:
        return _failed_after_generation(
            task_dir,
            output_backups,
            completed.returncode,
            {
                "status": "failed",
                "route": route,
                "reason": "generator_failed",
                "stderr": completed.stderr.strip(),
            },
        )
    artifacts = (task_dir / "roadmap.html", task_dir / "roadmap-snapshot.json")
    missing = [str(path) for path in artifacts if not path.is_file()]
    if missing:
        return _failed_after_generation(
            task_dir,
            output_backups,
            2,
            {
                "status": "failed",
                "route": route,
                "reason": "roadmap_artifact_missing",
                "missing": missing,
            },
        )
    snapshot_error = validate_generated_snapshot(
        task_dir / "roadmap-snapshot.json",
        task_dir,
        plan_model,
        source_root=workspace_root,
    )
    if snapshot_error:
        return _failed_after_generation(
            task_dir,
            output_backups,
            2,
            {
                "status": "failed",
                "route": route,
                "reason": snapshot_error,
                "path": str(task_dir / "roadmap-snapshot.json"),
            },
        )
    pair_error = validate_snapshot_pair(
        task_dir / "roadmap.html",
        task_dir / "roadmap-snapshot.json",
        task_dir,
        plan_model,
        source_root=workspace_root,
    )
    if pair_error:
        return _failed_after_generation(
            task_dir,
            output_backups,
            2,
            {
                "status": "failed",
                "route": route,
                "reason": pair_error,
                "paths": [
                    str(task_dir / "roadmap.html"),
                    str(task_dir / "roadmap-snapshot.json"),
                ],
            },
        )
    metadata_error = validate_task_metadata(task_dir, workspace_root)
    if metadata_error:
        return _failed_after_generation(
            task_dir,
            output_backups,
            2,
            {"status": "failed", "reason": metadata_error},
        )
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
        **({"completion_gate": completion_gate} if completion_gate else {}),
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
