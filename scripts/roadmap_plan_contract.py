#!/usr/bin/env python3
"""Parse Roadmap plan/progress Markdown into a JSON-serializable contract."""

from __future__ import annotations

import hashlib
import json
import re
from bisect import bisect_right
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


SCHEMA_VERSION = 2
PARSER_VERSION = "2.0.0"

TASK_HEADING_RE = re.compile(
    r"^(#{2,3})[ \t]+(?:Task|タスク)[ \t]+(\d+(?:\.\d+)?)[ \t]*[:：][ \t]*(.*)$",
    re.IGNORECASE | re.MULTILINE,
)
ANY_TASK_HEADING_RE = re.compile(
    r"^(#{1,6})[ \t]+(?:Task|タスク)[ \t]+([0-9.]+)[ \t]*[:：][ \t]*(.*)$",
    re.IGNORECASE | re.MULTILINE,
)
MARKDOWN_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
CHECKBOX_RE = re.compile(r"^\s*[-*]\s+\[([ xX])\]\s+(.+)$", re.MULTILINE)
LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]\s+(?:\[[ xX]\]\s+)?|\d+[.)]\s+)(.+)$", re.MULTILINE)
INLINE_CODE_LINE_RE = re.compile(r"^\s*`([^`\n]+)`\s*$", re.MULTILINE)
PROGRESS_TASK_CHECK_RE = re.compile(
    r"^\s*[-*]\s+\[([ xX])\]\s+(?:Task|タスク)\s+(\d+(?:\.\d+)?)\b.*$",
    re.IGNORECASE | re.MULTILINE,
)
REQUIRED_SECTIONS = {
    "purpose": ("目的", "Purpose"),
    "targets": ("変更対象", "Target", "Targets"),
    "implementation": ("実装", "Implementation"),
    "outputs": ("成果物", "Output", "Outputs", "Deliverables"),
    "verification": ("検証", "Verification", "Verify"),
}
BLOCKED_BY_SECTIONS = ("blockedBy", "Blocked By", "依存", "依存関係")


class PlanContractError(ValueError):
    """Raised when a plan violates a hard parser contract."""


