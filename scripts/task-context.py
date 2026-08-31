#!/usr/bin/env python3
"""Read-only context for explicitly selected Roadmap task memory."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

sys.dont_write_bytecode = True

try:
    from roadmap_plan_contract import PlanContractError, parse_plan_files, resolve_plan_source
except ModuleNotFoundError:
    parser_path = Path(__file__).with_name("roadmap_plan_contract.py")
    parser_spec = importlib.util.spec_from_file_location("task_context_plan_parser", parser_path)
    if parser_spec is None or parser_spec.loader is None:
        raise
    parser_module = importlib.util.module_from_spec(parser_spec)
    parser_spec.loader.exec_module(parser_module)
    PlanContractError = parser_module.PlanContractError
    parse_plan_files = parser_module.parse_plan_files
    resolve_plan_source = parser_module.resolve_plan_source


SCHEMA_VERSION = 1
DEFAULT_LIMIT = 25
MAX_LIMIT = 100
MAX_EXCERPT_BYTES = 64 * 1024
MAX_METADATA_BYTES = 64 * 1024
MAX_TEXT = 240
MAX_ITEMS = 16
ROUTE_RE = re.compile(r"roadmap_route:\s*(explicit-roadmap|roadmap|log-only)", re.I)
SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
ACCEPTANCE_RE = re.compile(r"^\s*(?:[-*+]\s+)?acceptance\s*[:：]\s*(.*)$", re.I | re.M)
ACCEPTANCE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
ARTIFACTS = (
    "00_spec.md", "20_survey.md", "30_plan.html", "30_plan.md", "40_progress.md", "05_log.md",
    "checkpoint.md", "80_review.md", "90_verification.md", "roadmap.html",
    "roadmap-snapshot.json",
)


class ContextError(ValueError):
    """Explicit context is missing, malformed, or unsafe."""


def _compact(value: object, limit: int = MAX_TEXT) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _absolute(value: str | Path) -> Path:
    if "\x00" in str(value):
        raise ContextError("NUL is not allowed in paths")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    if ".." in path.parts:
        raise ContextError(f"path traversal is not allowed: {value}")
    return path


def _root(value: str | Path) -> tuple[Path, Path]:
    lexical = _absolute(value)
    if lexical.is_symlink():
        raise ContextError(f"memory root must not be a symlink: {lexical}")
    try:
        resolved = lexical.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ContextError(f"memory root is unavailable: {lexical}") from exc
    if not resolved.is_dir():
        raise ContextError(f"memory root is not a directory: {lexical}")
    return lexical, resolved


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _reject_symlinks(path: Path, lexical_root: Path, resolved_root: Path) -> None:
    for base in (lexical_root, resolved_root):
        try:
            relative = path.relative_to(base)
        except ValueError:
            continue
        probe = base
        for part in relative.parts:
            probe /= part
            if probe.is_symlink():
                raise ContextError(f"symlink task path is not allowed: {probe}")


def _task(value: str | Path, roots: Sequence[tuple[Path, Path]]) -> tuple[Path, tuple[Path, Path]]:
    lexical = _absolute(value)
    if lexical.is_symlink():
        raise ContextError(f"task path must not be a symlink: {lexical}")
    try:
        resolved = lexical.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ContextError(f"task path is unavailable: {lexical}") from exc
    if not resolved.is_dir():
        raise ContextError(f"task path is not a directory: {lexical}")
    matches = [
        root for root in roots
        if _inside(resolved, root[1]) and (_inside(lexical, root[0]) or _inside(lexical, root[1]))
    ]
    if not matches:
        raise ContextError(f"task path is outside every explicit memory root: {resolved}")
    selected = matches[0]
    if resolved == selected[1]:
        raise ContextError(f"task path must name a child task directory: {resolved}")
    _reject_symlinks(lexical, selected[0], selected[1])
    _reject_symlinks(resolved, selected[1], selected[1])
    return resolved, selected


def _child(directory: Path, name: str) -> Path | None:
    path = directory / name
    if path.is_symlink():
        raise ContextError(f"symlink artifact is not allowed: {path}")
    if not path.exists():
        return None
    if not path.is_file():
        raise ContextError(f"artifact is not a regular file: {path}")
    return path


def _excerpt(path: Path) -> str:
    size = path.stat().st_size
    with path.open("rb") as stream:
        if size <= MAX_EXCERPT_BYTES:
            data = stream.read(MAX_EXCERPT_BYTES)
        else:
            half = MAX_EXCERPT_BYTES // 2
            data = stream.read(half) + b"\n...[excerpt truncated]...\n"
            stream.seek(size - half)
            data += stream.read(half)
    return data.decode("utf-8", errors="replace")


def _route(task: Path) -> str:
    path = _child(task, "05_log.md")
    if path is None:
        return "unknown"
    found = ROUTE_RE.findall(_excerpt(path))
    return found[-1].lower() if found else "unknown"


def _metadata(task: Path) -> dict[str, Any]:
    path = _child(task, "task-meta.json")
    if path is None:
        return {"taskId": task.name, "metadataState": "missing"}
    if path.stat().st_size > MAX_METADATA_BYTES:
        return {"taskId": task.name, "metadataState": "invalid", "metadataError": "too_large"}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {"taskId": task.name, "metadataState": "invalid", "metadataError": _compact(exc)}
    if not isinstance(value, dict):
        return {"taskId": task.name, "metadataState": "invalid", "metadataError": "root_not_object"}
    task_id = value.get("task_id", task.name)
    if not isinstance(task_id, str) or not SAFE_ID_RE.fullmatch(task_id):
        return {"taskId": task.name, "metadataState": "invalid", "metadataError": "task_id_invalid"}
    result: dict[str, Any] = {"taskId": task_id, "metadataState": "valid"}
    for source, target in (("task_title", "taskTitle"), ("task_state", "taskState")):
        if isinstance(value.get(source), str):
            result[target] = _compact(value[source])
    return result


def _refs(task: Path) -> dict[str, dict[str, Any]]:
    html_present = (task / "30_plan.html").exists() or (task / "30_plan.html").is_symlink()
    refs: dict[str, dict[str, Any]] = {}
    for name in ARTIFACTS:
        if html_present and name == "30_plan.md":
            # A legacy sibling is not part of the HTML source boundary.
            refs[name] = {"path": str(task / name), "exists": False}
            continue
        refs[name] = {"path": str(task / name), "exists": _child(task, name) is not None}
    return refs


def _raw(task: dict[str, Any]) -> tuple[int, int, bool, list[str]]:
    steps = task.get("steps")
    if not isinstance(steps, list):
        return 0, 0, False, []
    valid = [step for step in steps if isinstance(step, dict)]
    done = sum(step.get("complete") is True for step in valid)
    incomplete = [_compact(step.get("label", "")) for step in valid if step.get("complete") is not True]
    return done, len(valid), bool(valid) and done == len(valid), [item for item in incomplete if item]


def _status(task: dict[str, Any]) -> str:
    reported = str(task.get("status", "planned"))
    done, _, complete, _ = _raw(task)
    if reported == "blocked":
        return "blocked"
    if complete:
        return "complete"
    return "in-progress" if reported == "in-progress" or done else "planned"


def _dependencies(tasks: list[dict[str, Any]], edges: object) -> tuple[list[str], dict[str, list[dict[str, str]]]]:
    by_id = {str(task.get("number")): task for task in tasks}
    unresolved: dict[str, list[dict[str, str]]] = {task_id: [] for task_id in by_id}
    if not isinstance(edges, list):
        raise ContextError("plan dependency edges are invalid")
    for edge in edges:
        if not isinstance(edge, dict) or edge.get("from") not in by_id or edge.get("to") not in by_id:
            raise ContextError("plan dependency edge references an unknown task")
        source, target = edge["from"], edge["to"]
        source_status = _status(by_id[source])
        if source_status != "complete":
            unresolved[target].append({"taskId": source, "status": source_status})
    frontier = [
        str(task.get("number")) for task in tasks
        if _status(task) not in {"complete", "blocked"} and not unresolved[str(task.get("number"))]
    ]
    return frontier, unresolved


def _parse(task: Path) -> dict[str, Any] | None:
    html = _child(task, "30_plan.html") if (task / "30_plan.html").exists() or (task / "30_plan.html").is_symlink() else None
    md = _child(task, "30_plan.md") if html is None else None
    if html is None and md is None:
        return None
    try:
        return resolve_plan_source(task)
    except (OSError, UnicodeError, PlanContractError, TypeError, ValueError) as exc:
        raise ContextError(f"plan contract is invalid: {_compact(exc)}") from exc


def _section(text: str, names: Sequence[str]) -> str:
    wanted = {name.casefold() for name in names}
    headings = list(re.finditer(r"^(#{2,6})\s+(.+?)\s*$", text, re.M))
    for index, heading in enumerate(headings):
        if heading.group(2).strip().casefold() not in wanted:
            continue
        level = len(heading.group(1))
        end = next((item.start() for item in headings[index + 1:] if len(item.group(1)) <= level), len(text))
        return _compact(text[heading.end():end])
    return ""


def _acceptance(model: dict[str, Any]) -> list[str]:
    if model.get("sourceKind") == "html":
        values: list[str] = []
        for task in model.get("tasks", []):
            if not isinstance(task, dict):
                continue
            ids = task.get("acceptanceIds", [])
            if isinstance(ids, list):
                for value in ids:
                    if isinstance(value, str) and value not in values:
                        values.append(value)
        return values
    values: list[str] = []
    for task in model.get("tasks", []):
        if not isinstance(task, dict):
            continue
        for match in ACCEPTANCE_RE.finditer(str(task.get("body", ""))):
            parts = [part.strip() for part in match.group(1).split(",")]
            if not parts or any(not ACCEPTANCE_ID_RE.fullmatch(part) for part in parts):
                continue
            for value in parts:
                if value not in values:
                    values.append(value)
    return values


def _detail(task: dict[str, Any]) -> dict[str, Any]:
    done, total, complete, incomplete = _raw(task)
    source = task.get("source") if isinstance(task.get("source"), dict) else {}
    steps = task.get("steps") if isinstance(task.get("steps"), list) else []
    return {
        "id": str(task.get("number", "")), "title": _compact(task.get("title", "")),
        "purpose": _compact(task.get("purpose", "")),
        "targets": [_compact(item) for item in task.get("targets", [])[:MAX_ITEMS]],
        "implementation": [_compact(item) for item in task.get("implementation", [])[:MAX_ITEMS]],
        "outputs": [_compact(item) for item in task.get("outputs", [])[:MAX_ITEMS]],
        "verification": [_compact(item) for item in task.get("verification", [])[:MAX_ITEMS]],
        "blockedBy": _compact(task.get("blockedBy", "")), "status": _status(task),
        "parserStatus": str(task.get("status", "planned")),
        "rawCompletion": {"done": done, "total": total, "complete": complete},
        "steps": [{"label": _compact(item.get("label", "")), "complete": item.get("complete") is True} for item in steps[:MAX_ITEMS] if isinstance(item, dict)],
        "incompleteSteps": incomplete[:MAX_ITEMS],
        "source": {"path": str(source.get("file", "")), "lineStart": source.get("lineStart"), "lineEnd": source.get("lineEnd")},
        "acceptanceIds": [value for value in task.get("acceptanceIds", []) if isinstance(value, str)],
        "requiredSources": [value for value in task.get("requiredSources", []) if isinstance(value, str)],
        "sourceRefs": [value for value in task.get("sourceRefs", []) if isinstance(value, str)],
        "uiPreviewBlocks": task.get("uiPreviewBlocks", []) if isinstance(task.get("uiPreviewBlocks"), list) else [],
    }


def _bounded(values: Sequence[Any]) -> tuple[list[Any], int, bool]:
    items = list(values)
    return items[:MAX_ITEMS], len(items), len(items) > MAX_ITEMS


def _bounded_map(values: dict[str, Any]) -> tuple[dict[str, Any], int, bool]:
    items = list(values.items())
    return dict(items[:MAX_ITEMS]), len(items), len(items) > MAX_ITEMS


def _list_entry(task: Path) -> dict[str, Any]:
    refs, metadata = _refs(task), _metadata(task)
    html_exists = refs["30_plan.html"]["exists"]
    plan_exists = html_exists or refs["30_plan.md"]["exists"]
    plan_source = "30_plan.html" if html_exists else ("30_plan.md" if refs["30_plan.md"]["exists"] else "")
    route = _route(task)
    result: dict[str, Any] = {
        "taskId": metadata["taskId"], "taskPath": str(task),
        "taskTitle": metadata.get("taskTitle", task.name), "taskState": metadata.get("taskState", "unknown"),
        "metadataState": metadata["metadataState"], "route": route,
        "state": "legacy-log-only" if route == "log-only" and not plan_exists else ("available" if plan_exists else "plan-missing"),
        "planExists": plan_exists, "planSource": plan_source, "htmlPath": refs["roadmap.html"]["path"],
        "htmlExists": refs["roadmap.html"]["exists"], "snapshotExists": refs["roadmap-snapshot.json"]["exists"],
    }
    if metadata.get("metadataError"):
        result["metadataError"] = metadata["metadataError"]
    return result


def list_context(memory_roots: Sequence[str | Path], *, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    """List only immediate task metadata and known artifact paths."""
    if not memory_roots:
        raise ContextError("at least one explicit --memory-root is required")
    if limit < 1:
        raise ContextError("limit must be at least 1")
    requested, limit = limit, min(limit, MAX_LIMIT)
    roots, candidates, seen = [], [], set()
    for value in memory_roots:
        root = _root(value)
        if root[1] in seen:
            continue
        seen.add(root[1]); roots.append(root)
        try:
            entries = sorted(root[1].iterdir(), key=lambda item: item.name)
        except (OSError, RuntimeError) as exc:
            raise ContextError(f"cannot list memory root: {root[1]}") from exc
        for entry in entries:
            if entry.name.startswith("."):
                continue
            if entry.is_symlink():
                raise ContextError(f"symlink task entry is not allowed: {entry}")
            if entry.is_dir():
                candidates.append(entry)
    total = len(candidates)
    rows = [_list_entry(entry) for entry in candidates[:limit]]
    return {
        "schemaVersion": SCHEMA_VERSION, "command": "list", "status": "ok",
        "memoryRoots": [str(root[1]) for root in roots],
        "selection": {"strategy": "explicit roots; immediate child directories; lexical order", "noLatestAutoSelection": True, "requestedLimit": requested, "limit": limit, "candidateCount": total, "returnedCount": len(rows), "truncated": len(rows) < total},
        "tasks": rows,
    }


def brief_context(task_path: str | Path, *, memory_roots: Sequence[str | Path] | None = None, task_id: str | None = None) -> dict[str, Any]:
    """Brief one explicitly named task, using the canonical plan parser."""
    if memory_roots:
        roots = [_root(value) for value in memory_roots]
    else:
        lexical = _absolute(task_path)
        try:
            roots = [(lexical.parent, lexical.parent.resolve(strict=True))]
        except (OSError, RuntimeError) as exc:
            raise ContextError(f"task memory root is unavailable: {lexical.parent}") from exc
    task, selected_root = _task(task_path, roots)
    refs, metadata, model = _refs(task), _metadata(task), _parse(task)
    result: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION, "command": "brief", "taskId": metadata["taskId"], "taskPath": str(task),
        "taskTitle": metadata.get("taskTitle", task.name), "taskState": metadata.get("taskState", "unknown"),
        "metadataState": metadata["metadataState"], "route": _route(task),
        "htmlPath": refs["roadmap.html"]["path"], "htmlExists": refs["roadmap.html"]["exists"],
        "planSource": "30_plan.html" if refs["30_plan.html"]["exists"] else ("30_plan.md" if refs["30_plan.md"]["exists"] else ""),
        "sourceRefs": {name: refs[name] for name in ARTIFACTS if name not in {"roadmap.html", "roadmap-snapshot.json"}},
        "limitations": "briefは要約と正本参照を返すだけで、要件・制約全文の充足を保証しません。",
    }
    if metadata.get("metadataError"):
        result["metadataError"] = metadata["metadataError"]
    if model is None:
        result.update({"state": "legacy-log-only" if result["route"] == "log-only" else "plan-missing", "taskIds": [], "taskCount": 0, "taskIdsTruncated": False, "frontierTaskIds": [], "frontierCount": 0, "frontierTaskIdsTruncated": False, "unresolvedDependencies": {}, "unresolvedDependencyTaskCount": 0, "unresolvedDependencyCount": 0, "unresolvedDependenciesTruncated": False, "selection": {"explicitTaskPath": True, "selectedTaskId": None}, "selectedTask": None, "goal": "", "constraints": "", "acceptanceIds": [], "acceptanceIdCount": 0, "acceptanceIdsTruncated": False, "nextReads": []})
        return result
    tasks = model.get("tasks")
    if not isinstance(tasks, list):
        raise ContextError("parsed plan tasks are invalid")
    task_ids, task_count, task_ids_truncated = _bounded(str(task.get("number", "")) for task in tasks)
    result.update({"taskIds": task_ids, "taskCount": task_count, "taskIdsTruncated": task_ids_truncated})
    result["parser"] = {
        "version": model.get("parserVersion", ""),
        "sourceHash": model.get("sourceHash", ""),
        "planSourceRawSha256": model.get("planSourceRawSha256", ""),
    }
    if model.get("diagnostics"):
        diagnostics, diagnostic_count, diagnostics_truncated = _bounded(model["diagnostics"])
        result.update({"state": "needs-plan-repair", "frontierTaskIds": [], "frontierCount": 0, "frontierTaskIdsTruncated": False, "unresolvedDependencies": {}, "unresolvedDependencyTaskCount": 0, "unresolvedDependencyCount": 0, "unresolvedDependenciesTruncated": False, "diagnostics": diagnostics, "diagnosticCount": diagnostic_count, "diagnosticsTruncated": diagnostics_truncated})
        result["selection"] = {"explicitTaskPath": True, "mode": "plan repair required", "selectedTaskId": None}
        result["selectedTask"] = None
        return result
    frontier, unresolved = _dependencies(tasks, model.get("edges", []))
    by_id = {str(task.get("number")): task for task in tasks}
    active = [str(task.get("number")) for task in tasks if _status(task) == "in-progress" and str(task.get("number")) in frontier]
    if task_id is not None:
        if task_id not in by_id:
            raise ContextError(f"task id is not present in selected plan: {task_id}")
        chosen, mode = task_id, "explicit task id"
    else:
        chosen = (active or frontier)[0] if (active or frontier) else None
        mode = "first runnable task within explicit plan path" if chosen else "no runnable frontier"
    selected = by_id[chosen] if chosen else None
    spec_path = _child(task, "00_spec.md")
    spec = _excerpt(spec_path) if spec_path else ""
    selected_detail = _detail(selected) if selected else None
    frontier_ids, frontier_count, frontier_truncated = _bounded(frontier)
    unresolved_values = {task_id: dependencies for task_id, dependencies in unresolved.items() if dependencies}
    unresolved_items, unresolved_count, unresolved_truncated = _bounded_map(unresolved_values)
    dependency_item_count = sum(len(dependencies) for dependencies in unresolved_values.values())
    dependency_items_truncated = any(len(dependencies) > MAX_ITEMS for dependencies in unresolved_values.values())
    unresolved_items = {task_id: dependencies[:MAX_ITEMS] for task_id, dependencies in unresolved_items.items()}
    acceptance_ids, acceptance_count, acceptance_truncated = _bounded(_acceptance(model))
    result.update({
        "state": "ready", "frontierTaskIds": frontier_ids, "frontierCount": frontier_count, "frontierTaskIdsTruncated": frontier_truncated,
        "unresolvedDependencies": unresolved_items, "unresolvedDependencyTaskCount": unresolved_count, "unresolvedDependencyCount": dependency_item_count, "unresolvedDependenciesTruncated": unresolved_truncated or dependency_items_truncated,
        "progress": {"rawCompleteTasks": sum(_raw(task)[2] for task in tasks), "taskCount": len(tasks), "rawComplete": bool(tasks) and all(_raw(task)[2] for task in tasks), "reportedByParser": {key: model.get("progress", {}).get(key) for key in ("done", "total", "globalComplete")}},
        "selection": {"explicitTaskPath": True, "mode": mode, "selectedTaskId": chosen, "nextTaskId": frontier[0] if frontier else None},
        "selectedTask": selected_detail,
        "goal": _section(spec, ("Goal", "目的", "概要", "背景・目的")) or (_compact(selected.get("purpose", "")) if selected else ""),
        "constraints": _section(spec, ("制約事項", "制約")), "acceptanceIds": acceptance_ids, "acceptanceIdCount": acceptance_count, "acceptanceIdsTruncated": acceptance_truncated,
        "nextReads": [{"name": name, "reason": reason} for name, reason in (("00_spec.md", "goal・scope・制約"), ("30_plan.html" if refs["30_plan.html"]["exists"] else "30_plan.md", "Taskの正本"), ("40_progress.md", "進捗の補足"), ("checkpoint.md", "acceptanceの正本"), ("80_review.md", "reviewと残課題"), ("90_verification.md", "検証結果")) if refs[name]["exists"]],
    })
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only explicit task context helper")
    sub = parser.add_subparsers(dest="command", required=True)
    list_parser = sub.add_parser("list", help="list immediate task metadata under explicit roots")
    list_parser.add_argument("--memory-root", action="append", required=True, dest="memory_roots")
    list_parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    brief_parser = sub.add_parser("brief", help="brief one explicitly named task path; summary/ref only")
    brief_parser.add_argument("task_path")
    brief_parser.add_argument("--memory-root", action="append", default=[], dest="memory_roots")
    brief_parser.add_argument("--task-id")
    args = parser.parse_args(argv)
    try:
        result = list_context(args.memory_roots, limit=args.limit) if args.command == "list" else brief_context(args.task_path, memory_roots=args.memory_roots, task_id=args.task_id)
    except (ContextError, OSError) as exc:
        print(json.dumps({"schemaVersion": SCHEMA_VERSION, "status": "error", "error": _compact(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
