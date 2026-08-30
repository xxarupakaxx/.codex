#!/usr/bin/env python3
"""Parse Roadmap plan/progress Markdown into a JSON-serializable contract."""

from __future__ import annotations

import hashlib
import re
from bisect import bisect_right
from pathlib import Path
from typing import Any


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


def parse_plan_files(plan_path: str | Path, progress_path: str | Path) -> dict[str, Any]:
    """Read 30_plan.md and 40_progress.md once and parse them."""
    plan = Path(plan_path).read_text(encoding="utf-8")
    progress_file = Path(progress_path)
    progress = progress_file.read_text(encoding="utf-8") if progress_file.exists() else ""
    return parse_plan_contract(
        plan,
        progress,
        plan_source=str(plan_path),
        progress_source=str(progress_path),
    )


def parse_plan_contract(
    plan_text: str,
    progress_text: str = "",
    *,
    plan_source: str = "30_plan.md",
    progress_source: str = "40_progress.md",
) -> dict[str, Any]:
    """Parse already-read plan/progress text into a Roadmap Plan v2 model."""
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