# The authoring document is deliberately a small semantic HTML vocabulary.  It
# is used by the Python parser and is also the contract consumed by the viewer;
# keeping the list here avoids sending arbitrary authoring markup downstream.
HTML_VISIBLE_TAGS = frozenset(
    {
        "a", "article", "aside", "blockquote", "br", "code", "dd", "del",
        "details", "div", "dl", "dt", "em", "figcaption", "figure", "footer",
        "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "i", "input",
        "label", "li", "main", "mark", "ol", "p", "pre", "section", "small",
        "span", "strong", "sub", "summary", "sup", "table", "tbody", "td",
        "tfoot", "th", "thead", "tr", "u", "ul", "s", "svg", "g", "path",
        "circle", "ellipse", "line", "polygon", "polyline", "rect", "text", "title", "desc",
        "defs", "marker", "caption", "col", "colgroup",
    }
)
HTML_DOCUMENT_TAGS = frozenset({"html", "head", "body", "title", "meta", "link", "base", "style"})
HTML_VOID_TAGS = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"})
HTML_HIDDEN_TAGS = frozenset({"script", "style", "meta", "link", "base", "title"})
HTML_FRAGMENT_KINDS = frozenset({"ui-preview", "diagram"})
HTML_SCHEMA_VERSION = 2
HTML_MAX_FRAGMENT_BYTES = 64 * 1024
HTML_TASK_ID_RE = re.compile(r"^(?:task[-_ ]*)?(\d+(?:\.\d+)?)$", re.IGNORECASE)
HTML_STATUS_VALUES = {"planned", "in-progress", "complete", "blocked"}
HTML_BOOL_TRUE = frozenset({"true", "yes", "y", "1", "x", "checked", "complete", "done", "完了"})
HTML_BOOL_FALSE = frozenset({"false", "no", "n", "0", "unchecked", "planned", "未完了"})
HTML_COMMON_ATTRS = frozenset(
    {
        "id", "class", "role", "title", "lang", "dir", "tabindex", "aria-label", "aria-describedby",
        "aria-labelledby", "aria-hidden", "aria-current",
        "data-plan-schema", "data-source-kind", "data-task-id",
        "data-plan-title", "data-plan-intro",
        "data-field", "data-status", "data-done", "data-total", "data-step-index",
        "data-complete", "data-task-ref", "data-acceptance-id", "data-acceptance", "data-source-ref", "data-source",
        "data-dependency", "data-blocked-by", "data-kind", "data-anchor", "data-section", "data-plan-section", "data-plan-task",
        "data-ui-change",
        "data-progress-done", "data-progress-total", "data-global-complete",
    }
)
HTML_TAG_ATTRS = {
    "a": frozenset({"href", "rel", "target"}),
    "input": frozenset({"type", "checked", "disabled", "name", "value"}),
    "label": frozenset({"for"}),
    "th": frozenset({"scope", "headers", "colspan", "rowspan"}),
    "td": frozenset({"headers", "colspan", "rowspan"}),
    "col": frozenset({"span"}),
    "colgroup": frozenset({"span"}),
    "meta": frozenset({"charset", "name", "content", "http-equiv"}),
    "link": frozenset({"href", "rel", "type"}),
    "base": frozenset({"href", "target"}),
    "svg": frozenset({"viewbox", "xmlns", "width", "height", "fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "preserveaspectratio"}),
    "g": frozenset({"fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "transform"}),
    "path": frozenset({"d", "fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "fill-rule", "clip-rule", "transform", "marker-end", "marker-start"}),
    "circle": frozenset({"cx", "cy", "r", "fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "transform"}),
    "ellipse": frozenset({"cx", "cy", "rx", "ry", "fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "transform"}),
    "line": frozenset({"x1", "x2", "y1", "y2", "fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "marker-end", "marker-start", "transform"}),
    "polygon": frozenset({"points", "fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "marker-end", "marker-start", "transform"}),
    "polyline": frozenset({"points", "fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "marker-end", "marker-start", "transform"}),
    "rect": frozenset({"x", "y", "width", "height", "rx", "ry", "fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "transform"}),
    "marker": frozenset({"markerwidth", "markerheight", "refx", "refy", "orient", "viewbox", "markerunits"}),
    "text": frozenset({"x", "y", "fill", "stroke", "stroke-width", "font-size", "font-family", "text-anchor", "transform"}),
}


CSS_ESCAPE_RE = re.compile(r"\\([0-9a-fA-F]{1,6})(?:\s)?|\\([^\r\n])")


def _decode_css_escape(match: re.Match[str]) -> str:
    if match.group(1):
        return chr(int(match.group(1), 16))
    return match.group(2) or ""


def _normalized_css_tokens(value: str) -> str | None:
    if re.search(r"\\(?:\r\n|\r|\n)", value):
        return None
    decoded = CSS_ESCAPE_RE.sub(_decode_css_escape, value)
    return re.sub(r"/\*[\s\S]*?\*/", "", decoded)


def css_has_external_load(value: str) -> bool:
    tokens = _normalized_css_tokens(value)
    return tokens is None or bool(re.search(r"@[\s]*import\b|url\s*\(", tokens, re.IGNORECASE))


def is_safe_svg_paint_value(value: str) -> bool:
    tokens = _normalized_css_tokens(value)
    if tokens is None or not re.search(r"url\s*\(", tokens, re.IGNORECASE):
        return tokens is not None
    return bool(re.fullmatch(r"url\(\s*#[A-Za-z][A-Za-z0-9_-]*\s*\)", tokens.strip(), re.IGNORECASE))


LOCAL_HREF_RE = re.compile(r"(?:#[A-Za-z0-9_.:-]+|(?:\./)?[A-Za-z0-9_.~/-]+(?:#[A-Za-z0-9_.:-]+)?)")


def is_safe_html_href(value: str, *, tag: str, attrs: dict[str, str]) -> bool:
    if not value or any(char.isspace() or ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        return False
    if any(char in value for char in ('\\', "'", '"', "<", ">", "`")) or value.startswith(("/", "//", "~")):
        return False
    try:
        parsed = urlparse(value)
        host = parsed.hostname
        username = parsed.username
        password = parsed.password
        _port = parsed.port
    except ValueError:
        return False
    scheme = parsed.scheme.casefold()
    if scheme in {"http", "https"}:
        rel_tokens = set(attrs.get("rel", "").casefold().split())
        return bool(
            tag == "a"
            and parsed.netloc
            and host
            and username is None
            and password is None
            and attrs.get("target") == "_blank"
            and {"noopener", "noreferrer"}.issubset(rel_tokens)
        )
    if scheme:
        return False
    return bool(LOCAL_HREF_RE.fullmatch(value) and ".." not in Path(value.split("#", 1)[0]).parts)


def _normalize_legacy_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def parse_plan_files(plan_path: str | Path, progress_path: str | Path) -> dict[str, Any]:
    """Read 30_plan.md and 40_progress.md once and parse them."""
    plan_raw = Path(plan_path).read_bytes()
    plan = _normalize_legacy_newlines(plan_raw.decode("utf-8"))
    progress_file = Path(progress_path)
    progress_raw = progress_file.read_bytes() if progress_file.exists() else b""
    progress = _normalize_legacy_newlines(progress_raw.decode("utf-8"))
    model = parse_plan_contract(
        plan,
        progress,
        plan_source=str(plan_path),
        progress_source=str(progress_path),
    )
    model["planSourceRawSha256"] = hashlib.sha256(plan_raw).hexdigest()
    return model


def parse_plan_contract(
    plan_text: str,
    progress_text: str = "",
    *,
    plan_source: str = "30_plan.md",
    progress_source: str = "40_progress.md",
) -> dict[str, Any]:
    """Parse already-read plan/progress text into a Roadmap Plan v2 model."""
    if str(plan_source).casefold().endswith("30_plan.html"):
        return parse_html_plan_contract(plan_text, plan_source=plan_source, progress_source=progress_source)
    _validate_task_headings(plan_text)
    sections = _iter_task_sections(plan_text, plan_source)
    progress_signals = _parse_progress_signals(progress_text)
    global_complete = bool(
        re.search(r"(?:進捗|progress)\s*[:：]\s*100\s*%", progress_text, re.IGNORECASE)
        or re.search(
            r"(?:現在地|current)\s*[:：]\s*(?:完了|complete|completed)",
            progress_text,
            re.IGNORECASE,
        )
    )
    diagnostics: list[dict[str, str]] = []
    tasks: list[dict[str, Any]] = []
    seen_numbers: set[str] = set()
    for section in sections:
        number = section["number"]
        title = section["title"]
        body = section["body"]
        if number in seen_numbers:
            raise PlanContractError(f"duplicate task id: {number}")
        seen_numbers.add(number)
        if not title:
            raise PlanContractError(f"empty task title: {number}")
        if not body.strip():
            raise PlanContractError(f"empty task body: {number}")

        task_sections = _task_subsections(body)
        missing = [
            field
            for field, names in REQUIRED_SECTIONS.items()
            if not _section_by_names(task_sections, names).strip()
        ]
        for field in missing:
            diagnostics.append(
                {
                    "code": "missing_required_section",
                    "task": number,
                    "field": field,
                    "message": f"Task {number} missing required section: {field}",
                }
            )

        stats = _checkbox_stats(body)
        signal = progress_signals.get(number, {})
        total = signal.get("total", stats["total"])
        done = signal.get("done", stats["done"])
        status = signal.get("status", "planned")
        if global_complete and "status" not in signal and signal.get("checked") is not False:
            status = "complete"
        elif signal.get("checked") is True:
            status = "complete"
        elif signal.get("checked") is False and status == "planned" and done > 0:
            status = "in-progress"
        if "status" not in signal:
            if total > 0 and done >= total:
                status = "complete"
            elif done > 0:
                status = "in-progress"
        if status == "complete" and total > 0:
            done = total

        blocked_by = _blocked_by(body, task_sections)
        task = {
            "number": number,
            "title": title,
            "purpose": _summarize(_section_by_names(task_sections, REQUIRED_SECTIONS["purpose"])),
            "targets": _compact_section_items(_section_by_names(task_sections, REQUIRED_SECTIONS["targets"])),
            "implementation": _compact_section_items(
                _section_by_names(task_sections, REQUIRED_SECTIONS["implementation"])
            ),
            "outputs": _compact_section_items(_section_by_names(task_sections, REQUIRED_SECTIONS["outputs"])),
            "verification": _compact_section_items(
                _section_by_names(task_sections, REQUIRED_SECTIONS["verification"])
            ),
            "blockedBy": blocked_by,
            "steps": stats["steps"],
            "done": done,
            "total": total,
            "status": status,
            "body": body,
            "source": {
                "file": section["source"],
                "lineStart": section["lineStart"],
                "lineEnd": section["lineEnd"],
            },
        }
        tasks.append(task)

    task_numbers = {task["number"] for task in tasks}
    edges = _dependency_edges(tasks, task_numbers)
    if not tasks:
        diagnostics.append(
            {
                "code": "no_tasks",
                "message": "No canonical Task headings were found.",
            }
        )
    plan_hash = _sha256(plan_text)
    progress_hash = _sha256(progress_text)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "parserVersion": PARSER_VERSION,
        "sourceHash": _sha256(
            "\0".join(("30_plan.md", plan_hash, "40_progress.md", progress_hash))
        ),
        "sourceHashes": {
            "30_plan.md": plan_hash,
            "40_progress.md": progress_hash,
        },
        "planSourceRawSha256": hashlib.sha256(plan_text.encode("utf-8")).hexdigest(),
        "tasks": tasks,
        "edges": edges,
        "progress": {
            "done": sum(1 for task in tasks if task["status"] == "complete"),
            "total": len(tasks),
            "globalComplete": global_complete,
            "signals": progress_signals,
        },
        "diagnostics": diagnostics,
        "sources": {"plan": plan_source, "progress": progress_source},
    }


def _validate_task_headings(plan_text: str) -> None:
    canonical_spans = {match.span() for match in TASK_HEADING_RE.finditer(plan_text)}
    for match in ANY_TASK_HEADING_RE.finditer(plan_text):
        level = len(match.group(1))
        number = match.group(2)
        title = match.group(3).strip()
        if match.span() in canonical_spans:
            if not title:
                raise PlanContractError(f"empty task title: {number}")
            continue
        if level not in {2, 3}:
            raise PlanContractError(f"task heading must be H2 or H3: {number}")
        if not re.fullmatch(r"\d+(?:\.\d+)?", number):
            raise PlanContractError(f"invalid task id: {number}")
        if not title:
            raise PlanContractError(f"empty task title: {number}")


def _iter_task_sections(plan_text: str, source: str) -> list[dict[str, Any]]:
    matches = list(TASK_HEADING_RE.finditer(plan_text))
    heading_records = [
        (heading.start(), len(heading.group(1)))
        for heading in MARKDOWN_HEADING_RE.finditer(plan_text)
    ]
    heading_starts = [start for start, _ in heading_records]
    line_starts = _line_starts(plan_text)
    sections: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        level = len(match.group(1))
        start = match.end()
        next_task_start = matches[index + 1].start() if index + 1 < len(matches) else len(plan_text)
        end = next_task_start
        heading_index = bisect_right(heading_starts, match.start())
        while heading_index < len(heading_records):
            heading_start, heading_level = heading_records[heading_index]
            if heading_start >= next_task_start:
                break
            if heading_level <= level:
                end = heading_start
                break
            heading_index += 1
        sections.append(
            {
                "number": match.group(2),
                "title": match.group(3).strip(),
                "body": plan_text[start:end],
                "source": source,
                "lineStart": _line_for_offset(line_starts, match.start()),
                "lineEnd": _line_for_offset(line_starts, end),
            }
        )
    return sections


def _task_subsections(body: str) -> dict[str, str]:
    headings = list(MARKDOWN_HEADING_RE.finditer(body))
    sections: dict[str, str] = {}
    for index, match in enumerate(headings):
        level = len(match.group(1))
        title = _strip_markdown(match.group(2)).strip()
        start = match.end()
        next_heading = next(
            (
                heading
                for heading in headings[index + 1 :]
                if len(heading.group(1)) <= level
            ),
            None,
        )
        end = next_heading.start() if next_heading else len(body)
        sections[title.casefold()] = body[start:end]
    return sections


def _section_by_names(sections: dict[str, str], names: tuple[str, ...]) -> str:
    for name in names:
        value = sections.get(name.casefold())
        if value is not None:
            return value
    return ""


def _checkbox_stats(text: str) -> dict[str, Any]:
    matches = list(CHECKBOX_RE.finditer(text))
    steps = [
        {"label": match.group(2).strip(), "complete": match.group(1).lower() == "x"}
        for match in matches
    ]
    return {
        "total": len(matches),
        "done": sum(1 for step in steps if step["complete"]),
        "steps": steps or _fallback_bullet_steps(text),
    }


def _fallback_bullet_steps(text: str) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for match in re.finditer(r"^\s*[-*]\s+(?!\[[ xX]\])(.+)$", text, re.MULTILINE):
        label = match.group(1).strip()
        if label and not re.match(r"^(owner|status|evidence)\s*[:：]", label, re.IGNORECASE):
            steps.append({"label": label, "complete": False})
    return steps


def _compact_section_items(section: str) -> list[str]:
    text = section.strip()
    if not text:
        return []
    listed = [_strip_markdown(match.group(1)).strip() for match in LIST_ITEM_RE.finditer(text)]
    listed = [value for value in listed if value]
    inline_code = [match.group(1).strip() for match in INLINE_CODE_LINE_RE.finditer(text)]
    values = listed or inline_code or [_summarize(text)]
    return list(dict.fromkeys(value for value in values if value))


def _parse_progress_signals(progress_text: str) -> dict[str, dict[str, Any]]:
    signals: dict[str, dict[str, Any]] = {}

    def ensure(number: str) -> dict[str, Any]:
        signals.setdefault(number, {})
        return signals[number]

    for match in PROGRESS_TASK_CHECK_RE.finditer(progress_text):
        ensure(match.group(2))["checked"] = match.group(1).lower() == "x"

    table_columns: dict[str, int] | None = None
    for line in progress_text.splitlines():
        if not re.match(r"^\s*\|.*\|\s*$", line):
            table_columns = None
            continue
        cells = [cell.strip() for cell in line.split("|")[1:-1]]
        if all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        task_index = _index_for(cells, ("タスク", "task"))
        if task_index >= 0:
            table_columns = {
                "task": task_index,
                "status": _index_for(cells, ("状態", "status")),
                "progress": _index_for(cells, ("進捗", "progress")),
            }
            continue
        if table_columns is None:
            continue
        task_cell = cells[table_columns["task"]] if table_columns["task"] < len(cells) else ""
        task_match = re.search(r"(?:Task|タスク)\s+(\d+(?:\.\d+)?)", task_cell, re.IGNORECASE)
        if not task_match:
            continue
        signal = ensure(task_match.group(1))
        status_cell = (
            cells[table_columns["status"]]
            if 0 <= table_columns["status"] < len(cells)
            else ""
        )
        progress_cell = (
            cells[table_columns["progress"]]
            if 0 <= table_columns["progress"] < len(cells)
            else ""
        )
        ratio = re.search(r"(\d+)\s*/\s*(\d+)", progress_cell)
        if ratio:
            signal["done"] = int(ratio.group(1))
            signal["total"] = int(ratio.group(2))
        status = _normalize_status(status_cell)
        if status:
            signal["status"] = status
    return signals


def _dependency_edges(
    tasks: list[dict[str, Any]], known_numbers: set[str]
) -> list[dict[str, str]]:
    edges: list[dict[str, str]] = []
    for task in tasks:
        target = task["number"]
        for source in re.findall(
            r"(?:Task|タスク)\s+(\d+(?:\.\d+)?)",
            task["blockedBy"],
            re.IGNORECASE,
        ):
            if source == target:
                raise PlanContractError(f"self dependency: Task {target}")
            if source not in known_numbers:
                raise PlanContractError(f"unknown dependency: Task {target} blocked by Task {source}")
            edge = {"from": source, "to": target, "kind": "blockedBy"}
            if edge not in edges:
                edges.append(edge)
    return edges


def _blocked_by(body: str, sections: dict[str, str]) -> str:
    match = re.search(r"\*\*blockedBy\s*[:：]\*\*\s*(.+)", body, re.IGNORECASE)
    if match:
        return match.group(1).strip().rstrip("。. ")
    match = re.search(r"^\s*blockedBy\s*[:：]\s*(.+)$", body, re.IGNORECASE | re.MULTILINE)
    if match:
        return match.group(1).strip().rstrip("。. ")
    blocked_section = _section_by_names(sections, BLOCKED_BY_SECTIONS)
    return " ".join(_compact_section_items(blocked_section)).strip().rstrip("。. ")


def _normalize_status(value: str) -> str:
    text = _strip_markdown(value).strip()
    if re.fullmatch(r"(完了|complete|done)", text, re.IGNORECASE):
        return "complete"
    if re.fullmatch(r"(進行中|実行中|in[\s-]?progress|active)", text, re.IGNORECASE):
        return "in-progress"
    if re.fullmatch(r"(blocked|ブロック|停止|失敗)", text, re.IGNORECASE):
        return "blocked"
    if re.fullmatch(r"(未着手|planned|待ち|pending)", text, re.IGNORECASE):
        return "planned"
    return ""


def _index_for(cells: list[str], names: tuple[str, ...]) -> int:
    lowered = [cell.casefold() for cell in cells]
    for name in names:
        if name.casefold() in lowered:
            return lowered.index(name.casefold())
    return -1


def _summarize(text: str) -> str:
    return " ".join(_strip_markdown(text).split())


def _strip_markdown(text: str) -> str:
    return re.sub(r"`([^`]+)`", r"\1", text).strip()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _line_starts(text: str) -> list[int]:
    starts = [0]
    for match in re.finditer(r"\n", text):
        starts.append(match.end())
    return starts


def _line_for_offset(starts: list[int], offset: int) -> int:
    return max(1, bisect_right(starts, offset))


class _HTMLPlanParser(HTMLParser):
    """Small, strict HTML parser used for the canonical authoring source."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.document: dict[str, Any] = {
            "tag": "__document__", "attrs": {}, "children": [], "lineStart": 1,
            "lineEnd": 1,
        }
        self.stack: list[dict[str, Any]] = [self.document]
        self.seen_html = False
        self.seen_head = False
        self.seen_body = False
        self.doctype_seen = False

    @staticmethod
    def _line(parser: "_HTMLPlanParser") -> int:
        return max(1, int(parser.getpos()[0]))

    def _parent_tag(self) -> str:
        return str(self.stack[-1].get("tag", ""))

    def _validate_attrs(self, tag: str, raw_attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        attrs: dict[str, str] = {}
        for raw_name, raw_value in raw_attrs:
            name = raw_name.casefold()
            if name in attrs:
                raise PlanContractError(f"duplicate HTML attribute: {name}")
            if name.startswith("on"):
                raise PlanContractError(f"event handler attribute is not allowed: {name}")
            allowed_for_tag = HTML_COMMON_ATTRS | HTML_TAG_ATTRS.get(tag, frozenset())
            if name not in allowed_for_tag and not name.startswith("aria-"):
                raise PlanContractError(f"HTML attribute is not allowed: {name}")
            value = "" if raw_value is None else str(raw_value)
            if "\x00" in value or len(value) > 8192:
                raise PlanContractError(f"invalid HTML attribute value: {name}")
            if name.startswith("data-") and name not in HTML_COMMON_ATTRS:
                raise PlanContractError(f"HTML data attribute is not allowed: {name}")
            if name == "target" and value not in {"_self", "_blank"}:
                raise PlanContractError("HTML target must be _self or _blank")
            if name == "aria-hidden" and value.casefold() == "true":
                raise PlanContractError("visible plan content cannot be aria-hidden")
            if name == "id" and (not value or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", value)):
                raise PlanContractError("unsafe HTML id")
            if name == "xmlns" and (tag != "svg" or value != "http://www.w3.org/2000/svg"):
                raise PlanContractError("HTML SVG namespace is not allowed")
            if name in {"fill", "stroke", "marker-end", "marker-start"} and not is_safe_svg_paint_value(value):
                raise PlanContractError("external SVG resource is not allowed")
            if name in {"data-task-id", "data-task-ref", "data-step-index", "data-done", "data-total", "data-progress-done", "data-progress-total"} and not value.strip():
                raise PlanContractError(f"empty HTML attribute value: {name}")
            attrs[name] = value
        if tag == "input" and attrs.get("type", "checkbox").casefold() != "checkbox":
            raise PlanContractError("only checkbox inputs are allowed in a plan")
        if tag == "a" and "href" not in attrs:
            raise PlanContractError("plan links require a safe href")
        if "href" in attrs and not is_safe_html_href(attrs["href"], tag=tag, attrs=attrs):
            raise PlanContractError("unsafe HTML href")
        return attrs

    def _new_node(self, tag: str, attrs: dict[str, str]) -> dict[str, Any]:
        return {
            "tag": tag,
            "attrs": attrs,
            "children": [],
            "lineStart": self._line(self),
            "lineEnd": self._line(self),
        }

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.casefold()
        if name not in HTML_VISIBLE_TAGS and name not in HTML_DOCUMENT_TAGS and name != "script":
            raise PlanContractError(f"HTML element is not allowed: {name}")
        if name == "html":
            if self.seen_html or self._parent_tag() != "__document__":
                raise PlanContractError("HTML document has an invalid html root")
            self.seen_html = True
        elif name == "head":
            if self.seen_head or self._parent_tag() not in {"__document__", "html"}:
                raise PlanContractError("HTML document has an invalid head")
            self.seen_head = True
        elif name == "body":
            if self.seen_body or self._parent_tag() not in {"__document__", "html"}:
                raise PlanContractError("HTML document has an invalid body")
            self.seen_body = True
        elif name in {"meta", "link", "base", "title"} and self._parent_tag() not in {"head", "svg"}:
            raise PlanContractError(f"HTML metadata element is outside head: {name}")
        elif name == "style" and self._parent_tag() != "head":
            raise PlanContractError("style is only allowed in HTML head metadata")
        elif self._parent_tag() == "head" and name not in {"meta", "link", "base", "title", "style", "script"}:
            raise PlanContractError(f"visible HTML element is not allowed in head: {name}")
        if name in {"link", "base"}:
            raise PlanContractError(f"HTML head resource element is not allowed: {name}")
        if self._parent_tag() == "style":
            raise PlanContractError("style content must be plain CSS text")

        if name == "script":
            normalized: dict[str, str] = {}
            for raw_name, raw_value in attrs:
                key = raw_name.casefold()
                if key in normalized:
                    raise PlanContractError(f"duplicate HTML attribute: {key}")
                normalized[key] = "" if raw_value is None else str(raw_value)
            script_type = normalized.get("type", "").casefold()
            fragment = normalized.get("data-plan-fragment", "").casefold()
            identifier = normalized.get("id", "")
            if script_type != "application/json":
                raise PlanContractError("executable script is not allowed in a plan source")
            allowed = {"type", "id", "data-plan-fragment"}
            if set(normalized) - allowed:
                raise PlanContractError("JSON plan script has an unsupported attribute")
            if identifier != "plan-envelope" and fragment not in HTML_FRAGMENT_KINDS:
                raise PlanContractError("unknown JSON plan fragment")
            if identifier == "plan-envelope" and fragment:
                raise PlanContractError("plan envelope cannot also be a fragment")
            node = self._new_node(name, normalized)
            node["raw"] = ""
            node["fragment"] = fragment or ("envelope" if identifier == "plan-envelope" else "")
            self.stack[-1]["children"].append(node)
            self.stack.append(node)
            return

        normalized = self._validate_attrs(name, attrs)
        if name == "meta":
            self._validate_meta_attrs(normalized)
        node = self._new_node(name, normalized)
        self.stack[-1]["children"].append(node)
        if name not in HTML_VOID_TAGS:
            self.stack.append(node)

    @staticmethod
    def _validate_meta_attrs(attrs: dict[str, str]) -> None:
        if "charset" in attrs:
            if set(attrs) != {"charset"} or attrs["charset"].casefold() not in {"utf-8", "utf8"}:
                raise PlanContractError("meta charset must be UTF-8")
            return
        if "http-equiv" in attrs:
            if set(attrs) - {"http-equiv", "content"} or attrs["http-equiv"].casefold() != "content-security-policy" or not attrs.get("content"):
                raise PlanContractError("meta http-equiv is limited to Content-Security-Policy")
            return
        if "name" not in attrs or not attrs["name"].strip():
            raise PlanContractError("meta is limited to charset, name, or Content-Security-Policy")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.casefold() not in HTML_VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        name = tag.casefold()
        if len(self.stack) == 1 or self.stack[-1].get("tag") != name:
            raise PlanContractError(f"unbalanced HTML closing element: {name}")
        node = self.stack.pop()
        node["lineEnd"] = self._line(self)
        if name == "style" and css_has_external_load(str(node.get("raw", ""))):
            raise PlanContractError("head style cannot load external resources")
        if name == "script":
            raw = str(node.get("raw", ""))
            if len(raw.encode("utf-8")) > HTML_MAX_FRAGMENT_BYTES:
                raise PlanContractError("JSON plan fragment is too large")
            try:
                value = strict_json_loads(raw)
            except (TypeError, json.JSONDecodeError) as exc:
                raise PlanContractError(f"invalid JSON plan fragment: {exc}") from exc
            if not isinstance(value, dict):
                raise PlanContractError("JSON plan fragment must be an object")
            node["value"] = value

    def handle_data(self, data: str) -> None:
        if not self.stack:
            raise PlanContractError("HTML text is outside the document")
        current = self.stack[-1]
        if current.get("tag") == "script":
            current["raw"] = str(current.get("raw", "")) + data
        elif current.get("tag") == "style":
            current["raw"] = str(current.get("raw", "")) + data
        else:
            current["children"].append(data)

    def handle_comment(self, _data: str) -> None:
        return

    def handle_decl(self, decl: str) -> None:
        if decl.casefold() != "doctype html" or self.doctype_seen:
            raise PlanContractError("only one HTML5 doctype is allowed")
        self.doctype_seen = True

    def unknown_decl(self, data: str) -> None:
        raise PlanContractError(f"unknown HTML declaration: {data}")

    def finish(self) -> dict[str, Any]:
        if len(self.stack) != 1:
            raise PlanContractError(f"unclosed HTML element: {self.stack[-1].get('tag')}")
        html_root = next(
            (child for child in self.document["children"] if isinstance(child, dict) and child.get("tag") == "html"),
            None,
        )
        for label, parent in (("document", self.document), ("html", html_root)):
            if parent is None:
                continue
            for child in parent.get("children", []):
                if isinstance(child, str) and child.strip():
                    raise PlanContractError(f"non-whitespace text is not allowed directly under {label}")
        head = next(
            (child for child in (html_root or {}).get("children", []) if isinstance(child, dict) and child.get("tag") == "head"),
            None,
        )
        if head is not None:
            for child in head.get("children", []):
                if isinstance(child, str) and child.strip():
                    raise PlanContractError("non-whitespace text is not allowed directly under head")
        self.document["lineEnd"] = max(1, int(self.getpos()[0]))
        if self.seen_html:
            roots = [child for child in self.document["children"] if isinstance(child, dict)]
            if len(roots) != 1 or roots[0].get("tag") != "html":
                raise PlanContractError("HTML root must contain one html element")
        return self.document


def _html_walk(node: dict[str, Any]) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for child in node.get("children", []):
        if isinstance(child, dict):
            values.append(child)
            values.extend(_html_walk(child))
    return values


def _html_visible_text(node: object) -> str:
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return ""
    tag = str(node.get("tag", ""))
    if tag in HTML_HIDDEN_TAGS or tag == "input":
        return ""
    return "".join(_html_visible_text(child) for child in node.get("children", []))


def _html_compact_text(value: object) -> str:
    return " ".join(str(value).split()).strip()


def _html_title_text(node: object) -> str:
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return ""
    if node.get("tag") in {"script", "style", "meta", "link", "base"}:
        return ""
    return "".join(_html_title_text(child) for child in node.get("children", []))


def _html_safe_tree(node: object, *, inside_svg: bool = False) -> dict[str, Any] | None:
    if isinstance(node, str):
        return {"text": node} if node else None
    if not isinstance(node, dict):
        return None
    tag = str(node.get("tag", ""))
    if (tag in HTML_HIDDEN_TAGS and not (inside_svg and tag == "title")) or tag in {"html", "head", "body"}:
        children = node.get("children", [])
        safe_children = [item for child in children if (item := _html_safe_tree(child, inside_svg=inside_svg))]
        return {"text": ""} if not safe_children else {"tag": "fragment", "attrs": {}, "children": safe_children}
    if tag not in HTML_VISIBLE_TAGS:
        return None
    attrs: dict[str, str] = {}
    for key, value in node.get("attrs", {}).items():
        key = {
            "viewbox": "viewBox", "markerwidth": "markerWidth", "markerheight": "markerHeight",
            "markerunits": "markerUnits", "refx": "refX", "refy": "refY",
            "preserveaspectratio": "preserveAspectRatio", "strokelinecap": "stroke-linecap",
            "strokelinejoin": "stroke-linejoin", "fillrule": "fill-rule", "cliprule": "clip-rule",
        }.get(key, key)
        attrs[str(key)] = "true" if tag == "input" and key == "checked" else str(value)
    children: list[dict[str, Any]] = []
    is_svg = inside_svg or tag == "svg"
    for child in node.get("children", []):
        safe = _html_safe_tree(child, inside_svg=is_svg)
        if safe is not None and (safe.get("text") != "" or safe.get("children")):
            children.append(safe)
    return {"tag": tag, "attrs": attrs, "children": children}


def _html_content_roots(document: dict[str, Any]) -> list[dict[str, Any]]:
    html_root = next(
        (child for child in document.get("children", []) if isinstance(child, dict) and child.get("tag") == "html"),
        None,
    )
    parent = html_root or document
    body = next(
        (child for child in parent.get("children", []) if isinstance(child, dict) and child.get("tag") == "body"),
        None,
    )
    content_parent = body or parent
    visible_children = [
        child for child in content_parent.get("children", [])
        if isinstance(child, dict) and child.get("tag") not in HTML_HIDDEN_TAGS
    ]
    main_nodes = [child for child in visible_children if child.get("tag") == "main"]
    marked_mains = [
        child for child in main_nodes
        if child.get("attrs", {}).get("id") == "plan-document"
        or "data-plan-schema" in child.get("attrs", {})
    ]
    if len(marked_mains) > 1:
        raise PlanContractError("HTML plan must have one marked main root")
    if marked_mains:
        main = marked_mains[0]
        outside = [child for child in content_parent.get("children", []) if child is not main]
        if any(
            (isinstance(child, str) and child.strip())
            or (isinstance(child, dict) and child.get("tag") not in HTML_HIDDEN_TAGS)
            for child in outside
        ):
            raise PlanContractError("visible HTML content exists outside the canonical main root")
        return [main]
    if len(main_nodes) > 1:
        raise PlanContractError("HTML plan must have one main root")
    if any(isinstance(child, str) and child.strip() for child in content_parent.get("children", [])):
        raise PlanContractError("visible HTML text exists outside a semantic element root")
    return visible_children


def _html_descendants(node: dict[str, Any], *, include_nested_tasks: bool = True) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for child in node.get("children", []):
        if not isinstance(child, dict):
            continue
        if not include_nested_tasks and "data-task-id" in child.get("attrs", {}):
            continue
        values.append(child)
        values.extend(_html_descendants(child, include_nested_tasks=include_nested_tasks))
    return values


def _html_fields(task: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    fields: dict[str, list[dict[str, Any]]] = {}

    def visit(parent: dict[str, Any]) -> None:
        children = parent.get("children", [])
        for index, child in enumerate(children):
            if not isinstance(child, dict):
                continue
            if "data-task-id" in child.get("attrs", {}):
                continue
            raw = child.get("attrs", {}).get("data-field")
            if raw:
                field = str(raw).casefold().replace("_", "-").strip()
                fields.setdefault(field, []).append(child)
                if str(child.get("tag", "")).startswith("h") and str(child.get("tag", ""))[1:].isdigit():
                    level = int(str(child.get("tag"))[1:])
                    region: list[object] = []
                    for sibling in children[index + 1:]:
                        if isinstance(sibling, dict):
                            sibling_tag = str(sibling.get("tag", ""))
                            if sibling_tag.startswith("h") and sibling_tag[1:].isdigit() and int(sibling_tag[1:]) <= level:
                                break
                            if sibling.get("attrs", {}).get("data-field"):
                                break
                        region.append(sibling)
                    if region:
                        fields[field].append({"tag": "__field_fragment__", "attrs": {}, "children": region})
            visit(child)

    visit(task)
    return fields


def _html_field_text(nodes: list[dict[str, Any]]) -> str:
    values: list[str] = []
    for node in nodes:
        if str(node.get("tag", "")).startswith("h") and node.get("attrs", {}).get("data-field"):
            continue
        text = _html_compact_text(_html_visible_text(node))
        if text:
            heading = next(
                (child for child in node.get("children", []) if isinstance(child, dict) and str(child.get("tag", "")).startswith("h")),
                None,
            )
            if heading is not None:
                heading_text = _html_compact_text(_html_visible_text(heading))
                if heading_text and text.startswith(heading_text):
                    text = text[len(heading_text):].strip()
            if text:
                values.append(text)
    return " ".join(values).strip()


def _html_field_items(nodes: list[dict[str, Any]]) -> list[str]:
    values: list[str] = []
    for node in nodes:
        candidates = [
            child for child in _html_descendants(node)
            if child.get("tag") in {"li", "dt", "dd"}
        ]
        if not candidates:
            text = _html_field_text([node])
            if text:
                candidates = [{"tag": "p", "children": [text], "attrs": {}}]
        for candidate in candidates:
            text = _html_compact_text(_html_visible_text(candidate))
            if text:
                values.append(text)
    return list(dict.fromkeys(values))


def _html_bool(value: object, *, default: bool | None = None, field: str = "boolean") -> bool:
    if value is None:
        if default is None:
            raise PlanContractError(f"missing HTML {field}")
        return default
    text = str(value).strip().casefold()
    if text in HTML_BOOL_TRUE:
        return True
    if text in HTML_BOOL_FALSE:
        return False
    raise PlanContractError(f"invalid HTML {field}: {value}")


def _json_unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise PlanContractError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _json_reject_constant(value: str) -> Any:
    raise PlanContractError(f"non-finite JSON number is not allowed: {value}")


def strict_json_loads(value: str) -> Any:
    return json.loads(
        value,
        object_pairs_hook=_json_unique_object,
        parse_constant=_json_reject_constant,
    )


def _html_int(value: object, *, default: int | None = None, field: str = "integer") -> int:
    if value is None or str(value).strip() == "":
        if default is None:
            raise PlanContractError(f"missing HTML {field}")
        return default
    if not re.fullmatch(r"\d+", str(value).strip()):
        raise PlanContractError(f"invalid HTML {field}: {value}")
    return int(str(value).strip())


def _html_task_number(value: object) -> str:
    match = HTML_TASK_ID_RE.fullmatch(str(value or "").strip())
    if not match:
        raise PlanContractError(f"invalid HTML task id: {value}")
    return match.group(1)


def _html_normalize_status(value: object) -> str:
    text = str(value or "").strip().casefold()
    aliases = {
        "done": "complete", "completed": "complete", "完了": "complete",
        "active": "in-progress", "in progress": "in-progress", "進行中": "in-progress",
        "pending": "planned", "待ち": "planned", "blocked": "blocked", "停止": "blocked",
    }
    text = aliases.get(text, text)
    if text not in HTML_STATUS_VALUES:
        raise PlanContractError(f"invalid HTML task status: {value}")
    return text


def _html_reference_values(value: object, *, field: str) -> list[str]:
    text = str(value or "").strip()
    if not text:
        raise PlanContractError(f"empty HTML {field}")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in text):
        raise PlanContractError(f"invalid HTML {field}: control character")
    if "\\" in text:
        raise PlanContractError(f"invalid HTML {field}: backslash")
    match = re.match(r"^(task|workspace|repo):(.+)$", text)
    if not match:
        raise PlanContractError(f"HTML {field} must use an explicit scope: {text}")
    relative, _, anchor = match.group(2).partition("#")
    if not relative or relative.startswith("/") or any(char.isspace() for char in relative):
        raise PlanContractError(f"unsafe HTML {field}: {text}")
    if "," in relative:
        raise PlanContractError(f"HTML {field} accepts one URI per node: {text}")
    parts = relative.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise PlanContractError(f"unsafe HTML {field}: {text}")
    if any(re.search(r"(?:secret|credential|password|api[_-]?key|private[_-]?key|token)", part, re.I) for part in parts):
        raise PlanContractError(f"secret-like HTML {field} is not allowed: {text}")
    if anchor and any(ord(char) < 0x20 or ord(char) == 0x7F for char in anchor):
        raise PlanContractError(f"invalid HTML {field} anchor: control character")
    return [text]


def _html_fragment_payloads(document: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    envelope: dict[str, Any] | None = None
    scripts: list[dict[str, Any]] = []
    for node in _html_walk(document):
        if node.get("tag") != "script":
            continue
        fragment = str(node.get("fragment", ""))
        value = node.get("value")
        if not isinstance(value, dict):
            raise PlanContractError("JSON plan fragment is invalid")
        if fragment == "envelope":
            if envelope is not None:
                raise PlanContractError("plan envelope must appear only once")
            envelope = value
        elif fragment in HTML_FRAGMENT_KINDS:
            node["fragmentValue"] = value
            scripts.append(node)
    if envelope is not None:
        unknown = set(envelope) - {"schemaVersion", "documentHash", "machine"}
        if unknown:
            raise PlanContractError("plan envelope contains unsupported machine fields")
        schema = envelope.get("schemaVersion")
        if schema is not None and schema != HTML_SCHEMA_VERSION:
            raise PlanContractError("plan envelope schemaVersion must be 2")
        if "documentHash" in envelope:
            if envelope["documentHash"] is not None and not isinstance(envelope["documentHash"], str):
                raise PlanContractError("plan envelope documentHash must be a string")
        machine = envelope.get("machine")
        if machine is not None:
            if not isinstance(machine, dict):
                raise PlanContractError("plan envelope machine metadata must be an object")
            forbidden = {"task", "tasks", "body", "purpose", "targets", "implementation", "outputs", "verification", "steps", "title", "text", "description"}
            if any(str(key).casefold() in forbidden for key in machine):
                raise PlanContractError("plan envelope must not duplicate Task prose")
    return envelope, scripts


def parse_html_plan_contract(
    raw: bytes | str,
    *,
    plan_source: str = "30_plan.html",
    progress_source: str = "40_progress.md",
) -> dict[str, Any]:
    """Parse canonical HTML bytes directly into Plan v2 and a safe DOM tree."""
    if isinstance(raw, str):
        raw_bytes = raw.encode("utf-8")
    elif isinstance(raw, bytes):
        raw_bytes = raw
    else:
        raise TypeError("HTML plan source must be bytes or UTF-8 text")
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PlanContractError(f"HTML plan is not valid UTF-8: {exc}") from exc
    if text.startswith("\ufeff"):
        text = text[1:]
    parser = _HTMLPlanParser()
    try:
        parser.feed(text)
        parser.close()
        document = parser.finish()
    except PlanContractError:
        raise
    except Exception as exc:
        raise PlanContractError(f"HTML plan cannot be parsed: {exc}") from exc

    envelope, scripts = _html_fragment_payloads(document)
    content_roots = _html_content_roots(document)
    if not content_roots:
        raise PlanContractError("HTML plan has no visible document content")
    schema_nodes = [
        node for node in _html_walk(document)
        if node.get("attrs", {}).get("data-plan-schema") is not None
    ]
    for node in schema_nodes:
        if node.get("attrs", {}).get("data-plan-schema") != str(HTML_SCHEMA_VERSION):
            raise PlanContractError("HTML plan data-plan-schema must be 2")
    if envelope is not None and envelope.get("schemaVersion", HTML_SCHEMA_VERSION) != HTML_SCHEMA_VERSION:
        raise PlanContractError("HTML plan envelope schemaVersion must be 2")

    seen_ids: set[str] = set()
    for root in content_roots:
        for node in [root, *_html_descendants(root)]:
            identifier = node.get("attrs", {}).get("id")
            if identifier:
                if identifier in seen_ids:
                    raise PlanContractError(f"duplicate HTML id: {identifier}")
                seen_ids.add(identifier)

    task_nodes = [
        node for root in content_roots
        for node in ([root] if "data-task-id" in root.get("attrs", {}) else []) + _html_descendants(root)
        if "data-task-id" in node.get("attrs", {})
    ]
    task_numbers: list[str] = []
    for node in task_nodes:
        number = _html_task_number(node.get("attrs", {}).get("data-task-id"))
        if number in task_numbers:
            raise PlanContractError(f"duplicate task id: {number}")
        task_numbers.append(number)
        if any("data-task-id" in descendant.get("attrs", {}) for descendant in _html_descendants(node)):
            raise PlanContractError(f"nested HTML task section: {number}")

    task_for_node: dict[int, dict[str, Any]] = {}
    for task_node in task_nodes:
        for child in [task_node, *_html_descendants(task_node)]:
            task_for_node[id(child)] = task_node
    scripts_by_task: dict[int, list[dict[str, Any]]] = {}
    for script in scripts:
        owner = task_for_node.get(id(script))
        if owner is not None:
            scripts_by_task.setdefault(id(owner), []).append(script)
        elif script.get("attrs", {}).get("data-plan-fragment"):
            raise PlanContractError("plan JSON fragments must be inside a Task section")

    diagnostics: list[dict[str, str]] = []
    tasks: list[dict[str, Any]] = []
    known_numbers = set(task_numbers)
    all_required_sources: list[str] = []

    def collect_global_required_sources(node: dict[str, Any]) -> None:
        if node in task_nodes:
            return
        field = str(node.get("attrs", {}).get("data-field", "")).casefold().replace("_", "-")
        if field in {"required-sources", "requiredsources"}:
            for candidate in [node, *_html_descendants(node)]:
                raw_ref = candidate.get("attrs", {}).get("data-source-ref")
                if raw_ref:
                    for value in _html_reference_values(raw_ref, field="required source"):
                        if value not in all_required_sources:
                            all_required_sources.append(value)
        for child in node.get("children", []):
            if isinstance(child, dict):
                collect_global_required_sources(child)

    for root in content_roots:
        collect_global_required_sources(root)
    global_node = content_roots[0]
    progress_node = next(
        (
            node for node in [global_node, *_html_descendants(global_node)]
            if node.get("attrs", {}).get("id") == "plan-progress"
        ),
        None,
    )
    progress_attrs = progress_node.get("attrs", {}) if progress_node else {}
    global_attrs = global_node.get("attrs", {})
    global_complete = _html_bool(
        global_attrs.get("data-global-complete", progress_attrs.get("data-global-complete")),
        default=False,
        field="global-complete",
    )
    progress_done = _html_int(
        global_attrs.get("data-progress-done", progress_attrs.get("data-progress-done")),
        default=0,
        field="progress-done",
    )
    progress_total = _html_int(
        global_attrs.get("data-progress-total", progress_attrs.get("data-progress-total")),
        default=len(task_nodes),
        field="progress-total",
    )
    if progress_done > progress_total:
        raise PlanContractError("HTML progress done exceeds total")

    for task_node in task_nodes:
        attrs = task_node.get("attrs", {})
        number = _html_task_number(attrs.get("data-task-id"))
        fields = _html_fields(task_node)
        heading = next(
            (
                child for child in _html_descendants(task_node, include_nested_tasks=False)
                if str(child.get("tag", "")).casefold() in {"h1", "h2", "h3", "h4", "h5", "h6"}
            ),
            None,
        )
        raw_title = _html_compact_text(_html_visible_text(heading)) if heading else ""
        raw_title = re.sub(rf"^(?:Task|タスク)\s+{re.escape(number)}\s*[:：-]?\s*", "", raw_title, flags=re.I).strip()
        title = raw_title or _html_compact_text(attrs.get("aria-label", ""))
        if not title:
            raise PlanContractError(f"empty task title: {number}")

        missing = [
            field for field, aliases in REQUIRED_SECTIONS.items()
            if not _html_field_text(sum((fields.get(alias.casefold().replace("_", "-"), []) for alias in aliases), [])).strip()
        ]
        for field in missing:
            diagnostics.append({"code": "missing_required_section", "task": number, "field": field, "message": f"Task {number} missing required section: {field}"})

        implementation_nodes = fields.get("implementation", [])
        step_nodes = [
            node for node in _html_descendants(task_node, include_nested_tasks=False)
            if node.get("tag") in {"li", "div", "p"}
            and "data-step-index" in node.get("attrs", {})
            and any(node is candidate or node in _html_descendants(candidate) for candidate in implementation_nodes)
        ]
        for impl in implementation_nodes:
            step_nodes.extend(
                node for node in _html_descendants(impl)
                if node.get("tag") == "li" and node not in step_nodes
            )
        for input_node in [node for impl in implementation_nodes for node in _html_descendants(impl) if node.get("tag") == "input"]:
            if input_node.get("attrs", {}).get("type", "checkbox").casefold() != "checkbox":
                raise PlanContractError(f"Task {number} implementation input must be checkbox")
            parent_candidates = [node for impl in implementation_nodes for node in _html_descendants(impl) if input_node in node.get("children", [])]
            for candidate in parent_candidates:
                if candidate.get("tag") == "li" and candidate not in step_nodes:
                    step_nodes.append(candidate)
        unique_steps: list[dict[str, Any]] = []
        seen_step_nodes: set[int] = set()
        for step_node in step_nodes:
            if id(step_node) in seen_step_nodes:
                continue
            seen_step_nodes.add(id(step_node))
            step_attrs = step_node.get("attrs", {})
            checkbox = next((child for child in _html_descendants(step_node) if child.get("tag") == "input"), None)
            if "data-complete" in step_attrs:
                complete = _html_bool(step_attrs.get("data-complete"), field="step complete")
            elif checkbox is not None:
                complete = "checked" in checkbox.get("attrs", {})
            else:
                complete = False
            label = _html_compact_text(_html_visible_text(step_node))
            if label:
                unique_steps.append({"label": label, "complete": complete})
        if not unique_steps:
            unique_steps = []
        done = _html_int(attrs.get("data-done"), default=sum(1 for step in unique_steps if step["complete"]), field="task done")
        total = _html_int(attrs.get("data-total"), default=len(unique_steps), field="task total")
        if done > total:
            raise PlanContractError(f"Task {number} done exceeds total")
        if attrs.get("data-status") is not None:
            status = _html_normalize_status(attrs.get("data-status"))
        elif global_complete:
            status = "complete"
        elif total > 0 and done >= total:
            status = "complete"
        elif done > 0:
            status = "in-progress"
        else:
            status = "planned"
        if status == "complete" and total:
            done = total

        blocked_values: list[str] = []
        blocked_task_ids: list[str] = []
        for key in ("data-blocked-by", "data-dependency"):
            raw_dependency = attrs.get(key)
            if raw_dependency:
                matches = re.findall(r"(?:Task|タスク)?\s*(\d+(?:\.\d+)?)", str(raw_dependency), re.I)
                if not matches:
                    raise PlanContractError(f"invalid dependency reference: {raw_dependency}")
                for ref_number in matches:
                    blocked_task_ids.append(ref_number)
                    blocked_values.append(f"Task {ref_number}")
        for node in fields.get("blocked-by", []) + fields.get("blockedby", []) + fields.get("dependencies", []):
            refs = [
                value for child in [node, *_html_descendants(node)]
                for value in ([child.get("attrs", {}).get("data-task-ref")] if child.get("attrs", {}).get("data-task-ref") else [])
            ]
            for ref in refs:
                ref_match = re.search(r"(?:Task|タスク)?\s*(\d+(?:\.\d+)?)", str(ref), re.I)
                if not ref_match:
                    raise PlanContractError(f"invalid dependency reference: {ref}")
                ref_number = ref_match.group(1)
                blocked_task_ids.append(ref_number)
                blocked_values.append(f"Task {ref_number}")
            if not refs:
                text_value = _html_field_text([node])
                if text_value:
                    blocked_values.append(text_value)
                    blocked_task_ids.extend(re.findall(r"(?:Task|タスク)\s+(\d+(?:\.\d+)?)", text_value, re.I))
        blocked_by = " ".join(dict.fromkeys(blocked_values)).strip().rstrip("。. ")
        for ref_number in blocked_task_ids:
            if ref_number == number:
                raise PlanContractError(f"self dependency: Task {number}")
            if ref_number not in known_numbers:
                raise PlanContractError(f"unknown dependency: Task {number} blocked by Task {ref_number}")

        acceptance_entries: list[dict[str, str]] = []
        for node in fields.get("acceptance", []):
            for candidate in [node, *_html_descendants(node)]:
                raw_id = candidate.get("attrs", {}).get("data-acceptance-id")
                if not raw_id:
                    continue
                ids = [item.strip() for item in str(raw_id).split(",") if item.strip()]
                for acceptance_id in ids:
                    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", acceptance_id):
                        raise PlanContractError(f"invalid acceptance id: {acceptance_id}")
                    description = _html_compact_text(_html_visible_text(candidate))
                    acceptance_entries.append({"id": acceptance_id, "text": description})
        acceptance_ids: list[str] = []
        for entry in acceptance_entries:
            if entry["id"] in acceptance_ids:
                raise PlanContractError(f"duplicate acceptance id: {entry['id']}")
            acceptance_ids.append(entry["id"])

        required_sources: list[str] = []
        for node in fields.get("required-sources", []) + fields.get("requiredsources", []):
            for candidate in [node, *_html_descendants(node)]:
                raw_ref = candidate.get("attrs", {}).get("data-source-ref")
                if raw_ref:
                    required_sources.extend(_html_reference_values(raw_ref, field="required source"))
        required_sources = list(dict.fromkeys(required_sources))
        all_required_sources.extend(value for value in required_sources if value not in all_required_sources)

        source_refs: list[str] = []
        for candidate in [task_node, *_html_descendants(task_node, include_nested_tasks=False)]:
            raw_ref = candidate.get("attrs", {}).get("data-source-ref")
            if raw_ref:
                for value in _html_reference_values(raw_ref, field="source reference"):
                    if value not in source_refs:
                        source_refs.append(value)

        body_parts = [_html_compact_text(_html_visible_text(child)) for child in task_node.get("children", [])]
        body = " ".join(item for item in body_parts if item).strip()
        if not body:
            raise PlanContractError(f"empty task body: {number}")
        fragments = scripts_by_task.get(id(task_node), [])
        ui_blocks = [dict(script.get("value", {})) for script in fragments if script.get("fragment") == "ui-preview"]
        for block in ui_blocks:
            if block.get("version") != 1 or str(block.get("taskNumber")) != number or not isinstance(block.get("previews"), list) or not block.get("previews"):
                raise PlanContractError(f"invalid ui-preview fragment in Task {number}")
        diagrams = [dict(script.get("value", {})) for script in fragments if script.get("fragment") == "diagram"]
        task_source = {
            "file": plan_source,
            "lineStart": int(task_node.get("lineStart", 1)),
            "lineEnd": int(task_node.get("lineEnd", task_node.get("lineStart", 1))),
            "anchor": str(attrs.get("id") or f"task-{number}"),
        }
        tasks.append(
            {
                "number": number,
                "title": title,
                "purpose": _html_compact_text(_html_field_text(fields.get("purpose", []))),
                "targets": _html_field_items(fields.get("targets", [])),
                "implementation": _html_field_items(fields.get("implementation", [])),
                "outputs": _html_field_items(fields.get("outputs", [])),
                "verification": _html_field_items(fields.get("verification", [])),
                "blockedBy": blocked_by,
                "blockedByTaskIds": list(dict.fromkeys(blocked_task_ids)),
                "steps": unique_steps,
                "done": done,
                "total": total,
                "status": status,
                "body": body,
                "source": task_source,
                "acceptanceIds": acceptance_ids,
                "acceptance": acceptance_entries,
                "requiredSources": required_sources,
                "sourceRefs": source_refs,
                "uiChange": _html_bool(attrs.get("data-ui-change"), default=False, field="ui-change"),
                "uiPreviewBlocks": ui_blocks,
                "diagramData": diagrams,
            }
        )

    edges: list[dict[str, str]] = []
    for task in tasks:
        for source in task.get("blockedByTaskIds", []):
            edge = {"from": source, "to": task["number"], "kind": "blockedBy"}
            if edge not in edges:
                edges.append(edge)
    if not tasks:
        diagnostics.append({"code": "no_tasks", "message": "No canonical HTML Task sections were found."})

    title = ""
    for root in content_roots:
        candidates = [node for node in [root, *_html_descendants(root)] if node.get("tag") == "h1"]
        candidate = next((node for node in candidates if "data-plan-title" in node.get("attrs", {})), None)
        candidate = candidate or (candidates[0] if candidates else None)
        if candidate:
            title = _html_compact_text(_html_visible_text(candidate))
            if title:
                break
    if not title:
        for node in _html_walk(document):
            if node.get("tag") == "title":
                title = _html_compact_text(_html_title_text(node))
                if title:
                    break
    safe_nodes: list[dict[str, Any]] = []
    for root in content_roots:
        safe = _html_safe_tree(root)
        if safe is not None and (safe.get("text") != "" or safe.get("children")):
            safe_nodes.append(safe)
    raw_hash = hashlib.sha256(raw_bytes).hexdigest()
    source_hash = _sha256("\0".join(("30_plan.html", raw_hash)))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "parserVersion": PARSER_VERSION + "+html",
        "sourceKind": "html",
        "planSource": "30_plan.html",
        "sourceHash": source_hash,
        "sourceHashes": {"30_plan.html": raw_hash},
        "planSourceRawSha256": raw_hash,
        "tasks": tasks,
        "edges": edges,
        "progress": {
            "done": sum(1 for task in tasks if task["status"] == "complete"),
            "total": len(tasks),
            "globalComplete": bool(global_complete or (tasks and all(task["status"] == "complete" for task in tasks))),
            "signals": {},
            "source": "30_plan.html",
            "declaredDone": progress_done,
            "declaredTotal": progress_total,
        },
        "diagnostics": diagnostics,
        "sources": {"plan": plan_source, "progress": plan_source},
        "requiredSources": list(dict.fromkeys(all_required_sources)),
        "planDocument": {"format": "html", "title": title or "Roadmap", "nodes": safe_nodes},
    }


def parse_html_plan_file(
    plan_path: str | Path,
    *,
    progress_source: str | Path = "40_progress.md",
) -> dict[str, Any]:
    """Read one canonical HTML source as raw bytes and parse it."""
    path = Path(plan_path)
    if path.is_symlink() or not path.is_file():
        raise PlanContractError(f"HTML plan source must be a regular file: {path}")
    try:
        raw = path.read_bytes()
    except (OSError, UnicodeError) as exc:
        raise PlanContractError(f"cannot read HTML plan source: {path}: {exc}") from exc
    return parse_html_plan_contract(raw, plan_source=str(path), progress_source=str(progress_source))


def resolve_plan_source(
    task_dir: str | Path,
    *,
    preloaded_plan_text: str | None = None,
    preloaded_plan_raw_sha256: str | None = None,
    preloaded_progress_text: str | None = None,
) -> dict[str, Any]:
    """Resolve HTML-first plan input, retaining Markdown only as legacy input."""
    task = Path(task_dir)
    if not task.is_dir():
        raise PlanContractError(f"task directory is unavailable: {task}")
    html_path = task / "30_plan.html"
    md_path = task / "30_plan.md"
    progress_path = task / "40_progress.md"
    if html_path.exists() or html_path.is_symlink():
        if preloaded_plan_text is None:
            model = parse_html_plan_file(html_path, progress_source=progress_path)
        else:
            if html_path.is_symlink() or not html_path.is_file():
                raise PlanContractError(f"HTML plan source must be a regular file: {html_path}")
            current_raw = html_path.read_bytes()
            if html_path.is_symlink() or current_raw != preloaded_plan_text.encode("utf-8"):
                raise PlanContractError("preloaded HTML source does not match current file bytes")
            current_hash = hashlib.sha256(current_raw).hexdigest()
            if preloaded_plan_raw_sha256 and preloaded_plan_raw_sha256 != current_hash:
                raise PlanContractError("preloaded HTML source hash does not match current file bytes")
            model = parse_html_plan_contract(
                current_raw,
                plan_source=str(html_path),
                progress_source=str(progress_path),
            )
        return model
    if md_path.exists() or md_path.is_symlink():
        if preloaded_plan_text is None:
            model = parse_plan_files(md_path, progress_path)
        else:
            if md_path.is_symlink() or not md_path.is_file():
                raise PlanContractError(f"Markdown plan source must be a regular file: {md_path}")
            current_raw = md_path.read_bytes()
            normalized = _normalize_legacy_newlines(current_raw.decode("utf-8"))
            if md_path.is_symlink() or normalized != preloaded_plan_text:
                raise PlanContractError("preloaded Markdown source does not match current file bytes")
            current_hash = hashlib.sha256(current_raw).hexdigest()
            progress = preloaded_progress_text
            if progress is None:
                progress = _normalize_legacy_newlines(progress_path.read_bytes().decode("utf-8")) if progress_path.exists() else ""
            model = parse_plan_contract(
                normalized,
                progress,
                plan_source=str(md_path),
                progress_source=str(progress_path),
            )
            if preloaded_plan_raw_sha256 and preloaded_plan_raw_sha256 != current_hash:
                raise PlanContractError("preloaded Markdown source hash does not match current file bytes")
            model["planSourceRawSha256"] = current_hash
        model.setdefault("sourceKind", "legacy-markdown")
        model.setdefault("planSource", "30_plan.md")
        return model
    raise PlanContractError(f"plan source is missing: {html_path}")


parse_plan_source = resolve_plan_source
load_plan_source = resolve_plan_source
