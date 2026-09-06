#!/usr/bin/env python3
"""Validate and index source-backed UI preview mocks in a canonical HTML plan.

Version 1 UI previews are item-based and remain owned by the legacy roadmap
generator.  Version 2 deliberately carries only metadata: the actual Before
and After mock markup stays in the task's canonical HTML DOM and is addressed
by stable element ids.  This module checks that relationship and verifies an
existing Before source through the generator's read-only source helpers.  It
never renders, copies, or reconstructs mock HTML.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


STABLE_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
TASK_ID_RE = re.compile(r"^(?:task[-_ ]*)?(\d+(?:\.\d+)?)$", re.IGNORECASE)
SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
REPO_SOURCE_RE = re.compile(r"^repo:[^\s#]+#[^\s#]+$")
MAX_PREVIEWS_PER_TASK = 3
MAX_TOTAL_PREVIEWS = 24
MAX_UNCERTAINTY = 24
MAX_TEXT_CHARS = 512
MAX_SOURCE_CHARS = 2048
MAX_SOURCE_BYTES = 64 * 1024


def _error(path: str, message: str) -> ValueError:
    return ValueError(f"{path}: {message}")


def _object(value: object, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _error(path, "must be an object")
    return value


def _keys(value: dict[str, Any], allowed: set[str], path: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise _error(path, f"unknown key: {unknown[0]}")


def _text(value: object, path: str, *, limit: int = MAX_TEXT_CHARS) -> str:
    if not isinstance(value, str):
        raise _error(path, "must be a string")
    result = value.strip()
    if not result:
        raise _error(path, "must not be empty")
    if len(result) > limit:
        raise _error(path, f"exceeds {limit} characters")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in result):
        raise _error(path, "contains a control character")
    if "<" in result or ">" in result:
        raise _error(path, "must not contain HTML")
    if re.search(r"(?i)(?:https?:)?//|javascript\s*:", result):
        raise _error(path, "must not contain an external or executable URL")
    return result


def _optional_text(value: object, path: str, *, limit: int = MAX_TEXT_CHARS) -> str | None:
    if value is None:
        return None
    return _text(value, path, limit=limit)


def _anchor(value: object, path: str, *, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    result = _text(value, path, limit=64)
    if not STABLE_ID_RE.fullmatch(result):
        raise _error(path, "must be a stable DOM id")
    return result


def _uncertainty(value: object, path: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_UNCERTAINTY:
        raise _error(path, f"must contain at most {MAX_UNCERTAINTY} entries")
    return [_text(item, f"{path}[{index}]") for index, item in enumerate(value)]


def _visible_markup(node: dict[str, Any]) -> bool:
    """Return whether an indexed mock has meaningful content to display."""
    text = node.get("text")
    if isinstance(text, str) and text.strip():
        return True
    for child in node.get("children", []):
        if isinstance(child, str) and child.strip():
            return True
        if isinstance(child, dict) and _visible_markup(child):
            return True
    # An embedded image or a leaf SVG shape is still visible markup even when
    # it has no text descendants.
    return str(node.get("tag", "")).casefold() in {
        "img", "svg", "path", "circle", "ellipse", "line", "polygon", "polyline", "rect",
    }


def _task_nodes(plan_document: dict[str, Any]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[tuple[str, dict[str, Any]]]]]:
    nodes = plan_document.get("nodes")
    if not isinstance(nodes, list):
        raise _error("planDocument.nodes", "must be a list")
    tasks: dict[str, list[dict[str, Any]]] = {}
    anchors: dict[str, list[tuple[str, dict[str, Any]]]] = {}

    def visit(node: dict[str, Any], current_task: str | None) -> None:
        attrs = node.get("attrs", {})
        if not isinstance(attrs, dict):
            raise _error("planDocument.node.attrs", "must be an object")
        raw_task = attrs.get("data-task-id")
        if raw_task is not None:
            if current_task is not None:
                raise _error("planDocument", "nested Task DOM is not allowed")
            task_match = TASK_ID_RE.fullmatch(str(raw_task).strip())
            if task_match is None:
                raise _error("planDocument.data-task-id", "must use a numeric Task id")
            current_task = task_match.group(1)
            tasks.setdefault(current_task, []).append(node)
        raw_id = attrs.get("id")
        if raw_id is not None:
            identifier = str(raw_id)
            anchors.setdefault(identifier, []).append((current_task or "", node))
        for child in node.get("children", []):
            if isinstance(child, dict):
                visit(child, current_task)

    for node in nodes:
        if not isinstance(node, dict):
            continue
        visit(node, None)
    return tasks, anchors


def _normalise_prefixes(generator: object, values: list[str] | tuple[str, ...] | None) -> object:
    normalizer = getattr(generator, "normalize_source_prefixes", None)
    if callable(normalizer):
        return normalizer(list(values) if values is not None else None)
    return tuple(values or ())


def _source_result(
    generator: object,
    task_number: str,
    reference: str,
    *,
    source_root: Path,
    allowed_prefixes: object,
    revision: str,
) -> dict[str, Any]:
    helper = getattr(generator, "extract_git_source_preview", None)
    if not callable(helper):
        raise _error("provenance.before.source", "generator source helper is unavailable")
    kwargs: dict[str, Any] = {
        "source_root": source_root,
        "allowed_prefixes": allowed_prefixes,
        "remaining_bytes": MAX_SOURCE_BYTES,
        "evidence_revision": revision,
        "base_ref_message": "",
        # v1 previews intentionally stay tiny; a v2 provenance range must be
        # large enough to verify every declared observed label in its selected
        # source span.  The helper bounds these values at 256 lines/64 KiB.
        "max_lines": 256,
        "max_bytes": MAX_SOURCE_BYTES,
    }
    try:
        result = helper(task_number, reference, **kwargs)
    except Exception as exc:  # adapter errors must remain explicit to callers
        raise _error("provenance.before.source", f"source verification failed: {exc}") from exc
    if not isinstance(result, dict):
        raise _error("provenance.before.source", "source helper returned an invalid result")
    status = str(result.get("status", ""))
    if status != "resolved":
        message = str(result.get("message") or "base ref source is unavailable")
        raise _error("provenance.before.source", f"{status or 'unavailable'}: {message}")
    code = result.get("code")
    if not isinstance(code, str) or not code.strip():
        raise _error("provenance.before.source", "verified source has no readable excerpt")
    if len(code.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise _error("provenance.before.source", "verified source excerpt exceeds the byte limit")
    if result.get("truncated") is True:
        raise _error("provenance.before.source", "verified source excerpt is truncated")
    return result


def _normalise_provenance(
    raw: object,
    path: str,
    *,
    cli_base_ref: str | None,
) -> tuple[dict[str, Any], str | None, list[str], str]:
    provenance = _object(raw, path)
    _keys(provenance, {"before", "after"}, path)
    before = _object(provenance.get("before", {}), f"{path}.before")
    after = _object(provenance.get("after"), f"{path}.after")
    _keys(before, {"source", "baseRef", "observedLabels"}, f"{path}.before")
    _keys(after, {"source"}, f"{path}.after")

    source = _optional_text(before.get("source"), f"{path}.before.source", limit=MAX_SOURCE_CHARS)
    if source is not None and not REPO_SOURCE_RE.fullmatch(source):
        raise _error(f"{path}.before.source", "must use repo:<path>#<anchor>")
    declared_ref = _optional_text(before.get("baseRef"), f"{path}.before.baseRef", limit=40)
    if declared_ref is not None and not SHA40_RE.fullmatch(declared_ref):
        raise _error(f"{path}.before.baseRef", "must be a fixed 40-character commit SHA")
    if cli_base_ref is not None and not SHA40_RE.fullmatch(cli_base_ref):
        raise _error("base_ref", "must be a fixed 40-character commit SHA")
    if declared_ref and cli_base_ref and declared_ref != cli_base_ref:
        raise _error(path, "plan baseRef does not match CLI base_ref")

    labels = before.get("observedLabels", [])
    if not isinstance(labels, list) or len(labels) > MAX_PREVIEWS_PER_TASK * 8:
        raise _error(f"{path}.before.observedLabels", "must be a bounded list")
    clean_labels = [_text(item, f"{path}.before.observedLabels[{index}]") for index, item in enumerate(labels)]
    if len(set(clean_labels)) != len(clean_labels):
        raise _error(f"{path}.before.observedLabels", "must not contain duplicates")
    if source is None and clean_labels:
        raise _error(f"{path}.before.observedLabels", "requires Before source provenance")
    after_source = _text(after.get("source"), f"{path}.after.source", limit=MAX_SOURCE_CHARS)
    clean_before: dict[str, Any] = {"observedLabels": clean_labels}
    if source is not None:
        clean_before["source"] = source
    if declared_ref is not None:
        clean_before["baseRef"] = declared_ref
    elif source is not None and cli_base_ref is not None:
        # A caller-supplied fixed revision is still part of the resulting
        # evidence, even when the authoring block leaves baseRef implicit.
        clean_before["baseRef"] = cli_base_ref
    clean = {"before": clean_before, "after": {"source": after_source}}
    return clean, declared_ref, clean_labels, after_source


def _normalise_preview(
    task_number: str,
    raw: object,
    path: str,
    *,
    task_anchors: dict[str, list[tuple[str, dict[str, Any]]]],
    allowed_base_ref: str | None,
    generator: object,
    source_root: Path | None,
    allowed_prefixes: object,
) -> dict[str, Any]:
    preview = _object(raw, path)
    _keys(preview, {"id", "title", "provenance", "before", "after", "uncertainty"}, path)
    preview_id = _anchor(preview.get("id"), f"{path}.id")
    assert preview_id is not None
    title = _text(preview.get("title"), f"{path}.title")
    provenance, declared_ref, labels, _after_source = _normalise_provenance(
        preview.get("provenance"), f"{path}.provenance", cli_base_ref=allowed_base_ref
    )
    before = _object(preview.get("before"), f"{path}.before")
    after = _object(preview.get("after"), f"{path}.after")
    _keys(before, {"anchor"}, f"{path}.before")
    _keys(after, {"anchor"}, f"{path}.after")
    before_anchor = _anchor(before.get("anchor"), f"{path}.before.anchor", allow_none=True)
    after_anchor = _anchor(after.get("anchor"), f"{path}.after.anchor")
    assert after_anchor is not None
    if before_anchor is not None and before_anchor == after_anchor:
        raise _error(path, "Before and After anchors must be distinct")
    if before_anchor is None and provenance["before"].get("source") is not None:
        raise _error(path, "Before source requires a Before anchor")
    if before_anchor is not None and provenance["before"].get("source") is None:
        raise _error(path, "an existing Before anchor requires source provenance")

    def find_anchor(identifier: str, side: str) -> dict[str, Any]:
        matches = task_anchors.get(identifier, [])
        if len(matches) != 1:
            raise _error(path, f"{side} anchor is missing or not unique: {identifier}")
        owner, node = matches[0]
        if owner != task_number:
            raise _error(path, f"{side} anchor belongs to Task {owner or 'outside a Task'}")
        attrs = node.get("attrs", {})
        if not isinstance(attrs, dict) or str(attrs.get("data-ui-side", "")).casefold() != side:
            raise _error(path, f"{side} anchor has the wrong data-ui-side: {identifier}")
        if not _visible_markup(node):
            raise _error(path, f"{side} anchor contains empty mock markup: {identifier}")
        return node

    if before_anchor is not None:
        find_anchor(before_anchor, "before")
    find_anchor(after_anchor, "after")

    if before_anchor is not None:
        if source_root is None or not source_root.is_dir():
            raise _error("provenance.before.source", "source_root is unavailable; Before cannot be verified")
        source = str(provenance["before"]["source"])
        revision = allowed_base_ref or declared_ref
        if revision is None:
            raise _error("provenance.before.baseRef", "existing Before requires a fixed commit SHA")
        source_result = _source_result(
            generator,
            task_number,
            source,
            source_root=source_root,
            allowed_prefixes=allowed_prefixes,
            revision=revision,
        )
        code = str(source_result.get("code", ""))
        absent = [label for label in labels if label not in code]
        if absent:
            raise _error(
                "provenance.before.observedLabels",
                "source excerpt does not contain observed label(s): " + ", ".join(absent),
            )

    uncertainty = _uncertainty(preview.get("uncertainty", []), f"{path}.uncertainty")
    return {
        "version": 2,
        "taskNumber": task_number,
        "id": preview_id,
        "title": title,
        "provenance": provenance,
        "before": {"anchor": before_anchor},
        "after": {"anchor": after_anchor},
        "uncertainty": uncertainty,
    }


def collect_html_ui_previews(
    plan_model: dict[str, Any],
    *,
    generator: object,
    source_root: str | Path | None,
    source_allow_prefixes: list[str] | tuple[str, ...] | None = None,
    base_ref: str | None = None,
) -> list[dict[str, Any]]:
    """Return validated, flattened v2 UI preview metadata for HTML Tasks.

    Tasks without a v2 block are ignored, allowing the caller to keep the
    established v1 Markdown/UI normalizer untouched.  A v2 block is strict:
    malformed metadata, stale or missing source evidence, wrong-task anchors,
    and active/empty mock markup all raise ``ValueError``.  The returned
    records contain anchors only; consumers must use ``planDocument`` (or the
    canonical HTML source) to render the corresponding DOM.
    """
    model = _object(plan_model, "plan_model")
    tasks = model.get("tasks", [])
    if not isinstance(tasks, list):
        raise _error("plan_model.tasks", "must be a list")
    candidates: list[tuple[str, dict[str, Any], int]] = []
    for task_index, raw_task in enumerate(tasks):
        task = _object(raw_task, f"tasks[{task_index}]")
        task_number = _text(task.get("number"), f"tasks[{task_index}].number", limit=64)
        blocks = task.get("uiPreviewBlocks", [])
        if blocks is None:
            continue
        if not isinstance(blocks, list):
            raise _error(f"tasks[{task_index}].uiPreviewBlocks", "must be a list")
        v2_blocks = [block for block in blocks if isinstance(block, dict) and block.get("version") == 2]
        if not v2_blocks:
            continue
        if len(v2_blocks) != 1:
            raise _error(f"Task {task_number}", "only one v2 ui-preview block is allowed")
        block = _object(v2_blocks[0], f"Task {task_number}.ui-preview")
        _keys(block, {"version", "taskNumber", "previews"}, f"Task {task_number}.ui-preview")
        if block.get("taskNumber") != task_number:
            raise _error(f"Task {task_number}.ui-preview.taskNumber", "does not match the owning Task")
        previews = block.get("previews")
        if not isinstance(previews, list) or not previews or len(previews) > MAX_PREVIEWS_PER_TASK:
            raise _error(f"Task {task_number}.ui-preview.previews", "must contain one to three previews")
        for preview_index, preview in enumerate(previews):
            candidates.append((task_number, _object(preview, f"Task {task_number}.previews[{preview_index}]"), preview_index))

    if not candidates:
        return []
    document = model.get("planDocument")
    if not isinstance(document, dict):
        raise _error("plan_model.planDocument", "is required for v2 UI previews")
    _keys(document, {"format", "title", "nodes"}, "planDocument")
    if document.get("format") != "html":
        raise _error("planDocument.format", "v2 UI previews require the HTML semantic tree")
    _tasks, anchors = _task_nodes(document)
    source_path = None
    if source_root is not None:
        source_path = Path(source_root).expanduser().resolve(strict=False)
    if base_ref is not None:
        if not isinstance(base_ref, str):
            raise _error("base_ref", "must be a fixed 40-character commit SHA")
        base_ref = base_ref.strip()
    prefixes = _normalise_prefixes(generator, source_allow_prefixes)

    declared_refs = {
        str(preview.get("provenance", {}).get("before", {}).get("baseRef"))
        for _task_number, preview, _index in candidates
        if isinstance(preview.get("provenance"), dict)
        and isinstance(preview.get("provenance", {}).get("before"), dict)
        and preview.get("provenance", {}).get("before", {}).get("source") is not None
        and preview.get("provenance", {}).get("before", {}).get("baseRef") is not None
    }
    if len(declared_refs) > 1 and base_ref is None:
        raise _error("ui-preview", "multiple baseRef values cannot be selected automatically")
    effective_base_ref = base_ref or (next(iter(declared_refs)) if declared_refs else None)
    result: list[dict[str, Any]] = []
    seen_ids: set[tuple[str, str]] = set()
    for task_number, preview, preview_index in candidates:
        preview_id = str(preview.get("id", ""))
        key = (task_number, preview_id)
        if key in seen_ids:
            raise _error(f"Task {task_number}.previews[{preview_index}].id", "duplicates another preview")
        seen_ids.add(key)
        result.append(
            _normalise_preview(
                task_number,
                preview,
                f"Task {task_number}.previews[{preview_index}]",
                task_anchors=anchors,
                allowed_base_ref=effective_base_ref,
                generator=generator,
                source_root=source_path,
                allowed_prefixes=prefixes,
            )
        )
        if len(result) > MAX_TOTAL_PREVIEWS:
            raise _error("ui-preview", f"total preview count exceeds {MAX_TOTAL_PREVIEWS}")
    return result


__all__ = ["collect_html_ui_previews"]
