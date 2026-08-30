#!/usr/bin/env python3
from __future__ import annotations

import argparse
import functools
import hashlib
import http.server
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "tools" / "roadmap_viewer.html"
HTML_CONTRACT = ROOT / "scripts" / "html_artifact_contract.py"
PLACEHOLDER = '{"__ROADMAP_SNAPSHOT_JSON__": true}'
DEFAULT_FILES = [
    "00_spec.md",
    "10_task.md",
    "20_survey.md",
    "30_plan.md",
    "40_progress.md",
    "80_review.md",
    "05_log.md",
    "99_history.md",
    "checkpoint.md",
    "team-journal.md",
    "90_verification.md",
    "graph-map.md",
]

OUTPUT_NAMES = {"roadmap.html", "roadmap-snapshot.json"}
PLAN_CONTRACT = ROOT / "scripts" / "roadmap_plan_contract.py"
EMBEDDED_SNAPSHOT_RE = re.compile(
    r'<script\b(?=[^>]*\bid=["\']embedded-snapshot["\'])[^>]*>(.*?)</script\s*>',
    re.IGNORECASE | re.DOTALL,
)
HEAD_OPEN_RE = re.compile(r"(<head\b[^>]*>)", re.IGNORECASE)
ARTIFACT_KIND_META_RE = re.compile(
    r'<meta\b[^>]*\bname=["\']artifact-kind["\']',
    re.IGNORECASE,
)
CSP_META_RE = re.compile(
    r'<meta\b[^>]*\bhttp-equiv=["\']Content-Security-Policy["\']',
    re.IGNORECASE,
)
ROADMAP_CSP = (
    "default-src 'none'; "
    "script-src 'unsafe-inline'; "
    "style-src 'unsafe-inline'; "
    "img-src data:; "
    "connect-src 'self'; "
    "base-uri 'none'; "
    "form-action 'none'"
)
IMPLEMENTATION_EVIDENCE_RE = re.compile(
    r"^#### 実装根拠\s*$([\s\S]*?)(?=^####\s|\Z)",
    re.MULTILINE,
)
INLINE_CODE_RE = re.compile(r"`([^`\r\n]+)`")
LINE_RANGE_RE = re.compile(r"^L([1-9]\d*)-L([1-9]\d*)$")

DEFAULT_SOURCE_ALLOW_PREFIXES = (
    ".codex",
    ".agents",
    ".github",
    "_shared-ai",
    "src",
    "app",
    "apps",
    "lib",
    "libs",
    "packages",
    "test",
    "tests",
    "scripts",
    "config",
    "docs",
)
DENIED_SOURCE_COMPONENTS = {
    "Daily",
    "Living",
    "Life",
    "Work",
    "Inbox",
    "Reading",
    "attachments",
    "Claude-note",
    "Codex-note",
    ".git",
    ".obsidian",
    ".local",
}
ALLOWED_HIDDEN_SOURCE_COMPONENTS = {".codex", ".agents", ".github"}
SECRET_SOURCE_NAMES = {
    ".npmrc",
    ".pypirc",
    ".netrc",
    "credentials.json",
    "secrets.json",
    "id_rsa",
    "id_dsa",
    "id_ed25519",
}
SECRET_SOURCE_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}
MAX_SOURCE_FILE_BYTES = 1024 * 1024
MAX_PREVIEW_LINES = 12
MAX_PREVIEW_BYTES = 4 * 1024
MAX_TOTAL_PREVIEW_BYTES = 32 * 1024
MAX_SOURCE_PREVIEW_COUNT = 24
MAX_UI_PREVIEW_BLOCK_BYTES = 16 * 1024
MAX_UI_PREVIEWS_PER_TASK = 3
MAX_UI_PREVIEW_COUNT = 24
MAX_TOTAL_UI_PREVIEW_BYTES = 64 * 1024
MAX_UI_ITEMS_PER_SIDE = 24
MAX_UI_TEXT_CHARS = 120
GIT_SUBPROCESS_TIMEOUT = 5.0

SECRET_CONTENT_PATTERNS = (
    re.compile(
        r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----",
        re.IGNORECASE,
    ),
    re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bgh(?:p|o|u|s|r)_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}\b"),
    re.compile(r"\bxox(?:a|b|p|r|s)-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(
        r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"
    ),
    re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9/_-]{20,}"),
    re.compile(
        r"https://(?:discord(?:app)?\.com)/api/webhooks/\d+/[A-Za-z0-9._-]{20,}"
    ),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{32,}", re.IGNORECASE),
)

LANGUAGE_BY_SUFFIX = {
    ".c": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cs": "csharp",
    ".css": "css",
    ".go": "go",
    ".html": "html",
    ".java": "java",
    ".js": "javascript",
    ".jsx": "jsx",
    ".json": "json",
    ".kt": "kotlin",
    ".md": "markdown",
    ".mjs": "javascript",
    ".php": "php",
    ".py": "python",
    ".rb": "ruby",
    ".rs": "rust",
    ".sh": "shell",
    ".sql": "sql",
    ".swift": "swift",
    ".toml": "toml",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".vue": "vue",
    ".xml": "xml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".zsh": "shell",
}
UI_PREVIEW_BLOCK_RE = re.compile(
    r"```[ \t]*ui-preview-json[ \t]*\r?\n([\s\S]*?)\r?\n```",
    re.IGNORECASE,
)
UI_CHANGE_MARKER_RE = re.compile(
    r"(?mi)^\s*(?:[-*]\s*)?UI変更\s*[:：]\s*(?:yes|true|あり|対象)\s*$"
)
STABLE_UI_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,63}$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40,64}$")
RAW_HTML_RE = re.compile(r"</?[A-Za-z][^>]*>")
EXTERNAL_URL_RE = re.compile(r"(?i)(?:https?:)?//")
LOG_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)\s*$", re.MULTILINE)
LOG_ISO_DATE_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})(?:[ T]+(?P<time>\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?))?"
)
LOG_JP_DATE_RE = re.compile(
    r"^(?P<year>\d{4})年(?P<month>\d{1,2})月(?P<day>\d{1,2})日"
    r"(?:[ T]+(?P<hour>\d{1,2}):(?P<minute>\d{2})(?::(?P<second>\d{2}))?)?"
)
ALLOWED_UI_LAYOUTS = {"topnav", "sidebar", "settings", "list", "form"}
ALLOWED_UI_ITEM_KINDS = {"label", "item", "group", "action", "input"}
ALLOWED_UI_CHANGES = {"same", "added", "modified", "removed"}


class RoadmapHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text)
    tmp.replace(path)


def write_text_if_changed(path: Path, text: str) -> bool:
    try:
        if path.is_file() and path.read_text() == text:
            return False
    except OSError:
        pass
    atomic_write_text(path, text)
    return True


def _publish_stage_path(path: Path) -> Path:
    token = f"{os.getpid()}.{threading.get_ident()}.{time.time_ns()}"
    return path.with_name(f".{path.name}.{token}.tmp")


def _replace_staged(stage: Path, destination: Path) -> None:
    """Replace one published output; kept injectable for failure testing."""
    stage.replace(destination)


def _read_publish_target(path: Path) -> tuple[bool, str | None]:
    if not path.exists():
        return False, None
    try:
        return True, path.read_text()
    except OSError as error:
        raise OSError(f"cannot read existing Roadmap output {path}: {error}") from error


