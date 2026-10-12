#!/usr/bin/env python3
"""Store and restore a bounded, session-scoped handover artifact.

Only task-meta.json and the explicit short-state schema are read. Transcripts,
task logs, databases, and personal notes are intentionally outside this core.
"""
from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = 1
MARKER_PREFIX = "<!-- codex-session-handover:"
MARKER_SUFFIX = " -->"
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
TASK_STATES = {"active", "waiting", "verifying", "completed", "archived"}
FINGERPRINT_KEYS = ("diff", "dependencies", "execution", "plan", "failure")
GATE_STATES = {"pending", "passed", "failed", "blocked", "unknown", "not_run"}
EVIDENCE_STATES = {"passed", "failed", "unknown", "not_run"}
REQUIRED_META = {
    "schema_version", "task_id", "task_title", "project_path", "worktree_path",
    "task_state", "code_change", "created_at", "updated_at",
}
OPTIONAL_META = {"session_id", "thread_id", "approval_state"}
LEGACY_READONLY_META = {"project", "run_id", "title", "workspace_root"}
LEGACY_META_MAX_BYTES = 4096
STATE_KEYS = {
    "schema_version", "objective", "next_acceptance", "plan", "dependencies",
    "unanswered_questions", "required_gates", "evidence", "next_action",
}
PLAN_KEYS = {"path", "anchor", "version", "sha256"}
GATE_KEYS = {"name", "status", "approval_ref", "evidence_refs"}
EVIDENCE_KEYS = {"name", "status", "command", "result", "fingerprints"}
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_STATE_BYTES = 256 * 1024


class HandoverError(Exception):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


def _init_argument_error(message: str) -> None:
    raise HandoverError("invalid_arguments", message)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(data: str | bytes) -> str:
    raw = data.encode("utf-8") if isinstance(data, str) else data
    return hashlib.sha256(raw).hexdigest()


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _safe_id(value: Any, name: str, *, optional: bool = True) -> str | None:
    if value is None or value == "":
        if optional:
            return None
        raise HandoverError("missing_identity", name)
    if (
        not isinstance(value, str)
        or not SAFE_ID.fullmatch(value)
        or value.lower() in {".", "..", "unknown", "null"}
    ):
        raise HandoverError("unsafe_identity", name)
    return value


def _require_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HandoverError("invalid_schema", name)
    return value


