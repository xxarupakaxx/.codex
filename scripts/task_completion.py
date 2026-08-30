#!/usr/bin/env python3
"""Pure, filesystem-bound completion checks used by roadmap Phase 5."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

try:
    from agent_delivery_lifecycle import COMPLETION_ORDER, validate_artifact
except ModuleNotFoundError:
    _spec = importlib.util.spec_from_file_location(
        "agent_delivery_lifecycle", Path(__file__).with_name("agent_delivery_lifecycle.py")
    )
    if _spec is None or _spec.loader is None:
        raise
    _lifecycle = importlib.util.module_from_spec(_spec)
    sys.modules[_spec.name] = _lifecycle
    _spec.loader.exec_module(_lifecycle)
    COMPLETION_ORDER = _lifecycle.COMPLETION_ORDER
    validate_artifact = _lifecycle.validate_artifact


SHA256 = re.compile(r"[0-9a-f]{64}\Z")
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
ACCEPTANCE = re.compile(
    r"^\s*(?:[-*+]\s+)?acceptance\s*[:：]\s*(.*)$", re.I | re.M
)
CHECKPOINT_ID = re.compile(
    r"^\s*(?:[-*+]\s+)?(?:\[[ xX]\]\s*)?"
    r"([A-Za-z0-9][A-Za-z0-9._-]*)(?:\s*:\s*|\s*$)"
)
REQUIRED = re.compile(
    r"^\s*(?:[-*+]\s+)?required[ _-]*sources\s*[:：]\s*(.*)$", re.I
)
REQUIRED_HEADING = re.compile(r"^\s*#{1,6}\s+required[ _-]*sources\s*$", re.I)
SCOPED = re.compile(r"\A(task|workspace):(.+)\Z")
LINE = re.compile(r"\AL([1-9][0-9]*)(?:-L([1-9][0-9]*))?\Z")
SECRET = re.compile(
    r"(?:secret|credential|password|passwd|api[_-]?key|private[_-]?key|access[_-]?token)",
    re.I,
)
SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".kdbx", ".age", ".gpg")
ROADMAP_OUTPUT = "roadmap" + ".html"
RESERVED = {
    "05_log.md", "evidence-bundle.json",
    ROADMAP_OUTPUT, "roadmap-snapshot.json", "task-meta.json",
}
MANDATORY = {"task:30_plan.md", "task:40_progress.md"}
NO_WORKSPACE_WRITES = "N/A: no workspace writes"


class CompletionValidationError(ValueError):
    """Stable failure reason returned to the sync boundary."""

    def __init__(self, reason: str, **details: object) -> None:
        self.reason = reason
        self.details = details
        super().__init__(reason)


def _fail(reason: str, **details: object) -> None:
    raise CompletionValidationError(reason, **details)


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path: Path, reason: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        _fail(reason, path=str(path))
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        _fail(reason, path=str(path), error=str(exc))
    if not isinstance(value, dict):
        _fail(reason, path=str(path), error="JSON root must be an object")
    return value


def _optional(root: Path, names: tuple[str, ...], reason: str) -> Path | None:
    found = [root / name for name in names if (root / name).exists() or (root / name).is_symlink()]
    if len(found) > 1:
        _fail(reason, paths=[str(path) for path in found])
    return found[0] if found else None


def _safe(path: str, *, reserved: bool = True) -> str:
    if not isinstance(path, str) or not path or "\x00" in path or "\\" in path:
        _fail("completion_source_path_invalid", path=path)
    if any(part in {".", ".."} for part in path.split("/")):
        _fail("completion_source_path_invalid", path=path)
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or not parsed.parts or any(part in {".", ".."} for part in parsed.parts):
        _fail("completion_source_path_invalid", path=path)
    lowered = [part.casefold() for part in parsed.parts]
    if any(part.startswith(".env") or part in {".ssh", "secrets", "credentials", "passwords"} for part in lowered):
        _fail("completion_secret_path_rejected", path=path)
    if any(
        SECRET.search(part) or part.casefold().endswith(SECRET_SUFFIXES)
        for part in parsed.parts
    ):
        _fail("completion_secret_path_rejected", path=path)
    if reserved and parsed.name.casefold() in RESERVED:
        _fail("completion_self_reference_rejected", path=path)
    return path


def _ref(value: str, *, default: str | None = None, fragment: bool = False) -> tuple[str, str, str, str | None]:
    if not isinstance(value, str) or not value:
        _fail("completion_source_scope_invalid", path=value)
    suffix: str | None = None
    if fragment and "#" in value:
        value, suffix = value.rsplit("#", 1)
        if not LINE.fullmatch(suffix):
            _fail("completion_evidence_ref_invalid", ref=value)
    for prefix in ("source:", "evidence:"):
        if value.startswith(prefix):
            value = value[len(prefix):]
            break
    match = SCOPED.fullmatch(value)
    if match:
        scope, path = match.groups()
    elif default is not None:
        scope, path = default, value
    else:
        _fail("completion_source_scope_invalid", path=value)
    path = _safe(path)
    return scope, path, f"{scope}:{path}", suffix


def _has_symlink(root: Path, relative: str) -> bool:
    current = root
    for part in PurePosixPath(relative).parts:
        current /= part
        if current.is_symlink():
            return True
    return False


def _file(root: Path, relative: str) -> Path:
    path = root.joinpath(*PurePosixPath(relative).parts)
    if _has_symlink(root, relative):
        _fail("completion_source_symlink_rejected", path=relative)
    if not path.is_file():
        _fail("completion_source_missing", path=relative)
    return path


def _source_values(value: str) -> list[str]:
    value = value.strip()
    if value.startswith("[") or value.endswith("]"):
        if not (value.startswith("[") and value.endswith("]")):
            _fail("completion_source_path_invalid", path=value)
        value = value[1:-1].strip()
    tokens = [part.strip() for part in value.split(",")] if "," in value else value.split()
    result: list[str] = []
    for token in tokens:
        if not token:
            _fail("completion_source_path_invalid", path=value)
        if token[:1] in {'"', "'"} or token[-1:] in {'"', "'"}:
            if len(token) < 2 or token[0] != token[-1]:
                _fail("completion_source_path_invalid", path=token)
            token = token[1:-1]
        if any(char in token for char in "[]{}\"'"):
            _fail("completion_source_path_invalid", path=token)
        result.append(token)
    return result


def extract_required_sources(plan_text: str) -> list[str]:
    values: list[str] = []
    collecting = False
    for line in plan_text.splitlines():
        marker = REQUIRED.match(line)
        if marker:
            collecting = True
            values.extend(_source_values(marker.group(1)))
            continue
        if REQUIRED_HEADING.match(line):
            collecting = True
            continue
        if not collecting:
            continue
        if not line.strip():
            collecting = False
            continue
        if re.match(r"^\s*#{1,6}\s+", line) or not re.match(r"^\s*(?:[-*+]\s+)?(?:task|workspace):", line):
            collecting = False
            continue
        values.extend(_source_values(re.sub(r"^\s*[-*+]\s+", "", line)))
    if not values:
        _fail("completion_required_sources_missing")
    canonical: list[str] = []
    for value in values:
        _, _, name, _ = _ref(value)
        canonical.append(name)
    if len(canonical) != len(set(canonical)):
        _fail("completion_required_sources_duplicate")
    return canonical


def extract_planned_acceptance_ids(plan_model: Mapping[str, Any]) -> list[str]:
    tasks = plan_model.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        _fail("completion_plan_tasks_missing")
    planned: list[str] = []
    for task in tasks:
        if not isinstance(task, Mapping):
            _fail("completion_plan_task_invalid")
        number, body = str(task.get("number", "")), task.get("body")
        if not isinstance(body, str):
            _fail("completion_acceptance_missing", task=number)
        task_ids: list[str] = []
        for match in ACCEPTANCE.finditer(body):
            parts = [part.strip() for part in match.group(1).split(",")]
            if not parts or any(not ID.fullmatch(part) for part in parts):
                _fail("completion_acceptance_invalid", task=number)
            task_ids.extend(parts)
        if not task_ids:
            _fail("completion_acceptance_missing", task=number)
        if len(task_ids) != len(set(task_ids)):
            _fail("completion_acceptance_duplicate", task=number)
        planned.extend(item for item in task_ids if item not in planned)
    return planned


def extract_checkpoint_acceptance_ids(text: str) -> list[str]:
    values = [
        match.group(1)
        for line in text.splitlines()
        for match in [CHECKPOINT_ID.match(line)]
        if match
    ]
    if len(values) != len(set(values)):
        _fail("completion_acceptance_duplicate", source="checkpoint.md")
    return values


def _raw_steps_complete(plan_model: Mapping[str, Any]) -> None:
    missing: list[str] = []
    for task in plan_model.get("tasks", []):
        number = str(task.get("number", "?")) if isinstance(task, Mapping) else "?"
        steps = task.get("steps") if isinstance(task, Mapping) else None
        if not isinstance(steps, list) or not steps:
            missing.append(number)
            continue
        for index, step in enumerate(steps, 1):
            if not isinstance(step, Mapping) or step.get("complete") is not True:
                missing.append(f"{number}:{index}")
    if missing:
        _fail("completion_plan_steps_incomplete", steps=missing)


def _fingerprints(
    task: Path, workspace: Path, refs: list[str] | Mapping[str, str], supplied: Any, *, evidence: bool
) -> int:
    if not isinstance(supplied, Mapping):
        _fail("completion_evidence_fingerprints_invalid" if evidence else "completion_source_fingerprints_invalid")
    raw_refs = list(refs.values()) if isinstance(refs, Mapping) else refs
    expected: dict[str, Path] = {}
    for raw in raw_refs:
        scope, relative, canonical, fragment = _ref(raw, default="task" if evidence else None, fragment=evidence)
        if not evidence and scope == "task" and PurePosixPath(relative).name.casefold() == "90_verification.md":
            _fail("completion_self_reference_rejected", path=raw)
        path = _file(task if scope == "task" else workspace, relative)
        if fragment:
            match = LINE.fullmatch(fragment)
            assert match
            try:
                if match.group(2) and int(match.group(1)) > int(match.group(2)):
                    _fail("completion_evidence_ref_invalid", ref=raw)
                end = int(match.group(2) or match.group(1))
                if end > len(path.read_text(encoding="utf-8").splitlines()):
                    _fail("completion_evidence_ref_invalid", ref=raw)
            except (OSError, UnicodeError) as exc:
                _fail("completion_evidence_ref_invalid", ref=raw, error=str(exc))
        expected[canonical] = path
    supplied_canonical: dict[str, str] = {}
    for key, value in supplied.items():
        if not isinstance(key, str) or (evidence and "#" in key):
            _fail("completion_evidence_fingerprints_invalid" if evidence else "completion_source_set_mismatch", path=key)
        _, _, canonical, _ = _ref(key, default="task" if evidence else None)
        if canonical in supplied_canonical:
            _fail("completion_evidence_fingerprints_invalid" if evidence else "completion_source_set_mismatch", path=key)
        if not isinstance(value, str) or not SHA256.fullmatch(value):
            _fail("completion_evidence_fingerprint_invalid" if evidence else "completion_source_fingerprint_invalid", path=key)
        supplied_canonical[canonical] = value
    if set(expected) != set(supplied_canonical):
        _fail(
            "completion_evidence_set_mismatch" if evidence else "completion_source_set_mismatch",
            missing=sorted(set(expected) - set(supplied_canonical)),
            extra=sorted(set(supplied_canonical) - set(expected)),
        )
    for canonical, path in expected.items():
        if _sha(path) != supplied_canonical[canonical]:
            _fail("completion_evidence_stale" if evidence else "completion_source_stale", ref=canonical)
    return len(expected)


def _evidence_refs(bundle: Mapping[str, Any], planned: list[str]) -> dict[str, str]:
    entries = bundle.get("acceptance_evidence")
    if not isinstance(entries, list):
        _fail("completion_acceptance_mismatch")
    refs: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, str):
            _fail("completion_acceptance_mismatch")
        parts = entry.split("|")
        if len(parts) < 3 or parts[0] != parts[0].strip() or parts[1] != "PASS":
            _fail("completion_acceptance_mismatch", entry=entry)
        acceptance_id = parts[0]
        if acceptance_id in refs:
            _fail("completion_acceptance_duplicate", ids=[acceptance_id])
        if acceptance_id not in planned:
            _fail("completion_acceptance_mismatch", unknown=[acceptance_id])
        path_refs = [
            part[len(prefix):] if part.startswith(prefix) else part
            for part in parts[2:]
            for prefix in ("source:", "evidence:")
            if part.startswith(prefix)
        ]
        path_refs.extend(
            part for part in parts[2:] if part.startswith("task:") or part.startswith("workspace:")
        )
        if len(path_refs) != 1 or not path_refs[0]:
            _fail("completion_acceptance_mismatch", entry=entry)
        refs[acceptance_id] = path_refs[0]
    if set(refs) != set(planned):
        _fail(
            "completion_acceptance_mismatch",
            missing=sorted(set(planned) - set(refs)),
            extra=sorted(set(refs) - set(planned)),
        )
    return refs


def _workspace_path(value: str) -> str:
    if isinstance(value, str) and value.startswith("workspace:"):
        value = value[len("workspace:"):]
    elif isinstance(value, str) and value.startswith("task:"):
        _fail("completion_write_scope_invalid", path=value)
    return _safe(value)


def _packet_and_writes(
    task: Path, workspace: Path, required: list[str], planned: list[str], bundle: Mapping[str, Any]
) -> str:
    packet_path = _optional(task, ("work-packet.json",), "completion_work_packet_invalid")
    state = bundle.get("completion_state")
    if packet_path is None:
        if state != "implemented":
            _fail("completion_target_unmet", target="implemented", state=state)
        allowed = [source.split(":", 1)[1] for source in required if source.startswith("workspace:")]
    else:
        packet = _json(packet_path, "completion_work_packet_invalid")
        errors = validate_artifact("work_packet", packet)
        if errors:
            _fail("completion_work_packet_invalid", errors=errors)
        if packet.get("source_hash") != bundle.get("source_hash"):
            _fail("completion_work_packet_mismatch", field="source_hash")
        ids = packet.get("acceptance_ids")
        if not isinstance(ids, list) or len(ids) != len(set(ids)) or set(ids) != set(planned):
            _fail("completion_work_packet_mismatch", field="acceptance_ids")
        target = packet.get("completion_target")
        if not isinstance(target, str) or not isinstance(state, str) or target not in COMPLETION_ORDER or state not in COMPLETION_ORDER:
            _fail("completion_target_unmet", target=target, state=state)
        if COMPLETION_ORDER[state] < COMPLETION_ORDER[target]:
            _fail("completion_target_unmet", target=target, state=state)
        raw_allowed = packet.get("owned_paths")
        if not isinstance(raw_allowed, list) or any(not isinstance(item, str) for item in raw_allowed):
            _fail("completion_work_packet_invalid", field="owned_paths")
        allowed = [_workspace_path(item) for item in raw_allowed]
        if len(allowed) != len(set(allowed)):
            _fail("completion_work_packet_invalid", field="owned_paths")
        declared_workspace = [
            source.split(":", 1)[1] for source in required if source.startswith("workspace:")
        ]
        if any(item not in declared_workspace for item in allowed):
            _fail("completion_work_packet_mismatch", field="owned_paths")
    writes = bundle.get("writes_performed")
    if not isinstance(writes, list):
        _fail("completion_write_scope_invalid")
    if NO_WORKSPACE_WRITES in writes:
        if writes != [NO_WORKSPACE_WRITES]:
            _fail("completion_write_scope_invalid", path=NO_WORKSPACE_WRITES)
        return target if packet_path is not None else "implemented"
    for write in writes:
        path = _workspace_path(write)
        if path not in allowed:
            _fail("completion_write_scope_invalid", path=write)
        if _has_symlink(workspace, path):
            _fail("completion_source_symlink_rejected", path=path)
    return target if packet_path is not None else "implemented"


def validate_phase5_completion(
    task_dir: str | Path,
    workspace_root: str | Path,
    plan_model: Mapping[str, Any],
) -> dict[str, object]:
    """Validate Phase 5 using the sync parser's trusted ``plan_model``.

    The plan text is always read from the task's ``30_plan.md``.  The sync
    caller supplies the already parsed ``parse_plan_files`` result; this gate
    has no command or write side effects.
    """
    task, workspace = Path(task_dir).resolve(), Path(workspace_root).resolve()
    if not task.is_dir() or not workspace.is_dir():
        _fail("completion_root_invalid")
    plan_path = task / "30_plan.md"
    if plan_path.is_symlink() or not plan_path.is_file():
        _fail("completion_plan_missing", path=str(plan_path))
    try:
        plan_text = plan_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        _fail("completion_plan_invalid", error=str(exc))
    planned = extract_planned_acceptance_ids(plan_model)
    diagnostics = plan_model.get("diagnostics")
    if isinstance(diagnostics, list) and diagnostics:
        _fail("completion_plan_diagnostics_present", diagnostics=diagnostics)
    checkpoint = task / "checkpoint.md"
    checkpoint_ids: list[str] = []
    if checkpoint.exists() or checkpoint.is_symlink():
        if checkpoint.is_symlink() or not checkpoint.is_file():
            _fail("completion_checkpoint_invalid")
        try:
            checkpoint_ids = extract_checkpoint_acceptance_ids(
                checkpoint.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError) as exc:
            _fail("completion_checkpoint_invalid", error=str(exc))
        if not checkpoint_ids or set(checkpoint_ids) != set(planned):
            _fail("completion_acceptance_mismatch", source="checkpoint.md")
    evidence_path = _optional(task, ("evidence-bundle.json",), "completion_evidence_invalid")
    if evidence_path is None:
        _fail("completion_evidence_missing", path=str(task / "evidence-bundle.json"))
    bundle = _json(evidence_path, "completion_evidence_invalid")
    errors = validate_artifact("evidence_bundle", bundle)
    if errors:
        _fail("completion_evidence_invalid", errors=errors)
    _raw_steps_complete(plan_model)
    if bundle.get("source_hash") != plan_model.get("sourceHash"):
        _fail("completion_source_hash_mismatch")
    required = extract_required_sources(plan_text)
    mandatory = set(MANDATORY)
    if checkpoint.exists() or checkpoint.is_symlink():
        mandatory.add("task:checkpoint.md")
    if not mandatory.issubset(required) or not set(required) - mandatory:
        _fail(
            "completion_required_sources_missing",
            missing=sorted(mandatory - set(required)) or ["declared production/test source"],
        )
    source_count = _fingerprints(task, workspace, required, bundle.get("source_fingerprints"), evidence=False)
    refs = _evidence_refs(bundle, planned)
    evidence_count = _fingerprints(task, workspace, refs, bundle.get("evidence_fingerprints"), evidence=True)
    if not isinstance(bundle.get("findings"), list) or bundle["findings"]:
        _fail("completion_findings_unresolved")
    target = _packet_and_writes(task, workspace, required, planned, bundle)
    return {
        "status": "pass",
        "planned_acceptance_ids": planned,
        "checkpoint_acceptance_ids": checkpoint_ids,
        "evidence_acceptance_ids": list(refs),
        "completion_state": bundle.get("completion_state"),
        "completion_target": target,
        "source_fingerprints_checked": source_count,
        "evidence_fingerprints_checked": evidence_count,
    }


__all__ = [
    "CompletionValidationError", "extract_checkpoint_acceptance_ids",
    "extract_planned_acceptance_ids", "extract_required_sources",
    "validate_phase5_completion",
]