def _cleanup_publish_stage(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError:
        # The original publish error is more useful than cleanup noise. The
        # next generation will still use a fresh unique stage path.
        return


def publish_output_pair(
    html_path: Path,
    html_text: str,
    json_path: Path,
    json_text: str,
) -> None:
    """Publish HTML and JSON as one recoverable pair.

    Both payloads are staged and read back before either destination changes.
    The destinations are then replaced in sequence; if a later replacement
    fails, already replaced destinations are restored from their private
    backups. This preserves the old pair for ordinary write failures while
    keeping ``write_json=False`` on the historical single-file path.
    """
    if html_path.resolve(strict=False) == json_path.resolve(strict=False):
        raise ValueError("HTML and JSON Roadmap outputs must be different files")
    try:
        parsed_json = json.loads(json_text)
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError(f"Roadmap snapshot JSON is invalid: {error}") from error
    if not isinstance(parsed_json, dict):
        raise ValueError("Roadmap snapshot JSON must contain an object")

    targets = [(html_path, html_text), (json_path, json_text)]
    states: list[dict[str, object]] = []
    staged: list[Path] = []
    backups: list[Path] = []
    replaced: list[dict[str, object]] = []
    try:
        # Read both old destinations first. A read error therefore occurs
        # before either new payload can become visible.
        for path, text in targets:
            existed, previous = _read_publish_target(path)
            stage = _publish_stage_path(path)
            atomic_write_text(stage, text)
            if stage.read_text() != text:
                raise OSError(f"staged Roadmap output was not verified: {stage}")
            staged.append(stage)
            states.append(
                {
                    "path": path,
                    "text": text,
                    "existed": existed,
                    "previous": previous,
                    "stage": stage,
                    "changed": not existed or previous != text,
                    "backup": None,
                }
            )

        # Back up only destinations that will change. Backups are prepared
        # before the first replacement, so rollback does not depend on the
        # old destination remaining readable after publication starts.
        for state in states:
            if not state["changed"] or not state["existed"]:
                continue
            path = state["path"]
            previous = state["previous"]
            if not isinstance(path, Path) or not isinstance(previous, str):
                raise OSError("invalid Roadmap output backup state")
            backup = _publish_stage_path(path)
            atomic_write_text(backup, previous)
            if backup.read_text() != previous:
                raise OSError(f"Roadmap output backup was not verified: {backup}")
            backups.append(backup)
            state["backup"] = backup

        # Preserve the historical HTML-then-JSON order. Any failure in the
        # second replacement is covered by the rollback below.
        for state in states:
            if not state["changed"]:
                continue
            replaced.append(state)
            stage = state["stage"]
            path = state["path"]
            if not isinstance(stage, Path) or not isinstance(path, Path):
                raise OSError("invalid Roadmap output publish state")
            _replace_staged(stage, path)
    except BaseException as error:
        rollback_errors: list[str] = []
        for state in reversed(replaced):
            path = state.get("path")
            existed = state.get("existed")
            backup = state.get("backup")
            if not isinstance(path, Path):
                rollback_errors.append("invalid Roadmap rollback path")
                continue
            try:
                if existed is True:
                    if not isinstance(backup, Path):
                        raise OSError("missing Roadmap rollback backup")
                    _replace_staged(backup, path)
                else:
                    path.unlink(missing_ok=True)
            except OSError as rollback_error:
                rollback_errors.append(f"{path}: {rollback_error}")
        if rollback_errors and hasattr(error, "add_note"):
            error.add_note("Roadmap output rollback failed: " + "; ".join(rollback_errors))
        raise
    finally:
        for path in staged + backups:
            _cleanup_publish_stage(path)


def ensure_task_meta(
    task_dir: Path,
    source_root: Path,
    *,
    thread_id: str | None = None,
    session_id: str | None = None,
    task_state: str | None = None,
) -> dict[str, object]:
    path = task_dir / "task-meta.json"
    existing: dict[str, object] = {}
    if path.is_symlink():
        raise ValueError("task-meta.json must not be a symlink")
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"invalid task-meta.json: {error}") from error
        if not isinstance(loaded, dict):
            raise ValueError("invalid task-meta.json: root must be an object")
        existing = loaded

    now = datetime.now(timezone.utc).isoformat()
    files, _ = read_files(task_dir)
    desired = {
        **existing,
        "schema_version": 1,
        "task_id": str(existing.get("task_id") or task_dir.name),
        "task_title": str(
            existing.get("task_title") or infer_title(files, task_dir)
        ),
        "project_path": str(source_root),
        "worktree_path": str(source_root),
        "task_state": str(task_state or existing.get("task_state") or "active"),
        "code_change": bool(
            existing.get("code_change") or (task_dir / "codemap.source.json").is_file()
        ),
        "created_at": str(existing.get("created_at") or now),
    }
    if thread_id:
        desired["thread_id"] = thread_id
    if session_id:
        desired["session_id"] = session_id
    comparable_existing = {key: value for key, value in existing.items() if key != "updated_at"}
    comparable_desired = {key: value for key, value in desired.items() if key != "updated_at"}
    desired["updated_at"] = (
        str(existing.get("updated_at"))
        if comparable_existing == comparable_desired and existing.get("updated_at")
        else now
    )
    write_text_if_changed(
        path,
        json.dumps(desired, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return desired


def read_files(task_dir: Path) -> tuple[dict[str, str], list[dict[str, object]]]:
    files: dict[str, str] = {}
    sources: list[dict[str, object]] = []
    for name in DEFAULT_FILES:
        path = task_dir / name
        if path.is_symlink():
            continue
        try:
            source_stat = path.stat(follow_symlinks=False)
        except OSError:
            continue
        if not stat.S_ISREG(source_stat.st_mode):
            continue
        text = path.read_text()
        files[name] = text
        sources.append(
            {
                "name": name,
                "path": str(path),
                "size": source_stat.st_size,
                "modifiedAt": datetime.fromtimestamp(source_stat.st_mtime, timezone.utc).isoformat(),
            }
        )
    return files, sources


def infer_source_root(task_dir: Path) -> Path | None:
    resolved = Path(os.path.abspath(task_dir))
    if (
        resolved.parent.name == "memory"
        and resolved.parent.parent.name == ".local"
    ):
        return resolved.parent.parent.parent
    return None


_PLAN_CONTRACT_MODULE: object | None = None


def load_plan_contract_module() -> object:
    """Load the one canonical Markdown-to-Plan parser used by Roadmap generation."""
    global _PLAN_CONTRACT_MODULE
    if _PLAN_CONTRACT_MODULE is not None:
        return _PLAN_CONTRACT_MODULE
    spec = importlib.util.spec_from_file_location("roadmap_plan_contract", PLAN_CONTRACT)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load Roadmap Plan contract: {PLAN_CONTRACT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    _PLAN_CONTRACT_MODULE = module
    return module


def parse_plan_model(
    plan: str,
    progress: str = "",
    *,
    plan_source: str = "30_plan.md",
    progress_source: str = "40_progress.md",
) -> dict[str, object]:
    """Return the canonical Plan model without reinterpreting Task headings here."""
    module = load_plan_contract_module()
    return module.parse_plan_contract(
        plan,
        progress,
        plan_source=plan_source,
        progress_source=progress_source,
    )


def _line_offsets(text: str) -> list[int]:
    offsets = [0]
    offsets.extend(match.end() for match in re.finditer(r"\n", text))
    return offsets


def iter_task_sections(
    plan: str,
    plan_model: dict[str, object] | None = None,
) -> list[tuple[str, int, int, str]]:
    """Compatibility adapter backed by the canonical Plan model.

    The source-preview/UI code historically consumed offsets and raw sections.
    Keep that tuple shape while taking Task identity and section boundaries from
    ``roadmap_plan_contract`` so this generator has no second Task parser.
    """
    model = plan_model or parse_plan_model(plan)
    offsets = _line_offsets(plan)
    sections: list[tuple[str, int, int, str]] = []
    tasks = model.get("tasks", [])
    if not isinstance(tasks, list):
        return sections
    for task in tasks:
        if not isinstance(task, dict):
            continue
        number = task.get("number")
        body = task.get("body")
        source = task.get("source")
        if not isinstance(number, str) or not isinstance(body, str):
            continue
        line_start = source.get("lineStart") if isinstance(source, dict) else None
        line_end = source.get("lineEnd") if isinstance(source, dict) else None
        start_offset = (
            offsets[int(line_start) - 1]
            if isinstance(line_start, int) and 1 <= line_start <= len(offsets)
            else 0
        )
        # ``body`` is preserved by the canonical parser. Locating that exact
        # slice keeps legacy preview span arithmetic compatible without
        # introducing another heading parser in this generator.
        body_offset = plan.find(body, start_offset)
        if body_offset >= 0:
            start_offset = body_offset
            end_offset = body_offset + len(body)
        else:
            end_offset = (
                offsets[int(line_end)]
                if isinstance(line_end, int) and 0 <= line_end < len(offsets)
                else len(plan)
            )
        sections.append((number, start_offset, end_offset, body))
    return sections


def parse_source_preview_references(
    plan: str,
    plan_model: dict[str, object] | None = None,
) -> list[tuple[str, str]]:
    references: list[tuple[str, str]] = []
    for task_number, _, _, task_section in iter_task_sections(plan, plan_model):
        evidence = IMPLEMENTATION_EVIDENCE_RE.search(task_section)
        if not evidence:
            continue
        first_inline = INLINE_CODE_RE.search(evidence.group(1))
        if not first_inline:
            continue
        reference = first_inline.group(1).strip()
        if not reference.startswith("repo:"):
            continue
        references.append((task_number, reference))
    return references


def source_language(relative_path: str) -> str:
    return LANGUAGE_BY_SUFFIX.get(Path(relative_path).suffix.lower(), "text")


def source_preview_record(
    task_number: str,
    relative_path: str,
    anchor: str,
    *,
    status: str,
    message: str,
    start_line: int | None = None,
    end_line: int | None = None,
    code: str = "",
    truncated: bool = False,
    evidence_revision: str | None = None,
) -> dict[str, object]:
    record: dict[str, object] = {
        "taskNumber": task_number,
        "path": relative_path,
        "anchor": anchor,
        "language": source_language(relative_path),
        "startLine": start_line,
        "endLine": end_line,
        "code": code,
        "status": status,
        "message": message,
        "truncated": truncated,
    }
    if evidence_revision:
        record["evidenceRevision"] = evidence_revision
    return record


def split_source_reference(reference: str) -> tuple[str, str]:
    payload = reference.removeprefix("repo:")
    relative_path, separator, anchor = payload.partition("#")
    if not separator:
        return relative_path.strip(), ""
    return relative_path.strip(), anchor.strip()


def normalize_source_prefixes(prefixes: list[str] | None) -> tuple[tuple[str, ...], ...]:
    values = [*DEFAULT_SOURCE_ALLOW_PREFIXES, *(prefixes or [])]
    normalized: list[tuple[str, ...]] = []
    for value in values:
        candidate = value.strip().rstrip("/")
        raw_parts = candidate.split("/")
        if (
            not candidate
            or candidate.startswith(("/", "~", "\\"))
            or "\\" in candidate
            or any(part in {"", ".", ".."} for part in raw_parts)
            or re.match(r"^[A-Za-z]:", candidate)
        ):
            continue
        parts = tuple(raw_parts)
        if parts not in normalized:
            normalized.append(parts)
    return tuple(normalized)


def validate_source_path_parts(
    raw_path: str,
    allowed_prefixes: tuple[tuple[str, ...], ...],
) -> tuple[tuple[str, ...] | None, str, str]:
    if (
        not raw_path
        or raw_path.startswith(("/", "~", "\\"))
        or "\\" in raw_path
        or re.match(r"^[A-Za-z]:", raw_path)
    ):
        return None, "source-denied", "相対パスではないため表示できません。"

    raw_parts = raw_path.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        return None, "source-denied", "安全でないパス指定のため表示できません。"

    denied_components = {value.casefold() for value in DENIED_SOURCE_COMPONENTS}
    for part in raw_parts:
        if part.casefold() in denied_components:
            return None, "source-denied", "表示禁止領域のため実コードを取得しません。"
        if part.startswith(".") and part not in ALLOWED_HIDDEN_SOURCE_COMPONENTS:
            return None, "source-denied", "hidden pathは表示対象にできません。"

    basename = raw_parts[-1].casefold()
    suffix = Path(basename).suffix.casefold()
    if (
        basename.startswith(".env")
        or basename in SECRET_SOURCE_NAMES
        or suffix in SECRET_SOURCE_SUFFIXES
    ):
        return None, "source-denied", "秘密情報を格納し得るファイルは表示できません。"

    path_parts = tuple(raw_parts)
    if not any(
        path_parts[: len(prefix)] == prefix
        for prefix in allowed_prefixes
    ):
        return None, "source-denied", "source allowlist外のため表示できません。"

    return path_parts, "", ""


def validate_source_path(
    raw_path: str,
    source_root: Path,
    allowed_prefixes: tuple[tuple[str, ...], ...],
) -> tuple[Path | None, str, str]:
    path_parts, status, message = validate_source_path_parts(
        raw_path,
        allowed_prefixes,
    )
    if path_parts is None:
        return None, status, message

    raw_parts = list(path_parts)
    candidate = source_root.joinpath(*raw_parts)
    try:
        candidate.relative_to(source_root)
    except ValueError:
        return None, "source-denied", "source root外のため表示できません。"

    current = source_root
    for part in raw_parts:
        current = current / part
        try:
            current_stat = current.lstat()
        except FileNotFoundError:
            return None, "source-missing", "参照先のsource fileが見つかりません。"
        except OSError:
            return None, "source-unavailable", "source fileを安全に確認できません。"
        if stat.S_ISLNK(current_stat.st_mode):
            return None, "source-denied", "symlinkは表示対象にできません。"

    try:
        candidate_stat = candidate.stat(follow_symlinks=False)
    except OSError:
        return None, "source-unavailable", "source fileを安全に確認できません。"
    if not stat.S_ISREG(candidate_stat.st_mode):
        return None, "source-denied", "regular fileではないため表示できません。"
    if candidate_stat.st_size > MAX_SOURCE_FILE_BYTES:
        return None, "source-denied", "1MiBを超えるsource fileは読み込みません。"

    try:
        resolved_candidate = candidate.resolve(strict=True)
        resolved_candidate.relative_to(source_root)
    except (OSError, ValueError):
        return None, "source-denied", "source root外のため表示できません。"
    return candidate, "", ""


def markdown_disallows_automation(text: str, relative_path: str) -> bool:
    if Path(relative_path).suffix.casefold() != ".md":
        return False
    lines = text.splitlines()
    if not lines or lines[0].lstrip("\ufeff").strip() != "---":
        return False
    try:
        frontmatter_end = next(
            index for index, line in enumerate(lines[1:], start=1)
            if line.strip() == "---"
        )
    except StopIteration:
        return False
    frontmatter = "\n".join(lines[1:frontmatter_end])
    return bool(
        re.search(
            r"""^\s*automation_read\s*:\s*(?:false|["']false["'])(?:\s*(?:#.*)?)?$""",
            frontmatter,
            re.IGNORECASE | re.MULTILINE,
        )
    )


def contains_secret_content(text: str) -> bool:
    return any(pattern.search(text) for pattern in SECRET_CONTENT_PATTERNS)


def truncate_utf8(text: str, byte_limit: int) -> tuple[str, bool]:
    encoded = text.encode("utf-8")
    if len(encoded) <= byte_limit:
        return text, False
    if byte_limit <= 0:
        return "", True
    return encoded[:byte_limit].decode("utf-8", errors="ignore"), True


def preview_text_record(
    task_number: str,
    relative_path: str,
    anchor: str,
    text: str,
    *,
    remaining_bytes: int,
    evidence_revision: str | None = None,
) -> dict[str, object]:
    if markdown_disallows_automation(text, relative_path):
        return source_preview_record(
            task_number,
            relative_path,
            anchor,
            status="source-denied",
            message="automation_read: falseのため本文を取得しません。",
            evidence_revision=evidence_revision,
        )

    lines = text.splitlines()
    range_match = LINE_RANGE_RE.fullmatch(anchor)
    truncated = False
    if range_match:
        requested_start = int(range_match.group(1))
        requested_end = int(range_match.group(2))
        if requested_end < requested_start or requested_start > len(lines):
            return source_preview_record(
                task_number,
                relative_path,
                anchor,
                status="anchor-missing",
                message="指定されたline rangeが見つかりません。",
                evidence_revision=evidence_revision,
            )
        start_line = requested_start
        end_line = min(requested_end, len(lines), start_line + MAX_PREVIEW_LINES - 1)
        truncated = end_line < requested_end
    else:
        start_index = next(
            (index for index, line in enumerate(lines) if anchor in line),
            None,
        )
        if start_index is None:
            return source_preview_record(
                task_number,
                relative_path,
                anchor,
                status="anchor-missing",
                message="指定されたanchorが現在のsourceに見つかりません。",
                evidence_revision=evidence_revision,
            )
        start_line = start_index + 1
        end_line = min(len(lines), start_line + MAX_PREVIEW_LINES - 1)
        truncated = end_line < len(lines)

    code = "\n".join(lines[start_line - 1 : end_line])
    if contains_secret_content(code):
        return source_preview_record(
            task_number,
            relative_path,
            anchor,
            status="secret-content",
            message="秘密情報らしき内容を検出したため本文を表示しません。",
            evidence_revision=evidence_revision,
        )

    code, preview_truncated = truncate_utf8(code, MAX_PREVIEW_BYTES)
    truncated = truncated or preview_truncated
    if remaining_bytes <= 0:
        return source_preview_record(
            task_number,
            relative_path,
            anchor,
            status="budget-exhausted",
            message="snapshotのsource preview上限に達したため本文を表示しません。",
            evidence_revision=evidence_revision,
        )
    code, total_truncated = truncate_utf8(code, remaining_bytes)
    truncated = truncated or total_truncated
    return source_preview_record(
        task_number,
        relative_path,
        anchor,
        status="resolved",
        message="",
        start_line=start_line,
        end_line=end_line,
        code=code,
        truncated=truncated,
        evidence_revision=evidence_revision,
    )


def extract_source_preview(
    task_number: str,
    reference: str,
    *,
    source_root: Path | None,
    allowed_prefixes: tuple[tuple[str, ...], ...],
    remaining_bytes: int,
) -> dict[str, object]:
    relative_path, anchor = split_source_reference(reference)
    if source_root is None:
        return source_preview_record(
            task_number,
            relative_path,
            anchor,
            status="source-root-unavailable",
            message="project rootを推定できません。--source-rootを指定してください。",
        )
    if not anchor:
        return source_preview_record(
            task_number,
            relative_path,
            anchor,
            status="source-denied",
            message="source anchorまたはline rangeが未指定です。",
        )

    candidate, status, message = validate_source_path(
        relative_path,
        source_root,
        allowed_prefixes,
    )
    if candidate is None:
        return source_preview_record(
            task_number,
            relative_path,
            anchor,
            status=status,
            message=message,
        )

    try:
        raw = candidate.read_bytes()
    except OSError:
        return source_preview_record(
            task_number,
            relative_path,
            anchor,
            status="source-unavailable",
            message="source fileを読み込めません。",
        )
    if b"\0" in raw:
        return source_preview_record(
            task_number,
            relative_path,
            anchor,
            status="source-denied",
            message="binary fileは表示対象にできません。",
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return source_preview_record(
            task_number,
            relative_path,
            anchor,
            status="source-denied",
            message="UTF-8ではないsource fileは表示できません。",
        )
    return preview_text_record(
        task_number,
        relative_path,
        anchor,
        text,
        remaining_bytes=remaining_bytes,
    )


def git_output(source_root: Path, args: list[str], *, text: bool = True) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
    command = ["git", *args]
    try:
        return subprocess.run(
            command,
            cwd=source_root,
            check=False,
            capture_output=True,
            text=text,
            timeout=GIT_SUBPROCESS_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            command,
            124,
            stdout="" if text else b"",
            stderr="git subprocess timed out" if text else b"git subprocess timed out",
        )


def resolve_git_commit(source_root: Path | None, ref: str | None) -> tuple[str | None, str]:
    if source_root is None or not ref:
        return None, "base refが未指定のためBeforeを確認できません。"
    result = git_output(
        source_root,
        ["rev-parse", "--verify", "--quiet", "--end-of-options", f"{ref}^{{commit}}"],
    )
    revision = result.stdout.strip() if isinstance(result.stdout, str) else ""
    if result.returncode != 0 or not GIT_SHA_RE.fullmatch(revision):
        return None, "base refをcommit SHAへ解決できません。"
    return revision, ""


def read_git_blob(
    source_root: Path,
    revision: str,
    relative_path: str,
    allowed_prefixes: tuple[tuple[str, ...], ...],
    cache: dict[tuple[str, str], tuple[bytes | None, str, str]] | None = None,
) -> tuple[bytes | None, str, str]:
    path_parts, status, message = validate_source_path_parts(
        relative_path,
        allowed_prefixes,
    )
    if path_parts is None:
        return None, status, message
    safe_path = "/".join(path_parts)
    key = (revision, safe_path)
    if cache is not None and key in cache:
        return cache[key]

    def cached(result: tuple[bytes | None, str, str]) -> tuple[bytes | None, str, str]:
        if cache is not None:
            cache[key] = result
        return result

    current_path, current_status, current_message = validate_source_path(
        relative_path,
        source_root,
        allowed_prefixes,
    )
    if current_path is None and current_status != "source-missing":
        return cached((None, current_status, current_message))
    if current_path is not None:
        try:
            current_text = current_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            current_text = ""
        if markdown_disallows_automation(current_text, relative_path):
            return cached((None, "source-denied", "automation_read: falseのため本文を取得しません。"))
    tree = git_output(
        source_root,
        ["ls-tree", "-z", revision, "--", safe_path],
        text=False,
    )
    if tree.returncode != 0 or not tree.stdout:
        return cached((None, "source-missing", "base ref内に参照先のsource fileが見つかりません。"))
    entry = bytes(tree.stdout).split(b"\0", 1)[0].decode("utf-8", errors="replace")
    meta, _, found_path = entry.partition("\t")
    parts = meta.split()
    if len(parts) < 3 or found_path != safe_path:
        return cached((None, "source-unavailable", "base refのtree entryを確認できません。"))
    mode, kind, object_id = parts[:3]
    if kind != "blob" or mode not in {"100644", "100755"}:
        return cached((None, "source-denied", "regular fileではないため表示できません。"))
    size = git_output(source_root, ["cat-file", "-s", object_id])
    try:
        byte_count = int(str(size.stdout).strip()) if size.returncode == 0 else -1
    except ValueError:
        byte_count = -1
    if byte_count < 0:
        return cached((None, "source-unavailable", "base refのblob sizeを確認できません。"))
    if byte_count > MAX_SOURCE_FILE_BYTES:
        return cached((None, "source-denied", "1MiBを超えるsource fileは読み込みません。"))
    blob = git_output(source_root, ["cat-file", "blob", object_id], text=False)
    if blob.returncode != 0:
        return cached((None, "source-unavailable", "base refのblobを読み込めません。"))
    return cached((bytes(blob.stdout), "", ""))


def extract_git_source_preview(
    task_number: str,
    reference: str,
    *,
    source_root: Path | None,
    allowed_prefixes: tuple[tuple[str, ...], ...],
    remaining_bytes: int,
    evidence_revision: str | None,
    base_ref_message: str,
    git_blob_cache: dict[tuple[str, str], tuple[bytes | None, str, str]] | None = None,
) -> dict[str, object]:
    relative_path, anchor = split_source_reference(reference)
    if evidence_revision is None or source_root is None:
        return source_preview_record(
            task_number,
            relative_path,
            anchor,
            status="base-ref-unavailable",
            message=base_ref_message or "base refを確認できません。",
        )
    if not anchor:
        return source_preview_record(
            task_number,
            relative_path,
            anchor,
            status="source-denied",
            message="source anchorまたはline rangeが未指定です。",
            evidence_revision=evidence_revision,
        )
    raw, status, message = read_git_blob(
        source_root,
        evidence_revision,
        relative_path,
        allowed_prefixes,
        git_blob_cache,
    )
    if raw is None:
        return source_preview_record(
            task_number,
            relative_path,
            anchor,
            status=status,
            message=message,
            evidence_revision=evidence_revision,
        )
    if b"\0" in raw:
        return source_preview_record(
            task_number,
            relative_path,
            anchor,
            status="source-denied",
            message="binary fileは表示対象にできません。",
            evidence_revision=evidence_revision,
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return source_preview_record(
            task_number,
            relative_path,
            anchor,
            status="source-denied",
            message="UTF-8ではないsource fileは表示できません。",
            evidence_revision=evidence_revision,
        )
    return preview_text_record(
        task_number,
        relative_path,
        anchor,
        text,
        remaining_bytes=remaining_bytes,
        evidence_revision=evidence_revision,
    )


def collect_source_previews(
    plan: str,
    *,
    source_root: Path | None,
    source_allow_prefixes: list[str] | None,
    base_ref: str | None = None,
    base_revision: str | None = None,
    base_ref_message: str = "",
    git_blob_cache: dict[tuple[str, str], tuple[bytes | None, str, str]] | None = None,
    plan_model: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    references = parse_source_preview_references(plan, plan_model)
    if not references:
        return []

    normalized_root = (
        source_root.expanduser().resolve(strict=False)
        if source_root is not None
        else None
    )
    allowed_prefixes = normalize_source_prefixes(source_allow_prefixes)
    previews: list[dict[str, object]] = []
    used_bytes = 0
    for task_number, reference in references:
        if len(previews) >= MAX_SOURCE_PREVIEW_COUNT or used_bytes >= MAX_TOTAL_PREVIEW_BYTES:
            break
        if base_ref:
            preview = extract_git_source_preview(
                task_number,
                reference,
                source_root=normalized_root,
                allowed_prefixes=allowed_prefixes,
                remaining_bytes=MAX_TOTAL_PREVIEW_BYTES - used_bytes,
                evidence_revision=base_revision,
                base_ref_message=base_ref_message,
                git_blob_cache=git_blob_cache,
            )
        else:
            preview = extract_source_preview(
                task_number,
                reference,
                source_root=normalized_root,
                allowed_prefixes=allowed_prefixes,
                remaining_bytes=MAX_TOTAL_PREVIEW_BYTES - used_bytes,
            )
        previews.append(preview)
        used_bytes += len(str(preview["code"]).encode("utf-8"))
    return previews


def invalid_ui_preview(task_number: str, message: str) -> dict[str, object]:
    return {"taskNumber": task_number, "id": "invalid-ui-preview", "status": "invalid", "message": message, "before": {"items": []}, "after": {"items": []}, "uncertainty": []}


def infer_ui_preview_base_ref(
    plan: str,
    plan_model: dict[str, object] | None = None,
) -> tuple[str | None, str]:
    """Use one LLM-recorded immutable SHA when the CLI did not supply a ref."""
    declared_refs: set[str] = set()
    for _task_number, _start, _end, body in iter_task_sections(plan, plan_model):
        for block in UI_PREVIEW_BLOCK_RE.finditer(body):
            try:
                root = json.loads(block.group(1))
            except json.JSONDecodeError:
                continue
            previews = root.get("previews") if isinstance(root, dict) else None
            if not isinstance(previews, list):
                continue
            for preview in previews:
                if not isinstance(preview, dict):
                    continue
                provenance = preview.get("provenance")
                before = provenance.get("before") if isinstance(provenance, dict) else None
                source = before.get("source") if isinstance(before, dict) else None
                if not isinstance(source, str) or not source.strip():
                    continue
                declared = before.get("baseRef")
                if not isinstance(declared, str) or not re.fullmatch(r"[0-9a-f]{40}", declared.strip()):
                    return None, "planのbaseRefは固定40桁commit SHAで記録してください。"
                declared_refs.add(declared.strip())
    if len(declared_refs) > 1:
        return None, "planに複数のbaseRefがあるため自動選択できません。"
    return (next(iter(declared_refs)), "") if declared_refs else (None, "")


def ensure_ui_keys(value: object, keys: set[str], path: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    unknown = sorted(set(value) - keys)
    if unknown:
        raise ValueError(f"{path} has unknown key")
    return value


def ui_text(value: object, path: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{path} must be a string")
    text = value.strip()
    if not text and not allow_empty:
        raise ValueError(f"{path} must not be empty")
    if len(text) > MAX_UI_TEXT_CHARS:
        raise ValueError(f"{path} exceeds {MAX_UI_TEXT_CHARS} chars")
    if RAW_HTML_RE.search(text) or EXTERNAL_URL_RE.search(text):
        raise ValueError(f"{path} contains raw HTML or external URL")
    return text


def ui_id(value: object, path: str) -> str:
    text = ui_text(value, path)
    if not STABLE_UI_ID_RE.fullmatch(text):
        raise ValueError(f"{path} must be a stable id")
    return text


def normalize_ui_items(value: object, path: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or len(value) > MAX_UI_ITEMS_PER_SIDE:
        raise ValueError(f"{path} must contain at most {MAX_UI_ITEMS_PER_SIDE} items")
    seen: set[str] = set()
    items: list[dict[str, object]] = []
    for index, raw_item in enumerate(value):
        item = ensure_ui_keys(
            raw_item,
            {"id", "label", "kind", "state", "change"},
            f"{path}[{index}]",
        )
        item_id = ui_id(item.get("id"), f"{path}[{index}].id")
        if item_id in seen:
            raise ValueError(f"{path}[{index}].id duplicates another item")
        seen.add(item_id)
        kind = ui_text(item.get("kind"), f"{path}[{index}].kind")
        change = ui_text(item.get("change"), f"{path}[{index}].change")
        if kind not in ALLOWED_UI_ITEM_KINDS:
            raise ValueError(f"{path}[{index}].kind is not allowed")
        if change not in ALLOWED_UI_CHANGES:
            raise ValueError(f"{path}[{index}].change is not allowed")
        clean: dict[str, object] = {
            "id": item_id,
            "label": ui_text(item.get("label"), f"{path}[{index}].label"),
            "kind": kind,
            "change": change,
        }
        if "state" in item:
            clean["state"] = ui_text(item["state"], f"{path}[{index}].state", allow_empty=True)
        items.append(clean)
    return items


def normalize_ui_side(value: object, path: str) -> dict[str, object]:
    side = ensure_ui_keys(value, {"items"}, path)
    return {"items": normalize_ui_items(side.get("items"), f"{path}.items")}


def normalize_ui_provenance(value: object, path: str) -> dict[str, object]:
    provenance = ensure_ui_keys(value, {"before", "after"}, path)
    before = ensure_ui_keys(
        provenance.get("before", {}),
        {"source", "baseRef", "observedLabels"},
        f"{path}.before",
    )
    after = ensure_ui_keys(provenance.get("after", {}), {"source"}, f"{path}.after")
    clean_before: dict[str, object] = {}
    if "source" in before:
        clean_before["source"] = ui_text(before["source"], f"{path}.before.source")
    if "baseRef" in before:
        clean_before["baseRef"] = ui_text(before["baseRef"], f"{path}.before.baseRef")
    labels = before.get("observedLabels", [])
    if not isinstance(labels, list) or len(labels) > MAX_UI_ITEMS_PER_SIDE:
        raise ValueError(f"{path}.before.observedLabels must be a bounded list")
    clean_before["observedLabels"] = [
        ui_text(label, f"{path}.before.observedLabels[{index}]")
        for index, label in enumerate(labels)
    ]
    clean_after = {"source": ui_text(after.get("source"), f"{path}.after.source")}
    return {"before": clean_before, "after": clean_after}


def normalize_ui_uncertainty(value: object, path: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_UI_ITEMS_PER_SIDE:
        raise ValueError(f"{path} must be a bounded list")
    return [ui_text(item, f"{path}[{index}]") for index, item in enumerate(value)]


def normalize_ui_preview_block(
    task_number: str,
    block: str,
    *,
    source_root: Path | None,
    allowed_prefixes: tuple[tuple[str, ...], ...],
    base_ref: str | None,
    base_revision: str | None,
    base_ref_message: str,
    git_blob_cache: dict[tuple[str, str], tuple[bytes | None, str, str]] | None,
) -> list[dict[str, object]]:
    if len(block.encode("utf-8")) > MAX_UI_PREVIEW_BLOCK_BYTES:
        raise ValueError("ui-preview-json block exceeds 16KiB")
    root = ensure_ui_keys(
        json.loads(block),
        {"version", "taskNumber", "previews"},
        "ui-preview-json",
    )
    if root.get("version") != 1 or str(root.get("taskNumber")) != task_number:
        raise ValueError("ui-preview-json version or taskNumber mismatch")
    previews = root.get("previews")
    if not isinstance(previews, list) or not previews or len(previews) > MAX_UI_PREVIEWS_PER_TASK:
        raise ValueError("ui-preview-json previews limit exceeded")

    clean_previews: list[dict[str, object]] = []
    seen_previews: set[str] = set()
    for index, raw_preview in enumerate(previews):
        preview = ensure_ui_keys(
            raw_preview,
            {"id", "title", "layout", "provenance", "before", "after", "uncertainty"},
            f"previews[{index}]",
        )
        preview_id = ui_id(preview.get("id"), f"previews[{index}].id")
        if preview_id in seen_previews:
            raise ValueError(f"previews[{index}].id duplicates another preview")
        seen_previews.add(preview_id)
        layout = ui_text(preview.get("layout"), f"previews[{index}].layout")
        if layout not in ALLOWED_UI_LAYOUTS:
            raise ValueError(f"previews[{index}].layout is not allowed")
        provenance = normalize_ui_provenance(preview.get("provenance"), f"previews[{index}].provenance")
        before = normalize_ui_side(preview.get("before"), f"previews[{index}].before")
        after = normalize_ui_side(preview.get("after"), f"previews[{index}].after")
        before_source = str(provenance["before"].get("source", ""))
        before_items = before["items"]
        if before_items and not before_source:
            raise ValueError(f"previews[{index}].before requires source provenance")
        if before_source and not before_source.startswith("repo:"):
            raise ValueError(f"previews[{index}].provenance.before.source must use repo:")
        declared_ref = str(provenance["before"].get("baseRef", ""))
        source = extract_git_source_preview(
            task_number,
            before_source,
            source_root=source_root,
            allowed_prefixes=allowed_prefixes,
            remaining_bytes=MAX_PREVIEW_BYTES,
            evidence_revision=base_revision,
            base_ref_message=base_ref_message,
            git_blob_cache=git_blob_cache,
        ) if before_source else source_preview_record(
            task_number,
            "",
            "",
            status="not-applicable",
            message="Before sourceは未指定です。",
        )
        labels = [
            str(item["label"]) for item in before_items
        ] + [str(label) for label in provenance["before"].get("observedLabels", [])]
        code = str(source.get("code", ""))
        status = "resolved"
        message = ""
        if before_items and not base_ref:
            status = "unverified"
            message = base_ref_message or "base refが未指定のためBeforeを確認できません。"
        elif declared_ref and base_ref and declared_ref != base_ref:
            status = "unverified"
            message = "planのbaseRefとCLI --base-refが一致しません。"
        elif before_items and (source.get("status") != "resolved" or not all(label in code for label in labels)):
            status = "unverified"
            message = str(source.get("message") or "Before labelをbase refのsourceで確認できません。")
        clean_previews.append(
            {
                "taskNumber": task_number,
                "id": preview_id,
                "title": ui_text(preview.get("title"), f"previews[{index}].title"),
                "layout": layout,
                "status": status,
                "message": message,
                "evidenceRevision": base_revision or "",
                "provenance": provenance,
                "source": source,
                "before": before if status == "resolved" else {"items": []},
                "after": after,
                "uncertainty": normalize_ui_uncertainty(
                    preview.get("uncertainty", []),
                    f"previews[{index}].uncertainty",
                ),
            }
        )
    return clean_previews


def collect_ui_previews(
    plan: str,
    *,
    source_root: Path | None,
    source_allow_prefixes: list[str] | None,
    base_ref: str | None,
    base_revision: str | None,
    base_ref_message: str,
    git_blob_cache: dict[tuple[str, str], tuple[bytes | None, str, str]] | None = None,
    plan_model: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    task_sections = iter_task_sections(plan, plan_model)
    if not task_sections and not UI_PREVIEW_BLOCK_RE.search(plan):
        return []
    normalized_root = (
        source_root.expanduser().resolve(strict=False)
        if source_root is not None
        else None
    )
    allowed_prefixes = normalize_source_prefixes(source_allow_prefixes)
    previews: list[dict[str, object]] = []
    used_bytes = 0
    covered: set[tuple[int, int]] = set()
    for task_number, start, end, body in task_sections:
        if len(previews) >= MAX_UI_PREVIEW_COUNT or used_bytes >= MAX_TOTAL_UI_PREVIEW_BYTES:
            break
        blocks = list(UI_PREVIEW_BLOCK_RE.finditer(body))
        for block in blocks:
            covered.add((start + block.start(), start + block.end()))
        if len(blocks) > 1:
            preview = invalid_ui_preview(task_number, "Task内のui-preview-jsonは1件だけ許可されています。")
            previews.append(preview)
            used_bytes += len(json.dumps(preview, ensure_ascii=False).encode("utf-8"))
            continue
        if not blocks:
            continue
        try:
            candidates = (
                normalize_ui_preview_block(
                    task_number,
                    blocks[0].group(1),
                    source_root=normalized_root,
                    allowed_prefixes=allowed_prefixes,
                    base_ref=base_ref,
                    base_revision=base_revision,
                    base_ref_message=base_ref_message,
                    git_blob_cache=git_blob_cache,
                )
            )
        except (ValueError, json.JSONDecodeError) as error:
            candidates = [invalid_ui_preview(task_number, str(error))]
        for preview in candidates:
            preview_bytes = len(json.dumps(preview, ensure_ascii=False).encode("utf-8"))
            if len(previews) >= MAX_UI_PREVIEW_COUNT or used_bytes + preview_bytes > MAX_TOTAL_UI_PREVIEW_BYTES:
                break
            previews.append(preview)
            used_bytes += preview_bytes
    for block in UI_PREVIEW_BLOCK_RE.finditer(plan):
        if len(previews) >= MAX_UI_PREVIEW_COUNT or used_bytes >= MAX_TOTAL_UI_PREVIEW_BYTES:
            break
        span = (block.start(), block.end())
        if not any(start <= span[0] and span[1] <= end for start, end in covered):
            preview = invalid_ui_preview("", "Task外のui-preview-jsonは許可されていません。")
            preview_bytes = len(json.dumps(preview, ensure_ascii=False).encode("utf-8"))
            if used_bytes + preview_bytes > MAX_TOTAL_UI_PREVIEW_BYTES:
                break
            previews.append(preview)
            used_bytes += preview_bytes
    return previews


def validate_declared_ui_previews(
    plan: str,
    previews: list[dict[str, object]],
    plan_model: dict[str, object] | None = None,
) -> None:
    declared = {
        task_number
        for task_number, _start, _end, body in iter_task_sections(plan, plan_model)
        if UI_CHANGE_MARKER_RE.search(body)
    }
    if not declared:
        return
    _inferred_ref, inferred_message = infer_ui_preview_base_ref(plan, plan_model)
    if inferred_message:
        raise ValueError(inferred_message)
    previews_by_task: dict[str, list[dict[str, object]]] = {}
    for preview in previews:
        previews_by_task.setdefault(str(preview.get("taskNumber", "")), []).append(preview)
    invalid = sorted(
        task_number
        for task_number in declared
        if not previews_by_task.get(task_number)
        or any(item.get("status") == "invalid" for item in previews_by_task[task_number])
    )
    if invalid:
        raise ValueError(
            "UI変更Taskのui-preview-jsonが未作成または不正です: " + ", ".join(invalid)
        )


def artifact_type(path: Path) -> str:
    suffix = path.suffix.lower().lstrip(".")
    return suffix or "file"


def is_temporary_file(path: Path) -> bool:
    return path.name.endswith(".tmp")


def collect_artifacts(task_dir: Path, output: Path | None = None) -> list[dict[str, object]]:
    artifacts: list[dict[str, object]] = []
    excluded_paths: set[Path] = set()
    if output is not None:
        excluded_paths.add(output.resolve(strict=False))
        excluded_paths.add(output.with_name("roadmap-snapshot.json").resolve(strict=False))

    for current, directory_names, file_names in os.walk(task_dir, followlinks=False):
        current_dir = Path(current)
        directory_names[:] = sorted(
            name for name in directory_names if not (current_dir / name).is_symlink()
        )
        for name in sorted(file_names):
            path = current_dir / name
            if path.is_symlink() or name in OUTPUT_NAMES or is_temporary_file(path):
                continue
            if path.resolve(strict=False) in excluded_paths:
                continue
            try:
                file_stat = path.stat(follow_symlinks=False)
            except OSError:
                continue
            if not stat.S_ISREG(file_stat.st_mode):
                continue
            relative_path = path.relative_to(task_dir).as_posix()
            artifacts.append(
                {
                    "name": path.name,
                    "path": relative_path,
                    "type": artifact_type(path),
                    "size": file_stat.st_size,
                    "modifiedAt": datetime.fromtimestamp(
                        file_stat.st_mtime, timezone.utc
                    ).isoformat(),
                }
            )

    artifacts.sort(key=lambda item: str(item["path"]))
    return artifacts


def build_fingerprint(
    files: dict[str, str],
    artifacts: list[dict[str, object]],
    source_previews: list[dict[str, object]] | None = None,
    ui_previews: list[dict[str, object]] | None = None,
    codemap_state: dict[str, object] | None = None,
    plan_model: dict[str, object] | None = None,
    timeline: list[dict[str, object]] | None = None,
) -> str:
    payload = {
        "files": files,
        "artifacts": artifacts,
        "sourcePreviews": source_previews or [],
        "uiPreviews": ui_previews or [],
        "codemap": codemap_state or {},
        "plan": plan_model or {},
        "timeline": timeline or [],
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _log_timestamp_and_title(raw_title: str) -> tuple[str | None, str]:
    """Extract a sortable timestamp from a dated log heading."""
    title = raw_title.strip()
    iso_match = LOG_ISO_DATE_RE.match(title)
    if iso_match:
        timestamp = iso_match.group("date")
        if iso_match.group("time"):
            timestamp += "T" + iso_match.group("time")
        remainder = title[iso_match.end() :].lstrip(" -–—:：")
        return timestamp, remainder or title

    jp_match = LOG_JP_DATE_RE.match(title)
    if jp_match:
        timestamp = (
            f"{jp_match.group('year')}-{int(jp_match.group('month')):02d}-"
            f"{int(jp_match.group('day')):02d}"
        )
        if jp_match.group("hour"):
            timestamp += (
                f"T{int(jp_match.group('hour')):02d}:{jp_match.group('minute')}"
            )
            if jp_match.group("second"):
                timestamp += f":{jp_match.group('second')}"
        remainder = title[jp_match.end() :].lstrip(" -–—:：")
        return timestamp, remainder or title
    return None, title


def _timeline_summary(body: str, title: str, *, limit: int = 320) -> str:
    compact = " ".join(
        re.sub(r"```[\s\S]*?```", " ", body).split()
    ).strip()
    summary = compact or title
    if len(summary) <= limit:
        return summary
    return summary[: limit - 1].rstrip() + "…"


def parse_log_timeline(log_text: str, *, log_source: str = "05_log.md") -> list[dict[str, object]]:
    """Turn dated headings in 05_log.md into stable, source-addressable events.

    This is intentionally a log parser, not a second Plan/Task parser. Plan
    headings are handled exclusively by ``roadmap_plan_contract``.
    """
    headings = list(LOG_HEADING_RE.finditer(log_text))
    events: list[dict[str, object]] = []
    occurrence: dict[tuple[str, str], int] = {}
    for index, heading in enumerate(headings):
        timestamp, title = _log_timestamp_and_title(heading.group(2))
        if timestamp is None:
            continue
        level = len(heading.group(1))
        next_heading = next(
            (
                candidate
                for candidate in headings[index + 1 :]
                if len(candidate.group(1)) <= level
            ),
            None,
        )
        end = next_heading.start() if next_heading else len(log_text)
        body = log_text[heading.end() : end].strip()
        line_start = log_text.count("\n", 0, heading.start()) + 1
        line_end = max(
            line_start,
            log_text.count("\n", 0, max(heading.start(), end - 1)) + 1,
        )
        key = (timestamp, title)
        ordinal = occurrence.get(key, 0)
        occurrence[key] = ordinal + 1
        event_key = "\0".join((log_source, timestamp, title, str(ordinal)))
        phase_match = re.search(
            r"(?:Phase|フェーズ)\s*([0-9]+(?:\.[0-9]+)?)",
            " ".join((title, body[:512])),
            re.IGNORECASE,
        )
        event: dict[str, object] = {
            "id": "timeline-" + hashlib.sha256(event_key.encode("utf-8")).hexdigest()[:16],
            "timestamp": timestamp,
            "time": timestamp,
            "title": title,
            "summary": _timeline_summary(body, title),
            "body": body,
            "phase": phase_match.group(1) if phase_match else "",
            "source": {
                "file": log_source,
                "lineStart": line_start,
                "lineEnd": line_end,
            },
        }
        events.append(event)

    # Keep chronological order while preserving source order for identical or
    # undated values. Dated events are the only entries emitted today, but the
    # key remains explicit for a future optional log event type.
    events.sort(
        key=lambda event: (
            str(event.get("timestamp") or "9999-99-99"),
            int(event.get("source", {}).get("lineStart", 0))
            if isinstance(event.get("source"), dict)
            else 0,
        )
    )
    return events


def infer_title(files: dict[str, str], task_dir: Path) -> str:
    directory_title = re.sub(r"^\d{6,8}[_-]+", "", task_dir.name)
    directory_title = re.sub(r"[_-]+", " ", directory_title).strip()
    if directory_title:
        return directory_title

    for name in ("30_plan.md", "00_spec.md", "05_log.md"):
        text = files.get(name, "")
        for line in text.splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                if title:
                    return title
    return "Roadmap"


def load_task_meta(task_dir: Path) -> dict[str, object]:
    path = task_dir / "task-meta.json"
    if not path.is_file() or path.is_symlink():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def load_codemap_state(task_dir: Path, source_root: Path) -> dict[str, object]:
    source = task_dir / "codemap.source.json"
    map_path = task_dir / "codemap.json"
    lock_path = task_dir / "codemap.lock"
    code_change = load_task_meta(task_dir).get("code_change") is True
    if not source.is_file() and not map_path.is_file() and not lock_path.is_file():
        if code_change:
            return {
                "status": "missing",
                "message": "Codemap is required for this code-change task. Run refresh, then check.",
            }
        return {"status": "not-applicable"}
    if not source.is_file() or not map_path.is_file() or not lock_path.is_file():
        return {"status": "missing", "message": "Codemap artifact is incomplete."}

    module_path = Path(__file__).with_name("generate-codemap.py")
    spec = importlib.util.spec_from_file_location("task_codemap_checker", module_path)
    if spec is None or spec.loader is None:
        return {"status": "error", "message": "Codemap checker could not be loaded."}
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        result = module.check(source_root, artifact_dir=task_dir)
        snapshot = json.loads(map_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RuntimeError) as error:
        message = str(error)
        if "missing" in message.lower():
            status = "missing"
        elif "mismatch" in message.lower():
            status = "mismatch"
        else:
            status = "stale"
        return {"status": status, "message": message}
    counts = snapshot.get("counts")
    if isinstance(counts, dict) and int(counts.get("unknown", 0) or 0) > 0:
        return {
            "status": "insufficient",
            "message": "Codemap still contains unknown relationships.",
            "snapshot": snapshot,
        }
    return {
        "status": str(result.get("status", "fresh")),
        "snapshot": snapshot,
    }


def build_snapshot(
    task_dir: Path,
    output: Path | None = None,
    *,
    source_root: Path | None = None,
    source_allow_prefixes: list[str] | None = None,
    base_ref: str | None = None,
) -> dict[str, object]:
    files, sources = read_files(task_dir)
    if not files:
        raise ValueError(f"no roadmap source files found in {task_dir}")
    artifacts = collect_artifacts(task_dir, output)
    effective_source_root = source_root or infer_source_root(task_dir) or task_dir.parent
    plan = files.get("30_plan.md", "")
    plan_model = parse_plan_model(
        plan,
        files.get("40_progress.md", ""),
        plan_source=str(task_dir / "30_plan.md"),
        progress_source=str(task_dir / "40_progress.md"),
    )
    log_source = str(task_dir / "05_log.md")
    timeline = parse_log_timeline(files.get("05_log.md", ""), log_source=log_source)
    inferred_base_ref, inferred_base_ref_message = infer_ui_preview_base_ref(
        plan,
        plan_model,
    )
    effective_base_ref = base_ref or inferred_base_ref
    base_revision, resolved_base_ref_message = resolve_git_commit(
        effective_source_root,
        effective_base_ref,
    ) if effective_base_ref else (None, "")
    base_ref_message = resolved_base_ref_message or inferred_base_ref_message
    git_blob_cache: dict[tuple[str, str], tuple[bytes | None, str, str]] = {}
    source_previews = collect_source_previews(
        plan,
        source_root=effective_source_root,
        source_allow_prefixes=source_allow_prefixes,
        base_ref=effective_base_ref,
        base_revision=base_revision,
        base_ref_message=base_ref_message,
        git_blob_cache=git_blob_cache,
        plan_model=plan_model,
    )
    ui_previews = collect_ui_previews(
        plan,
        source_root=effective_source_root,
        source_allow_prefixes=source_allow_prefixes,
        base_ref=effective_base_ref,
        base_revision=base_revision,
        base_ref_message=base_ref_message,
        git_blob_cache=git_blob_cache,
        plan_model=plan_model,
    )
    validate_declared_ui_previews(plan, ui_previews, plan_model)
    codemap_state = load_codemap_state(task_dir, effective_source_root)
    fingerprint = build_fingerprint(
        files,
        artifacts,
        source_previews,
        ui_previews,
        codemap_state,
        plan_model,
        timeline,
    )
    snapshot: dict[str, object] = {
        "version": 1,
        "title": infer_title(files, task_dir),
        "taskDir": str(task_dir),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "fingerprint": fingerprint,
        "planSourceHash": plan_model.get("sourceHash", ""),
        "generationId": "roadmap-" + hashlib.sha256(
            ("v2\0" + fingerprint).encode("utf-8")
        ).hexdigest()[:20],
        "files": files,
        "sources": sources,
        "artifacts": artifacts,
        "sourcePreviews": source_previews,
        "uiPreviews": ui_previews,
        "codemapStatus": codemap_state["status"],
        "plan": plan_model,
        "timeline": timeline,
        "timelineSource": {
            "file": log_source,
            "sourceHash": hashlib.sha256(
                files.get("05_log.md", "").encode("utf-8")
            ).hexdigest(),
        },
    }
    codemap_snapshot = codemap_state.get("snapshot")
    if isinstance(codemap_snapshot, dict):
        snapshot["codemap"] = codemap_snapshot
    codemap_message = codemap_state.get("message")
    if isinstance(codemap_message, str) and codemap_message:
        snapshot["codemapMessage"] = codemap_message
    return snapshot


def render_html(snapshot: dict[str, object]) -> str:
    template = TEMPLATE.read_text()
    if PLACEHOLDER not in template:
        raise ValueError(f"placeholder not found in {TEMPLATE}")
    payload = json.dumps(snapshot, ensure_ascii=False).replace("</", "<\\/")
    return apply_roadmap_static_contract_meta(template.replace(PLACEHOLDER, payload, 1))


def apply_roadmap_static_contract_meta(html: str) -> str:
    additions: list[str] = []
    if not ARTIFACT_KIND_META_RE.search(html):
        additions.append('  <meta name="artifact-kind" content="html-plan">')
    if not CSP_META_RE.search(html):
        additions.append(
            f'  <meta http-equiv="Content-Security-Policy" content="{ROADMAP_CSP}">'
        )
    if not additions:
        return html
    match = HEAD_OPEN_RE.search(html)
    if not match:
        return html
    return html[: match.end()] + "\n" + "\n".join(additions) + html[match.end() :]


def validate_roadmap_html(html: str, output: Path) -> None:
    spec = importlib.util.spec_from_file_location("html_artifact_contract", HTML_CONTRACT)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load HTML artifact contract: {HTML_CONTRACT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    try:
        module.assert_valid_html(
            html,
            profile_name="roadmap-generated",
            path=str(output),
            expected_artifact_kind="html-plan",
        )
    except Exception as error:
        raise ValueError(f"roadmap output failed static HTML contract: {error}") from error


def read_json_snapshot(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def read_html_snapshot(path: Path) -> dict[str, object] | None:
    try:
        html = path.read_text()
    except OSError:
        return None
    match = EMBEDDED_SNAPSHOT_RE.search(html)
    if not match:
        return None
    try:
        value = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def previous_generated_at(
    fingerprint: str, candidates: list[dict[str, object] | None]
) -> str | None:
    for candidate in candidates:
        if not candidate or candidate.get("fingerprint") != fingerprint:
            continue
        generated_at = candidate.get("generatedAt")
        if isinstance(generated_at, str) and generated_at:
            return generated_at
    return None


def write_outputs(
    task_dir: Path,
    output: Path,
    write_json: bool,
    *,
    source_root: Path | None = None,
    source_allow_prefixes: list[str] | None = None,
    base_ref: str | None = None,
    thread_id: str | None = None,
    session_id: str | None = None,
    task_state: str | None = None,
) -> dict[str, object]:
    json_path = output.with_name("roadmap-snapshot.json")
    effective_source_root = source_root or infer_source_root(task_dir) or task_dir.parent
    ensure_task_meta(
        task_dir,
        effective_source_root,
        thread_id=thread_id,
        session_id=session_id,
        task_state=task_state,
    )
    snapshot = build_snapshot(
        task_dir,
        output=output,
        source_root=source_root,
        source_allow_prefixes=source_allow_prefixes,
        base_ref=base_ref,
    )
    previous_timestamp = previous_generated_at(
        str(snapshot["fingerprint"]),
        [
            read_html_snapshot(output),
            read_json_snapshot(json_path) if write_json else None,
        ],
    )
    if previous_timestamp:
        snapshot["generatedAt"] = previous_timestamp

    rendered_html = render_html(snapshot)
    validate_roadmap_html(rendered_html, output)
    if write_json:
        json_text = json.dumps(snapshot, ensure_ascii=False, indent=2)
        publish_output_pair(
            output,
            rendered_html,
            json_path,
            json_text,
        )
    else:
        write_text_if_changed(output, rendered_html)

    return snapshot


def watch_outputs(
    task_dir: Path,
    output: Path,
    interval: float,
    stop: threading.Event,
    *,
    source_root: Path | None = None,
    source_allow_prefixes: list[str] | None = None,
    base_ref: str | None = None,
) -> None:
    while not stop.is_set():
        try:
            write_outputs(
                task_dir,
                output,
                write_json=True,
                source_root=source_root,
                source_allow_prefixes=source_allow_prefixes,
                base_ref=base_ref,
            )
        except Exception as exc:  # pragma: no cover - visible operator feedback
            print(f"watch update failed: {exc}", file=sys.stderr, flush=True)
        stop.wait(interval)


def serve_output(output: Path, host: str, port: int, open_browser: bool) -> int:
    directory = output.parent
    handler = functools.partial(RoadmapHTTPRequestHandler, directory=str(directory))
    server = http.server.ThreadingHTTPServer((host, port), handler)
    actual_host, actual_port = server.server_address[:2]
    url = f"http://{actual_host}:{actual_port}/{output.name}"
    print(url, flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping roadmap server", file=sys.stderr)
    finally:
        server.server_close()
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a browser-readable roadmap.html from a Codex task memory directory."
    )
    parser.add_argument("task_dir", nargs="?", help="Path to .local/memory/<task>")
    parser.add_argument(
        "--hub",
        action="store_true",
        help="Open the Roadmap Task Hub instead of a single task roadmap.",
    )
    parser.add_argument(
        "--memory-root",
        action="append",
        default=[],
        help="Memory root to discover in --hub mode. May be repeated.",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Output HTML path. Defaults to <task_dir>/roadmap.html.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Write roadmap-snapshot.json next to the HTML as well.",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Serve the generated HTML over local HTTP. Defaults to an OS-assigned free port.",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Keep regenerating roadmap.html and roadmap-snapshot.json until interrupted.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host for --serve. Defaults to 127.0.0.1.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Port for --serve. Defaults to 0, letting the OS choose a free port.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=2.0,
        help="Seconds between --watch refreshes. Defaults to 2.0.",
    )
    parser.add_argument(
        "--source-root",
        help=(
            "Project root used to resolve explicit repo: source previews. "
            "Defaults to the project containing .local/memory/<task>."
        ),
    )
    parser.add_argument(
        "--source-allow-prefix",
        action="append",
        default=[],
        help=(
            "Additional relative source prefix allowed for repo: previews. "
            "May be repeated."
        ),
    )
    parser.add_argument(
        "--base-ref",
        help=(
            "Optional Git ref override for source-backed UI Before previews and source previews. "
            "Without it, one immutable SHA declared by the plan is used automatically."
        ),
    )
    parser.add_argument("--thread-id", help="Bind task-meta.json to a Codex thread ID.")
    parser.add_argument("--session-id", help="Bind task-meta.json to a runtime session ID.")
    parser.add_argument(
        "--task-state",
        choices=("active", "waiting", "verifying", "completed", "archived"),
        help="Update the machine-owned task lifecycle state.",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="Open the generated file or local server URL in the default browser.",
    )
    args = parser.parse_args(argv)
    if args.hub and args.task_dir:
        parser.error("task_dir cannot be used with --hub")
    if not args.hub and not args.task_dir:
        parser.error("task_dir is required unless --hub is used")
    return args


def run_task_hub(
    memory_roots: list[Path],
    *,
    host: str,
    port: int,
    open_browser: bool,
) -> int:
    hub_path = ROOT / "scripts" / "roadmap_task_hub.py"
    spec = importlib.util.spec_from_file_location("roadmap_task_hub", hub_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load Task Hub backend: {hub_path}")
    hub = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = hub
    spec.loader.exec_module(hub)
    return hub.run_task_hub(
        memory_roots,
        host=host,
        port=port,
        open_browser=open_browser,
    )


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if args.hub:
        return run_task_hub(
            [Path(root).expanduser().resolve() for root in args.memory_root],
            host=args.host,
            port=args.port,
            open_browser=args.open,
        )

    task_dir = Path(args.task_dir).expanduser().resolve()
    if not task_dir.is_dir():
        print(f"task_dir is not a directory: {task_dir}", file=sys.stderr)
        return 2

    output = Path(args.output).expanduser().resolve() if args.output else task_dir / "roadmap.html"
    source_root = (
        Path(args.source_root).expanduser().resolve()
        if args.source_root
        else None
    )
    write_json = args.json or args.serve or args.watch
    write_outputs(
        task_dir,
        output,
        write_json=write_json,
        source_root=source_root,
        source_allow_prefixes=args.source_allow_prefix,
        base_ref=args.base_ref,
        thread_id=args.thread_id,
        session_id=args.session_id,
        task_state=args.task_state,
    )

    print(output)
    if args.serve:
        stop = threading.Event()
        thread = None
        if args.watch:
            thread = threading.Thread(
                target=watch_outputs,
                args=(task_dir, output, args.interval, stop),
                kwargs={
                    "source_root": source_root,
                    "source_allow_prefixes": args.source_allow_prefix,
                    "base_ref": args.base_ref,
                },
                daemon=True,
            )
            thread.start()
        try:
            return serve_output(output, args.host, args.port, args.open)
        finally:
            stop.set()
            if thread:
                thread.join(timeout=1)

    if args.watch:
        stop = threading.Event()
        try:
            watch_outputs(
                task_dir,
                output,
                args.interval,
                stop,
                source_root=source_root,
                source_allow_prefixes=args.source_allow_prefix,
                base_ref=args.base_ref,
            )
        except KeyboardInterrupt:
            print("\nstopping roadmap watch", file=sys.stderr)
        return 0

    if args.open:
        webbrowser.open(output.as_uri())

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