def _require_text_list(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise HandoverError("invalid_schema", name)
    return value


def _read_json(path: Path) -> dict[str, Any]:
    _regular_leaf(path, allow_missing=False)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = -1
    try:
        fd = os.open(path, flags)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_JSON_BYTES:
            raise HandoverError("non_regular_file", str(path))
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            fd = -1
            value = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise HandoverError("invalid_json", str(path)) from error
    finally:
        if fd >= 0:
            os.close(fd)
    if not isinstance(value, dict):
        raise HandoverError("invalid_json", str(path))
    return value


def _read_stdin_json() -> Any:
    stream = getattr(sys.stdin, "buffer", sys.stdin)
    raw = stream.read(MAX_JSON_BYTES + 1)
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    if len(raw) > MAX_JSON_BYTES:
        raise ValueError("stdin JSON is too large")
    return json.loads(raw.decode("utf-8"))


class _SectionLocator(HTMLParser):
    def __init__(self, source: str, anchor: str) -> None:
        super().__init__(convert_charrefs=False)
        self.source = source
        self.anchor = anchor.lstrip("#")
        self.line_offsets = [0]
        for match in re.finditer("\n", source):
            self.line_offsets.append(match.end())
        self.start: int | None = None
        self.end: int | None = None
        self.depth = 0
        self.matches = 0

    def _offset(self) -> int:
        line, column = self.getpos()
        return self.line_offsets[line - 1] + column

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        is_target = dict(attrs).get("id") == self.anchor
        if is_target:
            self.matches += 1
        if tag.lower() != "section":
            return
        if self.start is not None and self.end is None:
            self.depth += 1
        elif is_target:
            self.start = self._offset()
            self.depth = 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "section" or self.start is None or self.end is not None:
            return
        self.depth -= 1
        if self.depth == 0:
            close = self.source.find(">", self._offset())
            if close < 0:
                raise HandoverError("invalid_plan_html", self.anchor)
            self.end = close + 1


def extract_section(path: Path, anchor: str) -> str:
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise HandoverError("invalid_plan_path", str(path))
    try:
        if path.stat().st_size > 10 * 1024 * 1024:
            raise HandoverError("invalid_plan_path", str(path))
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise HandoverError("invalid_plan_path", str(path)) from error
    locator = _SectionLocator(source, anchor)
    try:
        locator.feed(source)
        locator.close()
    except HandoverError:
        raise
    except Exception as error:
        raise HandoverError("invalid_plan_html", anchor) from error
    if locator.matches != 1 or locator.start is None or locator.end is None:
        raise HandoverError("plan_anchor_not_unique", anchor)
    return source[locator.start:locator.end]


def plan_section_hash(path: Path, anchor: str) -> str:
    return _sha(extract_section(path, anchor))


def plan_section_version(path: Path, anchor: str) -> str | None:
    section = extract_section(path, anchor)
    reader = _OpeningTag()
    reader.feed(section)
    if reader.tag != "section":
        raise HandoverError("invalid_plan_html", anchor)
    return dict(reader.attrs).get("data-plan-version")


class _OpeningTag(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.tag: str | None = None
        self.attrs: list[tuple[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.tag is None:
            self.tag = tag.lower()
            self.attrs = attrs


def _exact_keys(value: dict[str, Any], expected: set[str], name: str) -> None:
    if set(value) != expected:
        raise HandoverError("invalid_short_state", name)


def _plan_path_allowed(path: Path, roots: list[Path]) -> bool:
    if not path.is_absolute() or path.is_symlink():
        return False
    try:
        real = path.resolve(strict=True)
    except OSError:
        return False
    return any(_within(real, root) for root in roots)


def validate_state(
    value: Any, *, check_plan: bool, allowed_plan_roots: list[Path] | None = None
) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or type(value.get("schema_version")) is not int
        or value["schema_version"] != SCHEMA_VERSION
    ):
        raise HandoverError("invalid_short_state", "schema_version")
    try:
        if len(_json(value).encode("utf-8")) > MAX_STATE_BYTES:
            raise HandoverError("short_state_too_large")
    except (TypeError, ValueError) as error:
        raise HandoverError("invalid_short_state", "json") from error
    _exact_keys(value, STATE_KEYS, "keys")
    state = dict(value)
    for key in ("objective", "next_acceptance", "next_action"):
        _require_text(state.get(key), key)
    for key in ("dependencies", "unanswered_questions"):
        _require_text_list(state.get(key), key)
    plan = state.get("plan")
    if not isinstance(plan, dict):
        raise HandoverError("invalid_short_state", "plan")
    _exact_keys(plan, PLAN_KEYS, "plan.keys")
    plan_path = Path(_require_text(plan.get("path"), "plan.path"))
    anchor = _require_text(plan.get("anchor"), "plan.anchor")
    _require_text(plan.get("version"), "plan.version")
    expected_hash = _require_text(plan.get("sha256"), "plan.sha256")
    if not SHA256.fullmatch(expected_hash):
        raise HandoverError("invalid_short_state", "plan.sha256")
    if check_plan:
        if not allowed_plan_roots or not _plan_path_allowed(plan_path, allowed_plan_roots):
            raise HandoverError("plan_path_not_allowed", str(plan_path))
        if plan_section_version(plan_path, anchor) != plan["version"]:
            raise HandoverError("plan_version_mismatch", str(plan_path))
        if plan_section_hash(plan_path, anchor) != expected_hash:
            raise HandoverError("plan_hash_mismatch", str(plan_path))
    gates = state.get("required_gates")
    if not isinstance(gates, list):
        raise HandoverError("invalid_short_state", "required_gates")
    for index, gate in enumerate(gates):
        if not isinstance(gate, dict):
            raise HandoverError("invalid_short_state", f"required_gates[{index}]")
        _exact_keys(gate, GATE_KEYS, f"required_gates[{index}].keys")
        _require_text(gate.get("name"), f"required_gates[{index}].name")
        if gate.get("status") not in GATE_STATES:
            raise HandoverError("invalid_short_state", f"required_gates[{index}].status")
        if gate.get("approval_ref") is not None and not isinstance(gate["approval_ref"], str):
            raise HandoverError("invalid_short_state", f"required_gates[{index}].approval_ref")
        _require_text_list(gate.get("evidence_refs"), f"required_gates[{index}].evidence_refs")
    gate_names = [gate["name"] for gate in gates]
    if len(set(gate_names)) != len(gate_names):
        raise HandoverError("invalid_short_state", "required_gates.duplicate_name")
    evidence = state.get("evidence")
    if not isinstance(evidence, list):
        raise HandoverError("invalid_short_state", "evidence")
    for index, item in enumerate(evidence):
        if not isinstance(item, dict):
            raise HandoverError("invalid_short_state", f"evidence[{index}]")
        _exact_keys(item, EVIDENCE_KEYS, f"evidence[{index}].keys")
        for key in ("name", "command", "result"):
            _require_text(item.get(key), f"evidence[{index}].{key}")
        if item.get("status") not in EVIDENCE_STATES:
            raise HandoverError("invalid_short_state", f"evidence[{index}].status")
        fingerprints = item.get("fingerprints")
        if not isinstance(fingerprints, dict) or set(fingerprints) != set(FINGERPRINT_KEYS):
            raise HandoverError("invalid_short_state", f"evidence[{index}].fingerprints")
        for key in FINGERPRINT_KEYS:
            if fingerprints[key] is not None and (
                not isinstance(fingerprints[key], str) or not fingerprints[key].strip()
            ):
                raise HandoverError("invalid_short_state", f"evidence[{index}].fingerprints.{key}")
    evidence_names = [item["name"] for item in evidence]
    if len(set(evidence_names)) != len(evidence_names):
        raise HandoverError("invalid_short_state", "evidence.duplicate_name")
    return state


def _validate_task_meta(
    value: dict[str, Any], path: Path,
    expected_project: Path | None = None, expected_worktree: Path | None = None,
) -> dict[str, Any]:
    if REQUIRED_META - set(value) or set(value) - REQUIRED_META - OPTIONAL_META - LEGACY_READONLY_META:
        raise HandoverError("invalid_task_metadata", str(path))
    for key in LEGACY_READONLY_META & set(value):
        legacy_value = value[key]
        try:
            legacy_bytes = legacy_value.encode("utf-8") if isinstance(legacy_value, str) else b""
        except UnicodeEncodeError as error:
            raise HandoverError("invalid_task_metadata", f"{path}:{key}") from error
        if not isinstance(legacy_value, str) or not legacy_value.strip() or "\x00" in legacy_value or len(legacy_bytes) > LEGACY_META_MAX_BYTES:
            raise HandoverError("invalid_task_metadata", f"{path}:{key}")
    if (
        type(value.get("schema_version")) is not int
        or value["schema_version"] != SCHEMA_VERSION
        or value.get("task_state") not in TASK_STATES
    ):
        raise HandoverError("invalid_task_metadata", str(path))
    for key in ("task_id", "task_title", "created_at", "updated_at"):
        _require_text(value.get(key), f"{path}:{key}")
    if not isinstance(value.get("code_change"), bool):
        raise HandoverError("invalid_task_metadata", f"{path}:code_change")
    for key in ("session_id", "thread_id"):
        if key in value and value[key] is not None:
            _safe_id(value[key], f"{path}:{key}")
    if value.get("approval_state") is not None and not isinstance(value["approval_state"], str):
        raise HandoverError("invalid_task_metadata", f"{path}:approval_state")
    project = Path(_require_text(value.get("project_path"), f"{path}:project_path"))
    worktree = Path(_require_text(value.get("worktree_path"), f"{path}:worktree_path"))
    if not project.is_absolute() or not worktree.is_absolute():
        raise HandoverError("invalid_task_metadata", f"{path}:paths")
    try:
        project_real = project.resolve(strict=True)
        worktree_real = worktree.resolve(strict=True)
    except OSError as error:
        raise HandoverError("invalid_task_metadata", f"{path}:paths") from error
    if (
        (expected_project is not None and project_real != expected_project)
        or (expected_worktree is not None and worktree_real != expected_worktree)
    ):
        raise HandoverError("context_mismatch", str(path))
    result = dict(value)
    result["project_path"] = str(project_real)
    result["worktree_path"] = str(worktree_real)
    return result


def _runtime_home(runtime: str) -> Path:
    variable = "CODEX_HOME" if runtime == "codex" else "CLAUDE_HOME"
    default = ".codex" if runtime == "codex" else ".claude"
    return Path(os.environ.get(variable) or Path.home() / default)


def _default_memory_roots(cwd: Path, runtime: str) -> list[Path]:
    configured = os.environ.get("SESSION_HANDOVER_TASK_MEMORY_ROOT")
    runtime_home = _runtime_home(runtime)
    if runtime_home.exists():
        runtime_home = runtime_home.resolve(strict=True)
    candidates = [
        Path(configured) if configured else None,
        runtime_home / ".local" / "memory",
        cwd / ".local" / "memory",
        cwd / "memory",
    ]
    roots: list[Path] = []
    seen: set[Path] = set()
    for root in candidates:
        if root is None or not root.exists():
            continue
        real = _strict_dir(root, "memory_root_escape")
        if real not in seen:
            seen.add(real)
            roots.append(real)
    return roots


def _strict_dir(path: Path, code: str) -> Path:
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise HandoverError(code, str(path))
    try:
        real = path.resolve(strict=True)
    except OSError as error:
        raise HandoverError(code, str(path)) from error
    return real


def resolve_task(
    cwd: Path,
    session_id: str | None,
    thread_id: str | None,
    *,
    runtime: str,
    expected_project: Path,
    expected_worktree: Path,
    explicit_memory_base: Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    cwd = cwd.resolve(strict=True)
    session_id = _safe_id(session_id, "session_id")
    thread_id = _safe_id(thread_id, "thread_id")
    if session_id is None and thread_id is None:
        raise HandoverError("missing_identity")
    roots = [explicit_memory_base] if explicit_memory_base is not None else _default_memory_roots(cwd, runtime)
    if not roots:
        raise HandoverError("missing_memory_root")
    matches: list[tuple[Path, dict[str, Any]]] = []
    for root in roots:
        if root is None or not root.exists():
            continue
        real_root = _strict_dir(root, "memory_root_escape")
        for child in sorted(real_root.iterdir(), key=lambda item: item.name):
            if child.is_symlink():
                raise HandoverError("task_path_escape", str(child))
            if not child.is_dir():
                continue
            real_child = child.resolve(strict=True)
            if not _within(real_child, real_root):
                raise HandoverError("task_path_escape", str(child))
            meta_path = child / "task-meta.json"
            if not meta_path.exists():
                continue
            if meta_path.is_symlink() or meta_path.resolve(strict=True).parent != real_child:
                raise HandoverError("task_metadata_escape", str(meta_path))
            raw = _read_json(meta_path)
            if session_id is not None:
                matched = raw.get("session_id") == session_id and (
                    thread_id is None or raw.get("thread_id") == thread_id
                )
            else:
                matched = raw.get("thread_id") == thread_id
            if not matched:
                continue
            meta = _validate_task_meta(raw, meta_path, expected_project, expected_worktree)
            matches.append((real_child, meta))
    if not matches:
        raise HandoverError("task_not_found")
    if len(matches) != 1:
        raise HandoverError("ambiguous_task")
    return matches[0]


def _local_root(cwd: Path, override: str | None = None) -> Path:
    raw = Path(override or os.environ.get("SESSION_HANDOVER_MEMORY_DIR", "") or cwd / ".local")
    if not raw.is_absolute() and ".." in raw.parts:
        raise HandoverError("local_root_escape", str(raw))
    root = Path(os.path.abspath(raw if raw.is_absolute() else cwd / raw))
    try:
        relative = root.relative_to(cwd)
    except ValueError as error:
        raise HandoverError("local_root_escape", str(root)) from error
    current = cwd
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise HandoverError("local_root_symlink", str(current))
    if root.exists() and (not root.is_dir() or root.resolve(strict=True) != root):
        raise HandoverError("local_root_escape", str(root))
    return root


def _private_dir(path: Path, trusted_root: Path, *, chmod_existing_final: bool = True) -> None:
    try:
        relative = path.relative_to(trusted_root)
    except ValueError as error:
        raise HandoverError("path_escape", str(path)) from error
    if any(part in {"", ".", ".."} for part in relative.parts):
        raise HandoverError("path_escape", str(path))
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        current_fd = os.open(trusted_root, flags)
    except OSError as error:
        raise HandoverError("path_not_directory", str(trusted_root)) from error
    try:
        for index, part in enumerate(relative.parts):
            created = False
            try:
                os.mkdir(part, mode=0o700, dir_fd=current_fd)
                created = True
            except FileExistsError:
                pass
            try:
                next_fd = os.open(part, flags, dir_fd=current_fd)
            except OSError as error:
                raise HandoverError("path_symlink", str(path)) from error
            if created or (chmod_existing_final and index == len(relative.parts) - 1):
                os.fchmod(next_fd, 0o700)
            os.close(current_fd)
            current_fd = next_fd
    finally:
        os.close(current_fd)


def _regular_leaf(path: Path, *, allow_missing: bool) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        if allow_missing:
            return False
        raise HandoverError("file_not_found", str(path))
    if stat.S_ISLNK(info.st_mode):
        raise HandoverError("path_symlink", str(path))
    if not stat.S_ISREG(info.st_mode):
        raise HandoverError("non_regular_file", str(path))
    return True


def _atomic_write(path: Path, content: str, local_root: Path) -> None:
    _private_dir(path.parent, local_root)
    _regular_leaf(path, allow_missing=True)
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    directory_fd = os.open(path.parent, directory_flags)
    temp_name = f".{path.name}.{os.getpid()}.{secrets.token_hex(6)}"
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(temp_name, flags, 0o600, dir_fd=directory_fd)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        _regular_leaf(path, allow_missing=True)
        os.rename(temp_name, path.name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        os.chmod(path.name, 0o600, dir_fd=directory_fd, follow_symlinks=False)
        os.fsync(directory_fd)
    finally:
        try:
            os.unlink(temp_name, dir_fd=directory_fd)
        except FileNotFoundError:
            pass
        os.close(directory_fd)


def _atomic_create_at(directory_fd: int, name: str, content: str, display_path: Path) -> None:
    try:
        existing = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        existing = None
    if existing is not None:
        if stat.S_ISLNK(existing.st_mode):
            raise HandoverError("path_symlink", str(display_path))
        if not stat.S_ISREG(existing.st_mode):
            raise HandoverError("non_regular_file", str(display_path))
        raise HandoverError("metadata_exists", str(display_path))
    temp_name = f".{name}.{os.getpid()}.{secrets.token_hex(6)}"
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(temp_name, flags, 0o600, dir_fd=directory_fd)
    published_identity: tuple[int, int] | None = None
    temp_exists = True
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            fd = -1
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), 0o600)
        temp_info = os.stat(temp_name, dir_fd=directory_fd, follow_symlinks=False)
        try:
            os.link(
                temp_name, name, src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd, follow_symlinks=False,
            )
            published_identity = (temp_info.st_dev, temp_info.st_ino)
        except FileExistsError as error:
            raise HandoverError("metadata_exists", str(display_path)) from error
        os.unlink(temp_name, dir_fd=directory_fd)
        temp_exists = False
        os.fsync(directory_fd)
    except Exception:
        if published_identity is not None:
            try:
                current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                if (current.st_dev, current.st_ino) == published_identity:
                    os.unlink(name, dir_fd=directory_fd)
            except OSError:
                pass
        raise
    finally:
        if fd >= 0:
            os.close(fd)
        if temp_exists:
            try:
                os.unlink(temp_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass


def _read_json_at(directory_fd: int, name: str, display_path: Path) -> dict[str, Any]:
    try:
        before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except OSError as error:
        raise HandoverError("invalid_json", str(display_path)) from error
    if stat.S_ISLNK(before.st_mode):
        raise HandoverError("path_symlink", str(display_path))
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_JSON_BYTES:
        raise HandoverError("non_regular_file", str(display_path))
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = -1
    try:
        fd = os.open(name, flags, dir_fd=directory_fd)
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise HandoverError("path_changed", str(display_path))
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            fd = -1
            value = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise HandoverError("invalid_json", str(display_path)) from error
    finally:
        if fd >= 0:
            os.close(fd)
    if not isinstance(value, dict):
        raise HandoverError("invalid_json", str(display_path))
    return value


def _open_directory_at(parent_fd: int, name: str, display_path: Path, *, create: bool) -> tuple[int, bool]:
    created = False
    created_identity: tuple[int, int] | None = None
    if create:
        try:
            os.mkdir(name, 0o700, dir_fd=parent_fd)
            created = True
            info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            created_identity = (info.st_dev, info.st_ino)
        except FileExistsError:
            pass
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(name, flags, dir_fd=parent_fd)
    except OSError as error:
        if created_identity is not None and _same_entry(parent_fd, name, created_identity):
            try:
                os.rmdir(name, dir_fd=parent_fd)
            except OSError:
                pass
        raise HandoverError("task_path_escape", str(display_path)) from error
    if created:
        os.fchmod(fd, 0o700)
    return fd, created


def _open_lock_at(directory_fd: int, name: str, display_path: Path) -> int:
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(name, flags, 0o600, dir_fd=directory_fd)
        os.fchmod(fd, 0o600)
    except FileExistsError:
        try:
            fd = os.open(name, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
        except OSError as error:
            raise HandoverError("lock_open_failed", str(display_path)) from error
    except OSError as error:
        raise HandoverError("lock_open_failed", str(display_path)) from error
    opened = os.fstat(fd)
    if not stat.S_ISREG(opened.st_mode):
        os.close(fd)
        raise HandoverError("non_regular_file", str(display_path))
    try:
        current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except OSError as error:
        os.close(fd)
        raise HandoverError("lock_open_failed", str(display_path)) from error
    if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
        os.close(fd)
        raise HandoverError("lock_changed", str(display_path))
    return fd


def _same_entry(directory_fd: int, name: str, identity: tuple[int, int]) -> bool:
    try:
        info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except OSError:
        return False
    return (info.st_dev, info.st_ino) == identity


def _artifact_digest(record: dict[str, Any], body: str) -> str:
    unsigned = {key: value for key, value in record.items() if key != "artifact_sha256"}
    return _sha(_json(unsigned) + "\n" + body)


def _marker(kind: str, metadata: dict[str, Any], body: str) -> str:
    record = dict(metadata)
    record.update({"kind": kind, "schema_version": SCHEMA_VERSION, "body_sha256": _sha(body)})
    record["artifact_sha256"] = _artifact_digest(record, body)
    encoded = base64.urlsafe_b64encode(_json(record).encode("utf-8")).decode("ascii")
    artifact = f"{MARKER_PREFIX}{encoded}{MARKER_SUFFIX}\n{body}"
    if len(artifact.encode("utf-8")) > MAX_JSON_BYTES:
        raise HandoverError("artifact_too_large", kind)
    return artifact


def _parse_generated_text(content: str, expected_kind: str) -> tuple[dict[str, Any], str]:
    if len(content.encode("utf-8")) > MAX_JSON_BYTES:
        raise HandoverError("artifact_too_large", expected_kind)
    first, separator, body = content.partition("\n")
    if not separator or not first.startswith(MARKER_PREFIX) or not first.endswith(MARKER_SUFFIX):
        raise HandoverError("unknown_generated_format")
    try:
        encoded = first[len(MARKER_PREFIX):-len(MARKER_SUFFIX)]
        metadata = json.loads(base64.urlsafe_b64decode(encoded.encode("ascii")))
    except (ValueError, UnicodeError, json.JSONDecodeError) as error:
        raise HandoverError("unknown_generated_format") from error
    if (
        not isinstance(metadata, dict)
        or metadata.get("kind") != expected_kind
        or type(metadata.get("schema_version")) is not int
        or metadata["schema_version"] != SCHEMA_VERSION
    ):
        raise HandoverError("unknown_generated_format")
    if metadata.get("body_sha256") != _sha(body) or metadata.get("artifact_sha256") != _artifact_digest(metadata, body):
        raise HandoverError("dirty_generated_file")
    return metadata, body


def _parse_generated(path: Path, expected_kind: str) -> tuple[dict[str, Any], str]:
    _regular_leaf(path, allow_missing=False)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except OSError as error:
        raise HandoverError("dirty_generated_file", str(path)) from error
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_JSON_BYTES:
            raise HandoverError("non_regular_file", str(path))
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            fd = -1
            return _parse_generated_text(stream.read(), expected_kind)
    except (OSError, UnicodeError) as error:
        raise HandoverError("dirty_generated_file", str(path)) from error
    finally:
        if fd >= 0:
            os.close(fd)


def _owner(meta: dict[str, Any], runtime: str, session_id: str | None, thread_id: str | None) -> dict[str, Any]:
    return {"runtime": runtime, "session_id": session_id, "thread_id": thread_id, "task_id": meta["task_id"]}


def _same_owner(record: dict[str, Any], owner: dict[str, Any]) -> bool:
    return record.get("owner") == owner


def _canonical_name(session_id: str | None, thread_id: str | None) -> str:
    if session_id is not None:
        return f"{session_id}.md"
    if thread_id is not None:
        return f"thread-{thread_id}.md"
    raise HandoverError("missing_identity")


def _render_saved(state: dict[str, Any], meta: dict[str, Any], runtime: str, session_id: str | None, thread_id: str | None) -> str:
    plan = state["plan"]
    lines = [
        "# Session Handover", "", f"- Runtime: {runtime}", f"- Session ID: {session_id or 'null'}",
        f"- Thread ID: {thread_id or 'null'}", f"- Task ID: {meta['task_id']}",
        f"- Project: {meta['project_path']}", f"- Worktree: {meta['worktree_path']}",
        f"- Generated: {datetime.now(timezone.utc).isoformat()}", "", "## Objective", "",
        state["objective"], "", "## Next acceptance condition", "", state["next_acceptance"],
        "", "## Plan", "", f"- Path: {plan['path']}", f"- Anchor: {plan['anchor']}",
        f"- Version: {plan['version']}", f"- Section SHA-256: {plan['sha256']}", "", "## Dependencies", "",
    ]
    lines.extend([f"- {item}" for item in state["dependencies"]] or ["- none"])
    lines.extend(["", "## Unanswered questions", ""])
    lines.extend([f"- {item}" for item in state["unanswered_questions"]] or ["- none"])
    lines.extend(["", "## Stored required gates", ""])
    for gate in state["required_gates"]:
        approval = gate["approval_ref"] if gate["approval_ref"] is not None else "none"
        evidence = ", ".join(gate["evidence_refs"]) or "none"
        lines.append(f"- {gate['name']}: {gate['status']}; approval={approval}; evidence={evidence}")
    if not state["required_gates"]:
        lines.append("- none declared")
    lines.extend(["", "## Stored evidence", ""])
    for item in state["evidence"]:
        lines.append(f"- {item['name']}: stored={item['status']}; command={item['command']}; result={item['result']}")
    if not state["evidence"]:
        lines.append("- none")
    lines.extend(["", "## Next action", "", state["next_action"], ""])
    return "\n".join(lines)


def _current_plan_status(state: dict[str, Any], allowed_plan_roots: list[Path]) -> tuple[str, str | None]:
    plan = state["plan"]
    path = Path(plan["path"])
    if not _plan_path_allowed(path, allowed_plan_roots):
        return "unknown", "plan_path_not_allowed"
    try:
        if plan_section_version(path, plan["anchor"]) != plan["version"]:
            return "stale", "plan_version_changed"
        current = plan_section_hash(path, plan["anchor"])
    except HandoverError as error:
        return "unknown", error.code
    if current != plan["sha256"]:
        return "stale", "plan_hash_changed"
    return "current", None


def _render_loaded(
    state: dict[str, Any], saved_body: str, current: dict[str, Any] | None,
    allowed_plan_roots: list[Path],
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    plan_status, plan_reason = _current_plan_status(state, allowed_plan_roots)
    validity: list[dict[str, Any]] = []
    lines = [saved_body.rstrip(), "", "## Current evidence validity", "", f"- Plan: {plan_status}" + (f" ({plan_reason})" if plan_reason else "")]
    for item in state["evidence"]:
        reasons: list[str] = []
        for key in FINGERPRINT_KEYS:
            expected = item["fingerprints"][key]
            actual = current.get(key) if isinstance(current, dict) else None
            if not isinstance(actual, str) or not actual.strip():
                reasons.append(f"{key}:unknown")
            elif expected is None:
                reasons.append(f"{key}:unknown")
            elif actual != expected:
                reasons.append(f"{key}:changed")
        if plan_status != "current" and f"plan:{plan_status}" not in reasons:
            reasons.append(f"plan:{plan_status}")
        if item["status"] != "passed":
            reasons.append(f"stored:{item['status']}")
        status = "current" if not reasons else "stale_or_unknown"
        validity.append({"name": item["name"], "status": status, "reasons": reasons})
        lines.append(f"- {item['name']}: {status}" + (f" ({', '.join(reasons)})" if reasons else ""))
    validity_by_name = {item["name"]: item for item in validity}
    effective_gates: list[dict[str, Any]] = []
    lines.extend(["", "## Effective required gates", ""])
    for gate in state["required_gates"]:
        effective = dict(gate)
        reasons: list[str] = []
        unresolved = [
            reference for reference in gate["evidence_refs"]
            if validity_by_name.get(reference, {}).get("status") != "current"
        ]
        invalid_gate = plan_status != "current" or not gate["evidence_refs"] or bool(unresolved)
        if gate["status"] == "passed" and invalid_gate:
            effective["status"] = "needs_revalidation"
            if plan_status != "current":
                reasons.append(f"plan is {plan_status}")
            if not gate["evidence_refs"]:
                reasons.append("no evidence references")
            if unresolved:
                reasons.append("evidence stale, unknown, or missing: " + ", ".join(unresolved))
        effective["reasons"] = reasons
        effective_gates.append(effective)
        lines.append(f"- {gate['name']}: {effective['status']}" + (f" ({'; '.join(reasons)})" if reasons else ""))
    if not effective_gates:
        lines.append("- none declared")
    lines.extend(["", "Use effective gate status for resume decisions.", ""])
    return "\n".join(lines), validity, effective_gates


def _request_context(request: dict[str, Any], cwd: Path) -> tuple[Path, Path]:
    project = Path(request.get("project_path") or cwd)
    worktree = Path(request.get("worktree_path") or cwd)
    if not project.is_absolute() or not worktree.is_absolute():
        raise HandoverError("context_mismatch")
    try:
        project_real = project.resolve(strict=True)
        worktree_real = worktree.resolve(strict=True)
    except OSError as error:
        raise HandoverError("invalid_context_path") from error
    if worktree_real != cwd:
        raise HandoverError("context_mismatch")
    return project_real, worktree_real


def _allowed_plan_roots(request: dict[str, Any], runtime: str, cwd: Path) -> list[Path]:
    roots = [cwd]
    homes = [_runtime_home("codex"), _runtime_home(runtime)]
    for home in homes:
        if home.exists():
            dashboard_root = home.resolve(strict=True) / ".local" / "dashboards"
            if dashboard_root.is_dir() and dashboard_root not in roots:
                roots.append(dashboard_root.resolve(strict=True))
    explicit = request.get("plan_root")
    if explicit:
        real = _strict_dir(Path(explicit), "plan_root_not_allowed")
        if real not in roots:
            roots.append(real)
    return roots


def _resolve_for_request(request: dict[str, Any], runtime: str, cwd: Path, session_id: str | None, thread_id: str | None) -> tuple[Path, dict[str, Any]]:
    project, worktree = _request_context(request, cwd)
    memory = request.get("task_memory_root")
    return resolve_task(
        cwd, session_id, thread_id, runtime=runtime, expected_project=project,
        expected_worktree=worktree, explicit_memory_base=Path(memory) if memory else None,
    )


def _init_memory_root(runtime: str, value: Any) -> tuple[Path, int]:
    requested = Path(_require_text(value, "task_memory_root"))
    runtime_home = _runtime_home(runtime)
    if not requested.is_absolute() or ".." in requested.parts or not runtime_home.is_absolute():
        raise HandoverError("memory_root_escape", str(requested))
    runtime_home_input = Path(os.path.abspath(runtime_home))
    try:
        runtime_home_real = runtime_home_input.resolve(strict=True)
    except OSError as error:
        raise HandoverError("invalid_runtime_home", str(runtime_home)) from error
    if not runtime_home_real.is_dir():
        raise HandoverError("invalid_runtime_home", str(runtime_home))
    expected = runtime_home_real / ".local" / "memory"
    requested_input = Path(os.path.abspath(requested))
    raw_expected = runtime_home_input / ".local" / "memory"
    if requested_input not in {raw_expected, expected}:
        raise HandoverError("memory_root_escape", str(requested))
    try:
        if requested_input.resolve(strict=False) != expected:
            raise HandoverError("memory_root_escape", str(requested))
    except OSError as error:
        raise HandoverError("memory_root_escape", str(requested)) from error
    _private_dir(expected, runtime_home_real, chmod_existing_final=False)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    home_fd = local_fd = -1
    try:
        home_fd = os.open(runtime_home_real, flags)
        local_fd = os.open(".local", flags, dir_fd=home_fd)
        root_fd = os.open("memory", flags, dir_fd=local_fd)
    except OSError as error:
        raise HandoverError("memory_root_escape", str(requested)) from error
    finally:
        if local_fd >= 0:
            os.close(local_fd)
        if home_fd >= 0:
            os.close(home_fd)
    return expected, root_fd


def init_task(request: dict[str, Any]) -> dict[str, Any]:
    runtime = request.get("runtime")
    if runtime not in {"codex", "claude"}:
        raise HandoverError("unsupported_runtime")
    raw_paths = {
        key: Path(_require_text(request.get(key), key))
        for key in ("cwd", "project_path", "worktree_path")
    }
    if any(not path.is_absolute() for path in raw_paths.values()):
        raise HandoverError("invalid_context_path")
    try:
        cwd = raw_paths["cwd"].resolve(strict=True)
    except OSError as error:
        raise HandoverError("invalid_context_path", "cwd") from error
    if not cwd.is_dir():
        raise HandoverError("invalid_context_path", "cwd")
    project, worktree = _request_context(request, cwd)
    if not project.is_dir() or not worktree.is_dir():
        raise HandoverError("invalid_context_path")
    task_id = _safe_id(request.get("task_id"), "task_id", optional=False)
    session_id = _safe_id(request.get("session_id"), "session_id")
    thread_id = _safe_id(request.get("thread_id"), "thread_id")
    if session_id is None and thread_id is None:
        raise HandoverError("missing_identity")
    task_title = _require_text(request.get("task_title"), "task_title")
    code_change = request.get("code_change")
    if type(code_change) is not bool:
        raise HandoverError("invalid_schema", "code_change")
    now = datetime.now(timezone.utc).isoformat()
    metadata: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION, "task_id": task_id, "task_title": task_title,
        "project_path": str(project), "worktree_path": str(worktree),
        "task_state": "active", "code_change": code_change,
        "created_at": now, "updated_at": now,
    }
    if session_id is not None:
        metadata["session_id"] = session_id
    if thread_id is not None:
        metadata["thread_id"] = thread_id
    content = _json(metadata) + "\n"
    if len(content.encode("utf-8")) > MAX_JSON_BYTES:
        raise HandoverError("metadata_too_large")
    root, root_fd = _init_memory_root(runtime, request.get("task_memory_root"))
    try:
        lock_path = root / ".session-handover-init.lock"
        lock_fd = _open_lock_at(root_fd, lock_path.name, lock_path)
        with os.fdopen(lock_fd, "r+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            for child_name in sorted(os.listdir(root_fd)):
                child = root / child_name
                try:
                    info = os.stat(child_name, dir_fd=root_fd, follow_symlinks=False)
                except OSError as error:
                    raise HandoverError("task_scan_changed", str(child)) from error
                if stat.S_ISLNK(info.st_mode):
                    raise HandoverError("task_path_escape", str(child))
                if not stat.S_ISDIR(info.st_mode):
                    continue
                if child_name.startswith("."):
                    raise HandoverError("task_path_escape", str(child))
                child_fd, _ = _open_directory_at(root_fd, child_name, child, create=False)
                try:
                    opened = os.fstat(child_fd)
                    if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                        raise HandoverError("task_scan_changed", str(child))
                    meta_path = child / "task-meta.json"
                    try:
                        os.stat(meta_path.name, dir_fd=child_fd, follow_symlinks=False)
                    except FileNotFoundError:
                        continue
                    meta = _validate_task_meta(_read_json_at(child_fd, meta_path.name, meta_path), meta_path)
                    _safe_id(meta["task_id"], f"{meta_path}:task_id", optional=False)
                    if meta["task_id"] != child_name:
                        raise HandoverError("invalid_task_metadata", str(meta_path))
                    if child_name == task_id:
                        raise HandoverError("metadata_exists", str(meta_path))
                    if session_id is not None and meta.get("session_id") == session_id:
                        raise HandoverError("identity_conflict", "session_id")
                    if thread_id is not None and meta.get("thread_id") == thread_id:
                        raise HandoverError("identity_conflict", "thread_id")
                finally:
                    os.close(child_fd)
            task_dir = root / task_id
            task_fd, task_created = _open_directory_at(root_fd, task_id, task_dir, create=True)
            task_identity = (os.fstat(task_fd).st_dev, os.fstat(task_fd).st_ino)
            meta_path = task_dir / "task-meta.json"
            try:
                _atomic_create_at(task_fd, meta_path.name, content, meta_path)
            except Exception:
                os.close(task_fd)
                task_fd = -1
                if task_created and _same_entry(root_fd, task_id, task_identity):
                    try:
                        os.rmdir(task_id, dir_fd=root_fd)
                    except OSError:
                        pass
                raise
            finally:
                if task_fd >= 0:
                    os.close(task_fd)
    finally:
        os.close(root_fd)
    return {"status": "created", "path": str(meta_path), "hash": _sha(content)}


def _open_lock(path: Path) -> int:
    existed = _regular_leaf(path, allow_missing=True)
    flags = os.O_RDWR | (0 if existed else os.O_CREAT | os.O_EXCL)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        _regular_leaf(path, allow_missing=False)
        existed = True
        fd = os.open(path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
    except OSError as error:
        raise HandoverError("lock_open_failed", str(path)) from error
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise HandoverError("non_regular_file", str(path))
    if not existed:
        os.fchmod(fd, 0o600)
    return fd


def save_handover(request: dict[str, Any]) -> dict[str, Any]:
    runtime = request.get("runtime")
    if runtime not in {"codex", "claude"}:
        raise HandoverError("unsupported_runtime")
    cwd = Path(_require_text(request.get("cwd"), "cwd")).resolve(strict=True)
    session_id = _safe_id(request.get("session_id"), "session_id")
    thread_id = _safe_id(request.get("thread_id"), "thread_id")
    local_root = _local_root(cwd, request.get("memory_dir"))
    task_dir, meta = _resolve_for_request(request, runtime, cwd, session_id, thread_id)
    plan_roots = _allowed_plan_roots(request, runtime, cwd)
    canonical = local_root / "handovers" / _canonical_name(session_id, thread_id)
    owner = _owner(meta, runtime, session_id, thread_id)
    state_value = request.get("short_state")
    expected_canonical = request.get("expected_canonical_hash")
    expected_pointer = request.get("expected_pointer_hash")
    for label, value in (("canonical", expected_canonical), ("pointer", expected_pointer)):
        if value is not None and not SHA256.fullmatch(str(value)):
            raise HandoverError("invalid_expected_hash", label)
    _private_dir(local_root, cwd)
    handovers = local_root / "handovers"
    locks = local_root / "runtime" / "locks"
    _private_dir(handovers, local_root)
    _private_dir(locks, local_root)
    lock_fd = _open_lock(locks / "session-handover.lock")
    with os.fdopen(lock_fd, "r+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        existing_record: dict[str, Any] | None = None
        canonical_present = canonical.exists() or canonical.is_symlink()
        if expected_canonical is not None and not canonical_present:
            return {"status": "conflict", "canonical": {"status": "conflict", "reason": "missing_expected_target", "path": str(canonical)}, "pointer": {"status": "not_attempted"}}
        if canonical_present:
            try:
                existing_record, _ = _parse_generated(canonical, "canonical")
            except HandoverError as error:
                return {"status": "conflict", "canonical": {"status": "conflict", "reason": error.code, "path": str(canonical)}, "pointer": {"status": "not_attempted"}}
            if not _same_owner(existing_record, owner) or existing_record.get("runtime") != runtime:
                return {"status": "conflict", "canonical": {"status": "conflict", "reason": "owner_mismatch", "path": str(canonical)}, "pointer": {"status": "not_attempted"}}
            if expected_canonical is not None and existing_record["artifact_sha256"] != expected_canonical:
                return {"status": "conflict", "canonical": {"status": "conflict", "reason": "cas_mismatch", "path": str(canonical)}, "pointer": {"status": "not_attempted"}}
        if state_value is None:
            if existing_record is None:
                raise HandoverError("missing_short_state")
            state = validate_state(existing_record.get("state"), check_plan=False)
            canonical_result = {"status": "unchanged", "path": str(canonical), "hash": existing_record["artifact_sha256"]}
        else:
            state = validate_state(state_value, check_plan=True, allowed_plan_roots=plan_roots)
            body = _render_saved(state, meta, runtime, session_id, thread_id)
            record = {
                "owner": owner, "runtime": runtime, "task_dir": str(task_dir),
                "project_path": meta["project_path"], "worktree_path": meta["worktree_path"],
                "plan_sha256": state["plan"]["sha256"], "state": state,
            }
            generated = _marker("canonical", record, body)
            generated_record, _ = _parse_generated_text(generated, "canonical")
            if existing_record is not None and existing_record.get("state") == state:
                canonical_result = {"status": "unchanged", "path": str(canonical), "hash": existing_record["artifact_sha256"]}
            elif existing_record is not None and expected_canonical is None:
                return {"status": "conflict", "canonical": {"status": "conflict", "reason": "missing_expected_hash", "path": str(canonical)}, "pointer": {"status": "not_attempted"}}
            else:
                _atomic_write(canonical, generated, local_root)
                canonical_result = {"status": "saved", "path": str(canonical), "hash": generated_record["artifact_sha256"]}
        pointer = local_root / "HANDOVER.md"
        relative = canonical.relative_to(local_root).as_posix()
        id_label = "session_id" if session_id is not None else "thread_id"
        id_value = session_id if session_id is not None else thread_id
        pointer_body = f"{id_label}: `{id_value}`\npath: `{relative}`\n"
        pointer_generated = _marker("pointer", {"owner": owner, "canonical_path": relative}, pointer_body)
        new_pointer, _ = _parse_generated_text(pointer_generated, "pointer")
        pointer_present = pointer.exists() or pointer.is_symlink()
        if expected_pointer is not None and not pointer_present:
            pointer_result = {"status": "conflict", "reason": "missing_expected_target", "path": str(pointer)}
        elif pointer_present:
            try:
                old_pointer, old_pointer_body = _parse_generated(pointer, "pointer")
            except HandoverError as error:
                pointer_result = {"status": "conflict", "reason": error.code, "path": str(pointer)}
            else:
                if not _same_owner(old_pointer, owner):
                    pointer_result = {"status": "conflict", "reason": "owner_mismatch", "path": str(pointer)}
                elif expected_pointer is not None and old_pointer["artifact_sha256"] != expected_pointer:
                    pointer_result = {"status": "conflict", "reason": "cas_mismatch", "path": str(pointer)}
                elif old_pointer_body == pointer_body:
                    pointer_result = {"status": "unchanged", "path": str(pointer), "hash": old_pointer["artifact_sha256"]}
                elif expected_pointer is None:
                    pointer_result = {"status": "conflict", "reason": "missing_expected_hash", "path": str(pointer)}
                else:
                    _atomic_write(pointer, pointer_generated, local_root)
                    pointer_result = {"status": "saved", "path": str(pointer), "hash": new_pointer["artifact_sha256"]}
        else:
            _atomic_write(pointer, pointer_generated, local_root)
            pointer_result = {"status": "saved", "path": str(pointer), "hash": new_pointer["artifact_sha256"]}
    overall = "partial" if pointer_result["status"] == "conflict" else "saved"
    return {"status": overall, "canonical": canonical_result, "pointer": pointer_result}


def load_handover(request: dict[str, Any]) -> dict[str, Any]:
    runtime = request.get("runtime")
    if runtime not in {"codex", "claude"}:
        raise HandoverError("unsupported_runtime")
    cwd = Path(_require_text(request.get("cwd"), "cwd")).resolve(strict=True)
    session_id = _safe_id(request.get("session_id"), "session_id")
    thread_id = _safe_id(request.get("thread_id"), "thread_id")
    local_root = _local_root(cwd, request.get("memory_dir"))
    _, meta = _resolve_for_request(request, runtime, cwd, session_id, thread_id)
    plan_roots = _allowed_plan_roots(request, runtime, cwd)
    canonical = local_root / "handovers" / _canonical_name(session_id, thread_id)
    if not canonical.is_file() or canonical.is_symlink():
        raise HandoverError("handover_not_found", str(canonical))
    record, saved_body = _parse_generated(canonical, "canonical")
    owner = _owner(meta, runtime, session_id, thread_id)
    if not _same_owner(record, owner) or record.get("runtime") != runtime:
        raise HandoverError("owner_mismatch")
    if record.get("project_path") != meta["project_path"] or record.get("worktree_path") != meta["worktree_path"]:
        raise HandoverError("context_mismatch")
    state = validate_state(record.get("state"), check_plan=False)
    if record.get("plan_sha256") != state["plan"]["sha256"]:
        raise HandoverError("stored_plan_hash_mismatch")
    context, validity, effective_gates = _render_loaded(
        state, saved_body, request.get("current_fingerprints"), plan_roots
    )
    return {
        "status": "loaded", "path": str(canonical), "hash": record["artifact_sha256"],
        "context": context, "evidence_validity": validity,
        "effective_required_gates": effective_gates, "state": state,
    }


def _request_from_args(args: argparse.Namespace, *, include_state: bool) -> dict[str, Any]:
    request: dict[str, Any] = {
        "runtime": args.runtime, "cwd": args.cwd, "session_id": args.session_id,
        "thread_id": args.thread_id, "memory_dir": args.memory_dir,
        "task_memory_root": args.task_memory_root, "project_path": args.project_path,
        "worktree_path": args.worktree_path, "plan_root": args.plan_root,
    }
    if include_state and args.state_file:
        if args.state_file == "-":
            try:
                request["short_state"] = _read_stdin_json()
            except (ValueError, UnicodeError, json.JSONDecodeError) as error:
                raise HandoverError("invalid_json", "stdin") from error
        else:
            request["short_state"] = _read_json(Path(args.state_file))
    for key in ("expected_canonical_hash", "expected_pointer_hash"):
        value = getattr(args, key, None)
        if value is not None:
            request[key] = value
    if getattr(args, "fingerprints_file", None):
        request["current_fingerprints"] = _read_json(Path(args.fingerprints_file))
    return request


def run_hook(runtime: str, event: str, payload: dict[str, Any]) -> tuple[str, str]:
    try:
        request: dict[str, Any] = {
            "runtime": runtime, "cwd": payload.get("cwd"), "session_id": payload.get("session_id"),
            "thread_id": payload.get("thread_id"),
            "memory_dir": os.environ.get("SESSION_HANDOVER_MEMORY_DIR"),
            "task_memory_root": os.environ.get("SESSION_HANDOVER_TASK_MEMORY_ROOT"),
            "plan_root": os.environ.get("SESSION_HANDOVER_PLAN_ROOT"),
            "project_path": payload.get("project_path") or payload.get("cwd"),
            "worktree_path": payload.get("worktree_path") or payload.get("cwd"),
        }
        if "current_fingerprints" in payload:
            request["current_fingerprints"] = payload["current_fingerprints"]
        for key in ("expected_canonical_hash", "expected_pointer_hash"):
            if payload.get(key) is not None:
                request[key] = payload[key]
        if event in {"PreCompact", "Stop"}:
            if event == "Stop" and payload.get("stop_hook_active") is True:
                return "", ""
            if payload.get("short_state") is not None:
                request["short_state"] = payload["short_state"]
            result = save_handover(request)
            if result["canonical"]["status"] == "conflict" or result["pointer"]["status"] == "conflict":
                return "", f"session-handover: {_json(result)}\n"
            return "", ""
        if event == "SessionStart":
            result = load_handover(request)
            output = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": result["context"]}}
            return _json(output) + "\n", ""
        return "", "session-handover: unsupported_event\n"
    except HandoverError as error:
        return "", f"session-handover: {error.code}\n"
    except Exception:
        return "", "session-handover: internal_error\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.error = _init_argument_error  # type: ignore[method-assign]
    init.add_argument("--runtime", choices=("codex", "claude"), required=True)
    init.add_argument("--cwd", required=True)
    init.add_argument("--project-path", required=True)
    init.add_argument("--worktree-path", required=True)
    init.add_argument("--task-memory-root", required=True)
    init.add_argument("--task-id", required=True)
    init.add_argument("--task-title", required=True)
    init.add_argument("--session-id")
    init.add_argument("--thread-id")
    init.add_argument("--code-change", choices=("true", "false"), required=True)
    for name in ("save", "load"):
        command = sub.add_parser(name)
        command.add_argument("--runtime", choices=("codex", "claude"), required=True)
        command.add_argument("--cwd", required=True)
        command.add_argument("--session-id")
        command.add_argument("--thread-id")
        command.add_argument("--memory-dir")
        command.add_argument("--task-memory-root")
        command.add_argument("--plan-root")
        command.add_argument("--project-path")
        command.add_argument("--worktree-path")
        if name == "save":
            command.add_argument("--state-file")
            command.add_argument("--expected-canonical-hash")
            command.add_argument("--expected-pointer-hash")
        else:
            command.add_argument("--fingerprints-file")
            command.add_argument("--format", choices=("text", "json"), default="text")
    hook = sub.add_parser("hook")
    hook.add_argument("--runtime", choices=("codex", "claude"), required=True)
    hook.add_argument("--event", required=True)
    resolve = sub.add_parser("resolve")
    resolve.add_argument("--runtime", choices=("codex", "claude"), default="codex")
    resolve.add_argument("--cwd", required=True)
    resolve.add_argument("--session-id")
    resolve.add_argument("--thread-id")
    resolve.add_argument("--memory-base")
    resolve.add_argument("--project-path")
    resolve.add_argument("--worktree-path")
    path = sub.add_parser("path")
    path.add_argument("--local-root", required=True)
    path.add_argument("--session-id")
    path.add_argument("--thread-id")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        if args.command == "init":
            result = init_task({
                "runtime": args.runtime, "cwd": args.cwd,
                "project_path": args.project_path, "worktree_path": args.worktree_path,
                "task_memory_root": args.task_memory_root, "task_id": args.task_id,
                "task_title": args.task_title, "session_id": args.session_id,
                "thread_id": args.thread_id, "code_change": args.code_change == "true",
            })
            print(_json(result))
            return 0
        if args.command == "hook":
            try:
                payload = _read_stdin_json()
            except (ValueError, json.JSONDecodeError, UnicodeError):
                sys.stderr.write("session-handover: invalid_hook_json\n")
                return 0
            if not isinstance(payload, dict):
                sys.stderr.write("session-handover: invalid_hook_json\n")
                return 0
            stdout, stderr = run_hook(args.runtime, args.event, payload)
            sys.stdout.write(stdout)
            sys.stderr.write(stderr)
            return 0
        if args.command == "save":
            result = save_handover(_request_from_args(args, include_state=True))
            print(_json(result))
            has_conflict = (
                result.get("canonical", {}).get("status") == "conflict"
                or result.get("pointer", {}).get("status") == "conflict"
            )
            return 3 if has_conflict else 0
        if args.command == "load":
            result = load_handover(_request_from_args(args, include_state=False))
            print(result["context"] if args.format == "text" else _json(result))
            return 0
        if args.command == "resolve":
            cwd = Path(args.cwd).resolve(strict=True)
            project = Path(args.project_path or cwd).resolve(strict=True)
            worktree = Path(args.worktree_path or cwd).resolve(strict=True)
            task, _ = resolve_task(
                cwd, args.session_id, args.thread_id, runtime=args.runtime,
                expected_project=project, expected_worktree=worktree,
                explicit_memory_base=Path(args.memory_base) if args.memory_base else None,
            )
            print(task)
            return 0
        if args.command == "path":
            session_id = _safe_id(args.session_id, "session_id")
            thread_id = _safe_id(args.thread_id, "thread_id")
            print(Path(args.local_root) / "handovers" / _canonical_name(session_id, thread_id))
            return 0
    except HandoverError as error:
        print(_json({"status": "rejected", "reason": error.code, "detail": error.detail}), file=sys.stderr)
        return 2
    except Exception:
        print(_json({"status": "rejected", "reason": "internal_error", "detail": ""}), file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
